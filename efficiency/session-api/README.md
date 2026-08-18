# session-api — 세션 측정 API (사후, 실행된 세션의 AI 효율)

실행된 Claude Code 세션 트랜스크립트(JSONL) 1개를 넣으면
**"이 세션이 실제로 얼마나 효율적이었나"**를 계산한다.

```
speedup = human_min(분자) ÷ agent_min(분모)

분자(human) — 방식 선택:
  req-actions    (기본) 기록→할일→사람 행동×요율. 규모 숫자는 코드 닻이 확정
                 (읽기 = 등급별 실측 단어: 기여 파일 실측 정독 + 훑기 실측×
                 탐색요율(1/10) + 헛읽기 0, 재읽기 중복 제거; 쓰기 = 산출물 상한).
                 calls="single"이면 할일 정리+행동 분해를 LLM 1회로 병합.
  record-actions 할일 안 거치고 기록에서 바로 행동 분해. 같은 닻 적용.
                 교차확인 기준선 — 쓰기 규모가 AI 산출 전량을 상속(4~5배 과대),
                 대화 형태를 노동으로 오인하는 한계 (CHANGELOG §20 대조 실험).
분모: 트랜스크립트에 기록된 동작 단서 × 요율  (../agent-effort/transcript_actual,
      LLM 미사용 — tool 호출·생성/읽기 단어(기계) + 지시·검토·중단(hitl))
      병렬 서브에이전트는 실제 소모 시간이 아니므로 미가산 (자원량 참고 옵션만).
      긴 세션의 압축 요약·시스템 주입 텍스트도 사람 지시가 아니므로 제외
      (CHANGELOG §17)
```

workunit 방식(요구사항→산출물 단위→Monte Carlo)의 사후 측정은 **폐기** —
`workunit_deprecated.py`에 참고 보관 (근거: CHANGELOG §20 신구 대조).

사전(아바타 정의 시점) 측정은 [`../counterfactual-api`](../counterfactual-api) —
같은 speedup 정의, 입력만 다름.

## 세 자의 위치 — 어느 자가 뭘 재나 (필독)

세 API는 같은 세션을 다른 자로 잰다. **핵심: `record_actions_code_api`의
건수형은 AI 행동의 코드 변환이 아니라 "직행 경로의 바닥값"이다** —
검색을 40번 했어도 search 1건("흔적 있으면 1건" 규칙). 따라서:

```
record_actions_code_api  = 바닥 자. 직행 경로의 최소값을 코드로 박음 (LLM 0회)
req_actions_api          = 바닥 근처. 직행 지시 + 할일 중간층 + 건수 상한(코드
                           강제)이 바닥으로 수렴시킴. LLM이 항목을 누락하면
                           바닥 밑으로도 감 (닻은 조정만 하고 추가하지 않음)
record_actions_api       = 위쪽. 직행 지시는 있으나 요약 속 활동 신호(검색·
                           실행·왕복 횟수)에 LLM이 앵커링되고, 건수 상한을
                           의도적으로 안 달아(비대칭 장치, §29) 궤적 냄새를
                           간직한 기준선
```

10세션 실측(primitive별): 닻이 있는 draft/edit/read는 세 자가 **완전 동일**,
닻이 없는 건수형(decide/execute/verify/search 등)만 rec가 +37min(26%) 위 —
"숫자 결정권을 코드로 옮긴 곳만 결정론이 된다"의 실측 증명. 예상 순서는
항상 **req ≈ code ≤ rec**이며, 이 순서가 깨지면 측정 버그를 의심할 것
(§29·§30·§33의 사고들이 전부 이 순서 역전으로 발견됨).

### req vs rec — 둘 다 "사람이 했다면"으로 재구성한다. 차이는 딱 하나

두 LLM 자 모두 사람 행동 목록을 짜고 같은 닻을 쓴다. 갈리는 건
**행동을 짜는 LLM이 무엇을 보고 짜느냐**:

- **req**: 기록에서 먼저 "완성해야 했던 결과물(할일)"만 추린 뒤, 행동 분해
  LLM에게는 **그 할일 목록만** 보여준다 — 완성된 요리 사진만 보고 레시피
  견적을 내는 방식. 세션의 경위는 행동 설계 입력에서 차단된다.
- **rec**: 중간 정리 없이 **세션 요약을 직접 보면서** 행동을 짠다 — 주방
  CCTV 요약을 보며 견적을 내는 방식. "따라가지 말라"고 지시해도 눈앞의
  활동 신호(검색·실행·왕복 횟수)에 끌린다(앵커링).

이 한 차이에서 파생: 쓰기 스코프(req는 할일에 없으면 못 들어옴 — §20에서
14,700→300단어 절삭 실측), 닻 재료(req만 명시 수량·완료조건 닻 추가),
건수형 상한(§29, req만), 자의 위치(직행 vs 궤적). **rec는 더 나은 자가
아니라 req를 검산하는 거울이다** — req ≤ rec 순서와 간격(직행 자와 궤적
자의 거리)이 상식적인지 보는 용도.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `req_actions_api.py` | **기본 API** — 할일 거치는 방식 (requirement-actions). 직행 자 — 바닥 근처 |
| `record_actions_api.py` | **교차확인 API** — 할일 안 거치는 방식 (record-actions). 궤적 냄새를 간직한 기준선 — 위쪽 자 |
| `record_actions_code_api.py` | **LLM 0회 API** (§32) — 분자까지 코드 실측(읽기 항해 구조 + 쓰기 순계 + 건수형은 행동 순계(§46~48): 검색=착지-기여 문서당 1건·실행=명령 신원당 1건(실패 호출 상쇄), 하한 1. 셸 속 grep·sed류는 검색·읽기 축으로 재분류(§47)). `humanize=False`(`--raw`)로 휴먼화 기능 끈 대조군 실행 가능 |
| `record_actions_code_api_all_sessions.bat` / `.sh` | **원클릭 실행 파일** (Windows 더블클릭 / Linux `./record_actions_code_api_all_sessions.sh`) — 그 PC 홈(`~/.claude/projects`)의 세션 전체를 LLM 0회로 측정해 **실행한 위치**(더블클릭이면 파일 폴더)에 `session-efficiency-report.md` 저장 |
| `record_actions_code_api_all_sessions.py` | 위 실행 파일의 본체 — 마크다운 리포트(휴먼화 ON/OFF 효과 + 효율 히스토그램 + 전체 세션 디테일 표) 생성. 직접 쓸 때: `python record_actions_code_api_all_sessions.py [루트] [--out 파일.md]` |
| `session_api.py` | 공용 코어 — 분모 실측·초소형 게이트·`measure_session(human=...)` |
| `workunit_deprecated.py` | 폐기된 workunit 세션 측정 (참고 보관) |

## 사용 — API ① req-actions (기본)

할일 정리 → 사람 행동 → 요율. 규모 숫자는 코드 닻이 확정.

```bash
python req_actions_api.py session.jsonl [s2.jsonl ...]   # 세션별 + 합산 리포트
python req_actions_api.py session.jsonl --json
python req_actions_api.py session.jsonl --staged   # 할일→행동 2회 (단계 감사)
```

```python
from req_actions_api import measure, measure_batch
r = measure(llm, "session.jsonl")        # LLM 1회 (할일+행동 병합)
r = measure(llm, "session.jsonl", calls="staged")   # LLM 2회, 단계별 감사
r["speedup"]                             # human_min / agent_total
r["speedup_vs_hitl"]                     # 사람 감독시간만 분모로
r["human"]["min"], r["human"]["breakdown"]
r["human"]["todos"]                      # 내부 정리된 할일 목록
r["human"]["anchors"]                    # 코드가 확정한 규모 닻 (감사용)
```

## 사용 — API ② record-actions (교차확인 기준선)

할일 안 거치고 기록에서 바로 행동 분해. 같은 닻 적용.
**단독 판정 금지** — 프롬프트는 직행을 지시하지만 입력 요약의 활동 신호
(검색·실행·왕복 횟수)에 LLM이 앵커링되고 건수 상한도 의도적으로 없어
(§29 비대칭 장치) 건수형이 부푼다. 그래서 req-actions보다 **크게 나오는
것이 정상**이고, 그 간격이 곧 "직행 자와 궤적 자의 거리"다. req-actions
결과의 교차확인용.

```bash
python record_actions_api.py session.jsonl [s2.jsonl ...]
python record_actions_api.py session.jsonl --json
```

```python
from record_actions_api import measure, measure_batch
r = measure(llm, "session.jsonl")        # LLM 1회
r["human"]["min"], r["human"]["anchors"]
```

## 사용 — API ③ record-actions w/o LLM (바닥 자, LLM 0회)

분자까지 전부 코드 실측 — 비용 0, 완전 결정론(같은 입력 = 같은 결과).
건수형은 **행동 순계**(§46~48) — 읽기 3등급·쓰기 순계의 원리를 건수에 적용:

- **검색** = 착지-기여 문서당 1건 (쿼리 다듬기는 그 1건에 흡수, 착지 없는
  검색은 자동 0). 셸 속 grep·find류도 검색 축으로 재분류(§47).
- **실행** = 정규화 명령 신원당 1건 (같은 명령 반복 = 번복 상쇄, 실패
  호출은 쓰기 순계의 실패 편집 제외처럼 상쇄 — §48). 셸 속 sed·cat류는
  조회형 읽기로 재분류(§47), 리다이렉트·히어독·sed -i는 실행 잔류.
- 클램프: 항목별 하한 1(흔적 있으면 최소 1건) · 상한 기록 호출 수 —
  act OFF(로레코드) 이하가 구조적으로 보장(§43).

절대값은 여전히 보수적 — 판단 노동이 깊은 세션은 과소. 켬/끔 대조와
세션 간 비교, 대량 일괄 측정 용도.

```bash
python record_actions_code_api.py session.jsonl [s2.jsonl ...]
python record_actions_code_api.py session.jsonl --raw    # 휴먼화 끈 대조군
```

조합 순서 규약 — 모든 표·리포트·문서에서 이 순서를 지킨다:
**rw ON·act ON → rw OFF·act ON → rw ON·act OFF → rw OFF·act OFF(로레코드)**

```python
from record_actions_code_api import measure, measure_batch
# 휴먼화 2축 (§40): 끈 만큼 "AI 궤적을 그대로 사람이 한 셈"에 가까워짐
r = measure("session.jsonl")                      # rw ON · act ON (기본)
r = measure("session.jsonl", humanize_rw=False)   # rw OFF · act ON
#   (검토 전량 정독·번복 미소거, CLI --norw)
r = measure("session.jsonl", humanize_act=False)  # rw ON · act OFF
#   (행동 횟수를 세션 기록 그대로, CLI --noact)
r = measure("session.jsonl", humanize_rw=False, humanize_act=False)
#   rw OFF · act OFF = 로레코드 (CLI --norw --noact)
r = measure("session.jsonl", humanize=False)      # 구 인터페이스도 그대로 동작
r["human"]["humanize_rw"], r["human"]["humanize_act"]
r["suspect_output_channel"]                       # 쓰기 툴 포맷 미등록 의심(§38)
```

## 공용 (두 API 동일)

```bash
python session_api.py session.jsonl --actual-only    # 분모 실측만 (LLM 불필요)
python test_session_api.py                           # 오프라인 테스트 (mock)
```

```python
from session_api import JsonRetryLLM
llm = JsonRetryLLM(OnpremLLM())          # 프록시 불량 JSON 자동 재시도
```

반환 스키마는 두 API 동일: `{session, session_id, human: {min, method,
anchors, todos, breakdown}, agent: {machine_min, hitl_min, total_min, ...},
speedup, speedup_vs_hitl, notes}` (+초소형이면 `{excluded, reason}`).

## 초소형 세션 자동 제외

측정 전에 실측치로 판정해 잡담·핑퐁급 세션은 **측정에서 제외**한다 (LLM 호출 0회):
- 기준: 검토·입력 자료 100단어 미만 그리고 산출물 50단어 미만
- 근거: 14세션 실측에서 초소형은 완료조건 고정비로 5~7배 역부풀림 확인
- 반환: `{"excluded": true, "reason": ...}` — 강제 측정은 `force=True`

## 해석 주의

- 요율은 seed 다수 포함, 보정 전 — 절대값보다 세션 간 **상대 비교** 용도
  (../agent-effort/README.md 한계 절).
- 잡담·테스트성 세션은 요구사항 자체가 무의미해 수치 의미 없음.
- record-actions 수치는 기준선 비교용 — 단독 판정에 쓰지 말 것 (§20).
