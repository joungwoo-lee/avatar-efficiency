# OBHE — Trajectory 기반 Human Equivalent Effort

[방법론 문서](./OBHE_결과물_기반_Human_Equivalent_Effort_방법론.md)의 구현.

**Claude Code 세션 기록(trajectory JSONL)과 로컬 Git repo를 넣으면, 그 작업의 최종
산출물을 확정하고 "사람이 혼자 했다면 몇 시간"을 계산한다.**

## 동작 흐름

```
trajectory 1..N + repo
   │
   ▼  로컬 결정론 층 (LLM 미사용)
   │   trajectory.py  수정 경로·Bash 후보·작업 요청 추출
   │   gitstate.py    base~end net diff, attribution, 복원 상태 판정
   │   manifest.py    → Artifact Manifest
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
- base commit을 확정 못 하면 지어내지 않고 **UNRECOVERABLE**로 멈춘다.
  자동 승인은 EXACT / HIGH_CONFIDENCE만.

## 파일 구성 (방법론 §17 모듈 매핑)

| 파일 | 담당 | LLM |
|---|---|---|
| `trajectory.py` | JSONL tolerant 파싱, Write/Edit/NotebookEdit 경로, Bash heuristic, 세션 grouping | X |
| `gitstate.py` | base/end 확정, net diff, DIRECT_NET/BASH_NET/GIT_NET/TRANSIENT 분류 | X |
| `manifest.py` | Artifact Manifest 생성 | X |
| `workload.py` | §10 프롬프트 생성, 1회 호출, 응답 검증(카탈로그 밖 행동 강등) | O |
| `rate_engine.py` | 요율 곱셈, rework 가산, 승인 판정, 리포트 | X |
| `rates.json` | **외부 설정** — 행동 11종 + workload 단위별 P50/P80 요율 + complexity 배수 | — |
| `sim_llm.py` | LLM 미연결 데모용 | — |
| `estimate.py` | CLI | — |

## 사용법

```bash
# 전체 파이프라인 (기본 SimLLM 데모)
python estimate.py --trajectory s1.jsonl s2.jsonl --repo /path/repo \
                   --base <시작commit> [--end <종료commit>] [--ai-hours 2]

# 로컬 층만 — 산출물 확정 결과(Manifest) 확인, LLM 미사용
python estimate.py --trajectory s1.jsonl --repo /path/repo --base <commit> --manifest-only

# 테스트
python test_obhe.py
```

`--end` 생략 시 현재 working tree 기준(HIGH_CONFIDENCE). `--base` 생략 시
UNRECOVERABLE — 계산하지 않음.

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

## 실제 LLM 연결

`workload.estimate_workload(manifest, llm, rates)` 의 `llm` 에
`complete_json(prompt, max_tokens) -> dict` 클라이언트를 넘기면 된다.
기본 `SimLLM`은 manifest에서 결정론적으로 장부를 흉내 내는 데모용.

## 리포트 읽는 법

| 항목 | 뜻 |
|---|---|
| Artifact Manifest | 최종 산출물 목록 + attribution + TRANSIENT 제외 목록 |
| Completed Outcomes | 독립 완료 판정 단위 |
| Human Action Ledger | 행동 × workload × 요율 → 행별 P50/P80 |
| RHE P50/P80 | 사람 기준 시간 — 보통 / 넉넉히 |
| 자동승인 | EXACT/HIGH_CONFIDENCE만 "가", 그 외 참고치 |
| Measurement Required | 산출물만으로 수량화 못 한 항목 (숫자 안 지어냄) |
