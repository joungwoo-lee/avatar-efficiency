# OBHE — Trajectory 기반 Human Equivalent Effort

[방법론 문서](./OBHE_결과물_기반_Human_Equivalent_Effort_방법론.md)의 구현.

**Claude Code 세션 기록(trajectory JSONL)과 로컬 Git repo를 넣으면, 그 작업의 최종
산출물을 확정하고 "사람이 혼자 했다면 몇 시간"을 계산한다.**

## 동작 흐름

```
trajectory 1..N + repo
   │
   ▼  로컬 결정론 층 (LLM 미사용)
   │   trajectory.py  수정 경로·편집 내용·Bash 후보·작업 요청 추출
   │                  + 산출물 겹침 기반 세션→job 그룹핑 (union-find)
   │   gitstate.py    (Git+base 있을 때) base~end net diff, attribution
   │   fsstate.py     (Git 없을 때) Write/Edit 기록 ↔ 현재 파일 대조 복원
   │   manifest.py    → job별 Artifact Manifest
   ▼
   │  LLM 1회 호출 (workload.py, 방법론 §10 프롬프트)
   │   STEP1 완료 결과 분할 → STEP2 결과별 인간 행동 + workload
   │   시간 출력 금지, 요율 비노출, 수량화 불가는 MEASUREMENT_REQUIRED
   ▼
   │  rate_engine.py (LLM 미사용)
   │   workload × rates.json 요율 × complexity + Human Rework
   ▼
RHE P50/P80 리포트
```

핵심 규칙:
- **산출물 확정에 LLM을 쓰지 않는다.** 세션별 diff 합산이 아니라 base~end **net diff** —
  만들다 버린 것(TRANSIENT)은 자동 제외.
- **LLM은 의미 해석 한 구간만** — 완료 결과 분할과 행동량 산정. 시간은 절대 안 정한다.
- **Git은 필수가 아니다 (§7).** base commit + `.git`이 있으면 Git으로 검증하고,
  없으면 trajectory의 Write content / Edit old·new 기록을 현재 파일과 대조해 복원:
  일치 → HIGH_CONFIDENCE, 불일치 → PARTIAL(참고치), 증거 없음 → UNRECOVERABLE.
  Edit 기록은 변경분만 diff로 남으므로 기존 파일 일부 수정이 전체 작성으로
  과대추산되지 않는다.
- 증거가 없으면 지어내지 않는다. 자동 승인은 EXACT / HIGH_CONFIDENCE만.

## LLM이 하는 변환 — 무엇이 들어가서 무엇이 나오나 (실측 예시)

LLM 입력 = **확정된 diff/content + 원래 작업 요청**. 출력 = 완료 결과 목록 +
행동×수량 장부(JSON). **시간은 출력되지 않는다.** cursor-proxy 라이브 실행 결과:

입력 (manifest의 diff + 요청 "로그인을 해시 검증으로 구현하고 token refresh 추가, 테스트 작성"):

```diff
--- src/auth.py
-def login(user, pw):  # TODO, return False
+import hashlib
+def login(user, pw): ... _check(user, sha256(pw)) ...
+def refresh_token(user): return f"tok-{user}"
+++ tests/test_auth.py (신규: test 3개, assert 3개)
```

출력 ① 완료 결과 — diff에서 "무엇이 달성됐나":

```json
"completed_outcomes": [
  {"outcome_id": "O1", "outcome": "로그인이 실제 해시 검증으로 구현됨",
   "evidence": "diff의 import hashlib, _check(...)"},
  {"outcome_id": "O2", "outcome": "토큰 리프레시 추가", "evidence": "def refresh_token"},
  {"outcome_id": "O3", "outcome": "검증 테스트 작성", "evidence": "test 3개, assert 3개"}
]
```

출력 ② 행동 장부 — 각 결과를 사람이 만들려면 뭘 몇 개 했어야 하나:

```json
"action_ledger": [
  {"action": "understand_context", "workload_unit": "module",         "workload": 1, "evidence": "기존 auth 구조 파악"},
  {"action": "design_decide",      "workload_unit": "decision",       "workload": 1, "evidence": "해시·토큰 포맷 결정"},
  {"action": "construct",          "workload_unit": "function_point", "workload": 3, "evidence": "login, _check, _load_users"},
  {"action": "construct",          "workload_unit": "testcase",       "workload": 3, "evidence": "test 함수 3개"},
  {"action": "verify",             "workload_unit": "assertion",      "workload": 3, "evidence": "assert 3개"},
  {"action": "finalize",           "workload_unit": "artifact_review","workload": 1, "evidence": "최종 반영 검토"}
]
```

즉 LLM의 변환 = **코드 변경 조각 → 셀 수 있는 사람 행동 수량 + diff 근거(evidence)**.
행동·단위는 프롬프트가 준 카탈로그에서만 고르게 강제되고 카탈로그 밖은 코드가 버린다.
이후는 LLM 밖: `construct 3 function_point × 35분 = 1.8h` 식으로 요율을 곱해
RHE(이 예시 P50 4.4h)를 코드가 계산한다.

## 다중 세션 → job 그룹핑 (LLM 미사용)

trajectory를 여러 개 넣으면 **같은 파일을 건드린 세션끼리** 한 job으로 묶고
job마다 OBHE를 따로 낸다.

- 두 세션이 공통 경로를 `--min-common`(기본 1)개 이상 건드리면 연결.
  s1∩s2, s2∩s3이면 s1·s3도 한 그룹 — 이어달리기 작업.
- 경로는 cwd 기준 **절대경로로 정규화** — 다른 프로젝트의 같은 상대경로가
  허위 병합되지 않는다.
- 어떤 세션과도 안 겹치면 독립 job.
- **판정은 경로만** — 파일 내용은 grouping에 쓰지 않는다 (내용 대조는 산출물 확정 단계 전용).
- 그룹핑 근거(공통 경로 목록)를 manifest와 리포트에 기록.
- job이 여러 개면 **다른 job이 건드린 경로는 이 job의 diff에서 제거**하고,
  trajectory 증거 없는 변경(GIT_NET)은 귀속 불가로 unresolved 처리 — job 간
  이중계산 방지.

## 파일 구성 (방법론 §17 모듈 매핑)

| 파일 | 담당 | LLM |
|---|---|---|
| `trajectory.py` | JSONL tolerant 파싱, Write/Edit/NotebookEdit 경로, Bash heuristic, 산출물 겹침 job 그룹핑 | X |
| `gitstate.py` | (Git) base/end 확정, net diff, DIRECT_NET/BASH_NET/GIT_NET/TRANSIENT 분류 | X |
| `fsstate.py` | (Git 없음) Write/Edit 기록↔현재 파일 대조, pseudo-diff, 복원 상태 판정 | X |
| `manifest.py` | Artifact Manifest 생성 | X |
| `workload.py` | §10 프롬프트 생성, 1회 호출, 응답 검증(카탈로그 밖 행동 강등) | O |
| `rate_engine.py` | 요율 곱셈, rework 가산, 승인 판정, 리포트 | X |
| `rates.json` | **외부 설정** — 행동 11종 + workload 단위별 P50/P80 요율 + complexity 배수 | — |
| `llm.py` | **LLM 백엔드 팩토리** — `make_llm("cursor"\|"sim"\|"모듈:클래스")`, 교체는 이 함수 하나 | — |
| `cursor_llm.py` | cursor-proxy(OpenAI 호환) 클라이언트 — 기본 백엔드 | — |
| `sim_llm.py` | proxy 없이 돌리는 데모용 시뮬레이터 (`--llm sim`) | — |
| `validate.py` | trajectory 파서 검증 CLI — 추정 없이 추출 요약만 (내용 비노출) | X |
| `estimate.py` | CLI | — |

## 사용법

```bash
# 전체 파이프라인 (기본 SimLLM 데모) — 세션 자동 그룹핑 → job별 리포트
python estimate.py --trajectory s1.jsonl s2.jsonl s3.jsonl \
                   --base <시작commit> [--repo /path/repo] [--end <종료commit>] \
                   [--min-common 1] [--ai-hours 2]

# 로컬 층만 — 그룹핑 + 산출물 확정 결과(Manifest) 확인, LLM 미사용
python estimate.py --trajectory s1.jsonl --base <commit> --manifest-only

# 테스트
python test_obhe.py
```

`--repo` 생략 시 그룹 첫 세션의 cwd 사용. `--end` 생략 시 현재 working tree 기준.
`--base` 생략 또는 Git 없는 프로젝트면 trajectory+filesystem 증거로 복원(§7) —
검증되면 HIGH_CONFIDENCE, 아니면 PARTIAL/UNRECOVERABLE.

## 요율 바꾸는 법

`rates.json`만 수정. `--rates 내파일.json`으로 조직별 교체.

```jsonc
"units": {
  "function_point": { "label": "기능 단위 구현", "p50_min": 35, "p80_min": 60 }
},
"complexity_adjustment": { "low": 0.8, "normal": 1.0, "high": 1.5 },
"expected_rework_ratio": 0.12
```

시간 = workload × 단위요율(P50/P80) × complexity. 실측 human-only 데이터가 쌓이면
값을 교체하고 `meta.rate_confidence`를 올린다.

## LLM 연결 — 교체는 함수 하나

### 계약 (이것만 구현하면 어떤 백엔드든 붙는다)

```python
class MyLLM:
    def complete_json(self, prompt: str, max_tokens: int) -> dict:
        ...
```

| 항목 | 내용 |
|---|---|
| 입력 `prompt` | 완성된 프롬프트 문자열 1개 (작업 지시+규칙+카탈로그+manifest 포함). 백엔드는 내용을 해석·수정하지 않고 그대로 모델에 전달 |
| 입력 `max_tokens` | 응답 토큰 상한 (현재 8000). 무시해도 되지만 응답이 잘리면 JSON 파싱 실패로 처리됨 |
| 반환 | **파싱 완료된 dict** (JSON 문자열 아님). 코드펜스·잡담 제거는 백엔드 책임 — `cursor_llm._extract_json()` 재사용 가능 |
| 반환 dict 키 | `completed_outcomes`, `action_ledger`, `excluded_outputs`, `measurement_required`. 누락 키는 빈 목록으로 처리되므로 필수는 `action_ledger`뿐 |
| 실패 시 | `RuntimeError`(호출 실패) 또는 `ValueError`(JSON 추출 실패)를 raise. 그 외 예외 타입은 재시도 없이 그대로 전파됨 |
| 상태 | 멀티턴 없음 — 호출마다 독립. 상태 저장 불필요 |

호출부(`workload.estimate_workload`)가 보장하는 것: 실패·유효 ledger 0행이면 **1회
재시도**, 소진 시 에러(숫자를 지어내지 않음). 응답 dict의 `action_ledger`는 카탈로그
검증을 거쳐 위반 행은 자동 폐기·`measurement_required` 강등 — 백엔드가 스키마를
완벽히 지키지 못해도 파이프라인은 오염되지 않는다.

### 백엔드 선택 — `llm.make_llm(spec)`

```python
llm = make_llm("cursor")              # cursor-proxy (기본)
llm = make_llm("sim")                 # 데모 시뮬레이터
llm = make_llm("my_pkg.my_mod:MyLLM") # 위 계약 구현체를 동적 로드 — 코드 수정 0줄
llm = make_llm()                      # env OBHE_LLM_BACKEND 값 사용
```

- CLI: `--llm cursor | sim | 모듈경로:클래스명`
- 동적 로드 시 `complete_json` 미구현이면 `TypeError`로 즉시 거부
- cursor-proxy: OpenAI 호환 `127.0.0.1:18741`, 기동 `opencode-cursor-proxy\proxy-start.ps1`,
  env `OBHE_LLM_BASE` / `OBHE_LLM_MODEL`(기본 `gpt-5-mini`)

### 교체 예시 — 사내 API 백엔드

```python
# my_llm.py
import json, urllib.request

class InhouseLLM:
    def complete_json(self, prompt, max_tokens):
        req = urllib.request.Request(
            "https://llm.internal/v1/chat", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"prompt": prompt, "max_tokens": max_tokens}).encode())
        with urllib.request.urlopen(req, timeout=300) as r:
            text = json.loads(r.read())["text"]
        from cursor_llm import _extract_json   # 코드펜스·잡담 방어 재사용
        return _extract_json(text)
```

```bash
python estimate.py --trajectory s1.jsonl --llm my_llm:InhouseLLM
```

## 파서 검증 (실측 완료)

실제 Claude Code trajectory(`~/.claude/projects/*/*.jsonl`)로 검증됨 —
session_id/cwd/timestamp, Write·Edit file_ops, PowerShell·Bash 후보 경로,
git 명령, task request 추출 확인. Windows 세션의 `PowerShell` 툴도 지원.

```bash
# 새 trajectory를 넣기 전 추출 상태 확인 (추정 미수행, 내용 비노출)
python validate.py --trajectory s1.jsonl s2.jsonl [--show-requests]
```

## 리포트 읽는 법

| 항목 | 뜻 |
|---|---|
| Artifact Manifest | 최종 산출물 목록 + attribution + TRANSIENT 제외 목록 |
| Completed Outcomes | 독립 완료 판정 단위 |
| Human Action Ledger | 행동 × workload × 요율 → 행별 P50/P80 |
| RHE P50/P80 | 사람 기준 시간 — 보통 / 넉넉히 |
| 자동승인 | EXACT/HIGH_CONFIDENCE만 "가", 그 외 참고치 |
| Measurement Required | 산출물만으로 수량화 못 한 항목 (숫자 안 지어냄) |
