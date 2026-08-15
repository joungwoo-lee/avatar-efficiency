# efficiency — AI 효율(speedup) 측정 서브시스템

```
speedup = human_min(분자) ÷ agent_min(분모)
  분자 = 사람이 생성형 AI 없이 직접 하면 걸리는 시간
  분모 = AI 에이전트 + HITL 사람감독을 합쳐서 걸리는 시간
```

측정 구도: **사람과 AI 에이전트의 협업**. 분모는 협업의 두 주체가 각자 쓴
에포트를 같은 단위(분)로 합산한 총 투입 — 사람 몫(지시·검토·승인·잔여작업)과
AI 몫(실제 소모 시간)을 따로 세서 더한다. 어느 한쪽만 세면 협업 비용이
왜곡된다(사람만 세면 AI 자원 공짜, AI만 세면 감독 노동 은폐).

## 구조 — 부품 2개 + 용도별 API 2개

```
efficiency/
├─ human-effort/        [부품·분자] human w/o AI — 방식 2개:
│                       ① 요구사항 기반(기본): Work Unit Catalog × Monte Carlo → P50/P80,
│                         입력 1단계 케이스별(아바타 정의 A-avatar / 트랜스크립트 복원 §23)
│                       ② 구버전 Phase1(primitive_effort.py): LLM 1회 human 행동
│                         count 분해 × human 요율 점값 곱셈 — 교차확인용
├─ agent-effort/        [부품·분모] agent_min
│                       agent_effort.py = 사전 추산 (LLM이 예상 경로 count 분해 × 요율)
│                       transcript_actual.py = 사후 실측 (기록된 동작 집계, LLM 미사용)
├─ counterfactual-api/  [API·아바타 측정 = 사전] 아바타 카드 입력 →
│                       A-avatar 분자 + agent_effort 분모 → 구 계약(integ-spec) 반환
└─ session-api/         [API·세션 측정 = 사후] 트랜스크립트 입력 →
                        §23 복원 분자 + transcript_actual 실측 분모 → speedup 리포트
```

규칙: **human-effort/agent-effort는 부품(분자·분모), *-api는 용도별 조합.**
한 케이스용 1단계 로직을 다른 케이스에 유용하지 않는다.

## 용도별 입구

| 알고 싶은 것 | 입구 |
|---|---|
| "이 아바타 업무, AI화하면 얼마 이득?" (실행 전) | `counterfactual-api/compat.py` — `estimate_task(title, context, role, skills, detail)` |
| "실행된 이 세션, 실제 효율은?" (실행 후) | `session-api/session_api.py` — `measure_session(llm, jsonl)` 또는 CLI |
| 사람 w/o AI 견적만 | `human-effort/estimator.py` |
| agent 시간만 | `agent-effort/` (사전: agent_effort, 실측: transcript_actual) |

## 공통 원칙

- LLM은 수량(count/quantity)만 출력한다. 시간은 코드가 요율·시간분포로만 계산.
- 요율(rates.json)·시간분포(catalog.json)는 프롬프트에 절대 미노출.
- 분자·분모는 서로 다른 산정 자(Work Unit vs primitive) — 실측 보정 전까지
  speedup 절대값은 상대 비교 용도 (agent-effort/README.md 한계 절).
- 분자는 두 자 병행: 요구사항 기반(v0.6, 기본)과 구버전 primitive(교차확인).
  실세션 6개 검증 결과 합산 2% 차 수렴하나 파일 산출물 없는 조사·판단 업무는
  primitive가 과소 — 두 값의 괴리가 큰 케이스는 사람 검토 트리거
  (human-effort/README.md 실측 검증 절).

LLM 백엔드: cursor-proxy(127.0.0.1:18741), 계약 `complete_json(prompt, max_tokens) -> dict`
(`human-effort/onprem_llm_sim.py`).

## 테스트

```bash
cd human-effort && python test_estimator.py          # 33종 (+ --live)
cd agent-effort && python test_agent_effort.py       # 6종
cd counterfactual-api && python test_compat.py       # 4종
cd session-api && python test_session_api.py         # 4종
```
