# agent-effort — 분모(agent_min) 계산 방법론과 모듈

AI 효율(speedup) 산정에서 **분모**를 담당하는 독립 모듈.

```
speedup = human_min ÷ agent_min

분자 = human_min  : 사람이 생성형 AI 없이 직접 하면 걸리는 시간
                    (effort-estimator — v0.6 Work Unit 방법론)
분모 = agent_min  : AI 에이전트 + HITL 사람감독을 합쳐서 걸리는 시간
                    (본 모듈 — 구 방식 그대로, primitive count × 요율)
```

사람이 AI 없이 100분 걸릴 일을 AI 써서 10분에 끝나면 효율 10배.

## 분모 계산 방식 (구 방식 그대로 유지, v0.6에서도 안 바꿈)

```
LLM 1회 호출 → agent 경로(기계가 하는 일) + hitl 경로(사람이 감독/개입하는 일)를
              각각 primitive 행동 이름 + count(횟수/단어수)로 분해
코드가 결정적으로 계산 → count × rates.json 요율 = 분
```

```
agent_min = agent_ai_min(기계시간) + agent_human_min(hitl, 사람감독시간)
```

- LLM은 count만 출력한다. 시간·분·요율은 절대 출력하지 않는다.
- 요율은 프롬프트에 노출하지 않는다 (count 역산 오염 방지).
- 카탈로그 밖 primitive·음수 count는 코드가 폐기한다.

## 요율표 (`rates.json`)

### agent (기계) — 사람보다 요율이 훨씬 낮음

| primitive | 의미 | 단위 | 분/단위 |
|---|---|---|---|
| `plan` | 계획 | 건 | 0.5 |
| `search` | 검색 | 쿼리 | 0.5 |
| `read` | 읽기 | 단어 | 0.0005 |
| `classify` | 분류 | 항목 | 0.01 |
| `draft` | 초안작성 | 단어 | 0.002 |
| `edit` | 수정 | 단어 | 0.001 |
| `data_entry` | 입력 | 레코드 | 0.005 |
| `execute` | 도구실행 | 호출 | 0.3 |
| `verify` | 검증 | 증거 | 0.5 |

예: `read`는 사람 0.005분/단어인데 agent는 0.0005분/단어 — 10배 빠름.

### hitl (사람 감독) — "사람이 AI를 부리는 데 드는 오버헤드"

| primitive | 의미 | 단위 | 분/단위 |
|---|---|---|---|
| `instruct` | 지시 작성 | 건 | 3.0 |
| `review` | 검토 | 단어 | 0.006 |
| `approve` | 승인 | 건 | 1.0 |
| `correct` | 수정지시 | 건 | 4.0 |
| `verify` | 수동검증 | 증거 | 3.0 |
| `decide` | 판단 | 건 | 5.0 |
| `draft`/`edit`/`data_entry`/`execute` | 에이전트가 못 해 사람이 직접 마저 하는 잔여 작업 | — | 사람 요율 |

## AI 처리시간(ai_io) — 별도 가산

```
ai_io_minutes = input_words × 0.00002 + output_words × 0.0015   (분)
```

LLM이 실제로 토큰을 읽고/생성하는 시간 (입력 약 3,000자/분 처리, 출력 약 667자/분 생성 속도).

## 최종 합

```
agent_min = (agent primitive count × rates) + ai_io_minutes   ← 기계 시간(agent_ai_min)
          + (hitl primitive count × rates)                     ← 사람 감독 시간(agent_human_min)
```

예: RCA 업무 16.4분 = jira 조회 몇 번(agent search/execute) + AI 응답 처리(ai_io)
+ 사람의 지시·승인·판단(hitl)을 다 합친 값.

## 한계 — 분자·분모 산정 체계 불일치 편향 (해석 주의)

speedup의 분자와 분모는 **서로 다른 산정 체계**로 계산된다:

| | 산정 체계 | 단위 스케일 |
|---|---|---|
| 분자 human_min | v0.6 Work Unit (완성 산출물 단위, 예: 출처 정밀검토 1건=20분급) | 수 분~수십 분/건 |
| 분모 agent_min | primitive 행동 × 저요율 (구 방식) | 초~분/행동 |

같은 업무를 다른 자로 재는 것이므로 **speedup 절대값에는 체계 불일치 편향이 있다** —
v0.6에서 분자 산정만 바뀌어 speedup 배수가 구 버전 대비 계통적으로 커진 것이 그 증상이다
(분모가 "안정적"이어서가 아니라, 두 자가 서로 보정된 적이 없어서다).

따라서:
- speedup 절대값은 실측 보정(human 실측 ↔ catalog.json, agent 실측 trajectory ↔
  rates.json) 전까지 확정치로 쓰지 말 것. 업무 간 **상대 비교** 용도.
- 구 버전 speedup 시계열과 직접 비교 금지 — v0.6 전환 시점에 단절점 표기.
- 보정의 목표는 두 자를 같은 실측 기준(동일 업무의 human-only 실측 시간과
  agent 실측 시간)에 맞추는 것이다.

## 사용

```bash
python agent_effort.py <spec.txt>            # 업무 설명 → agent_min 리포트
python agent_effort.py <spec.txt> --json
python test_agent_effort.py                  # 오프라인 테스트 (mock)
```

```python
from agent_effort import estimate_agent_min, speedup
r = estimate_agent_min(llm, spec_text)   # llm: complete_json(prompt, max_tokens)->dict
r["agent_min"], r["agent_ai_min"], r["agent_human_min"]
speedup(human_min, r["agent_min"])       # = human_min / agent_min
```

분자(human_min)는 `../effort-estimator`의 `HumanEffortEstimator`가 산정한다.
LLM 백엔드는 cursor-proxy(127.0.0.1:18741) — `../effort-estimator/onprem_llm_sim.py`
계약(`complete_json(prompt, max_tokens) -> dict`)과 동일.

## 요율 보정

`rates.json`만 수정 (cold-start seed, confidence C). 실측 trajectory가 쌓이면 교체.
프롬프트에는 절대 넣지 않는다.
