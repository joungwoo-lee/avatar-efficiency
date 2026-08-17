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

## 파일 구성

| 파일 | 역할 |
|---|---|
| `req_actions_api.py` | **기본 API** — 할일 거치는 방식 (requirement-actions) |
| `record_actions_api.py` | **교차확인 API** — 할일 안 거치는 방식 (record-actions) |
| `record_actions_code_api.py` | **LLM 0회 API** (§32) — 분자까지 코드 실측(읽기 항해 구조 + 쓰기 순계 + 건수 고정 규칙). `humanize=False`(`--raw`)로 휴먼화 기능 끈 대조군 실행 가능 |
| `report_all_sessions.py` | **전 세션 리포트 실행 파일** — 이 PC 세션 전체를 LLM 0회로 측정해 마크다운 리포트(휴먼화 ON/OFF 효과 + 효율 히스토그램 + 전체 세션 디테일 표) 출력. `python report_all_sessions.py [루트] [--out 파일.md]` |
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
**단독 판정 금지** — 쓰기 규모가 AI 산출 전량을 상속(4~5배 과대)하는
한계가 실측 확인됨 (CHANGELOG §20). req-actions 결과의 교차확인용.

```bash
python record_actions_api.py session.jsonl [s2.jsonl ...]
python record_actions_api.py session.jsonl --json
```

```python
from record_actions_api import measure, measure_batch
r = measure(llm, "session.jsonl")        # LLM 1회
r["human"]["min"], r["human"]["anchors"]
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
