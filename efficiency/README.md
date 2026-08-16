# efficiency — AI 효율(speedup) 측정

```
speedup = human_min ÷ agent_min
  human_min = 사람이 생성형 AI 없이 직접 하면 걸리는 시간 (분)
  agent_min = AI가 쓴 시간 + 감독하는 사람이 쓴 시간 (분)
```

측정 구도: 사람과 AI의 **협업** — 두 주체의 에포트를 같은 단위(분)로 합산.
숫자 산출 원칙: **LLM은 "무엇을 몇 번"만 정하고, 시간은 코드가 단가표로만 계산.**

## 조합 층 — `api.py` (방법론을 명령한 조합으로)

방식 선택은 전부 여기 인자로만 한다. 다른 모듈은 부품이다.

```python
from api import estimate_avatar, measure_session

estimate_avatar(llm, 카드)                                  # 기본: 1회 동시 분해
estimate_avatar(llm, 카드, human="workunit")                # 분자만 카탈로그(P50/P80)
estimate_avatar(llm, 카드, human="req-actions", agent="agent-llm")

measure_session(llm, 세션.jsonl)                            # 기본: 분자 workunit + 분모 실측
measure_session(llm, 세션.jsonl, human="req-actions")       # 분자를 닻 방식으로
measure_session(llm, 세션.jsonl, human="record-actions")    # 할일 안 거치는 교차확인
```

분자(방법론 3종): req-actions(사전 기본) · workunit · record-actions(사후 전용)
분모: agent-llm(사전 기본) · record(사후 고정, LLM 0회)
호출 병합: 사전 기본 조합(req-actions+agent-llm)+calls="single"이면 한 프롬프트로 LLM 1회 — 방법론이 아니라 호출 최적화
호출 수 조절: `calls="single"` — 어느 조합이든 분자를 한 호출로 접음
(workunit→Prompt C, req-actions→내부 할일 포함 단일호출; 사후 req-actions는
세션당 LLM 1회까지 내려감). 감사·재처리가 필요한 정식 산정은 staged.
반환은 공통 스키마: `{human, agent, speedup, notes}` (+excluded).

## 입구 2개 (API)

| 질문 | 입구 | LLM 호출 |
|---|---|---|
| "이 아바타 업무, AI 시키면 얼마 이득?" (사전) | `counterfactual-api/compat.py` — `estimate_task(카드)` | **1회** — 한 호출이 human/agent/감독 세 경로를 같은 완료상태 기준으로 분해(integ-spec §3, paths.py) × rates 단가. 분포(P50/P80) 필요 시 `human_method="workunit"`(3회) |
| "실행된 이 세션, 실제 효율은?" (사후) | `session-api/session_api.py` — `measure_session(jsonl)` | 2회 — 분모는 기록 실측(0회), 분자는 할일 복원→견적(2회). 초소형(검토·입력<100단어 & 산출물<50단어)은 자동 제외 |

## 부품

```
human-effort/    분자 — 방식 3종 (폴더별, README 참조)
agent-effort/    분모 — 사전 추산(agent_effort.py) · 세션 실측(transcript_actual.py)
                 rates.json = 행동 단가표 단일 출처 (프롬프트 미노출)
counterfactual-api/  사전 API + 구 계약(integ-spec) drop-in
session-api/         사후 API + 초소형 게이트
```

## 측정 기조 (요지)

- 감독(hitl)은 세션 시간 측정이 아니라 **단서 × 단가** — 검토·후작업은 세션
  밖에서 할 수 있어 시간 재기로는 못 잡는다. 타임스탬프는 단가 보정 재료로만.
- 병렬 서브에이전트는 실소모 시간에 가산 금지.
- AI가 읽고 쓴 양은 사람 견적의 **상한이지 목표가 아니다** — 사람은 선별해서
  읽고, 요구된 분량만 쓴다. 목표는 할일에 적힌 수량·완료조건에서만 나온다.

## 신뢰도 현황

- 단가는 대부분 전문가 초기값(confidence C). **실측 보정 완료 1건**:
  지시 작성 단가(타임스탬프 1,456건 → 0.5분+0.05분/단어, 60단어 상한).
- 사람 실측 정답지 0건 — 절대값은 참고치, 세션·업무 간 상대 비교 용도.
- 남은 한계·다음 단계: [CHANGELOG.md](CHANGELOG.md) 미해결 절.

개선 이력 전체: [CHANGELOG.md](CHANGELOG.md) ·
프롬프트 설계 근거: [human-effort/doc/PROMPT_DESIGN.md](human-effort/doc/PROMPT_DESIGN.md)

## 테스트

```bash
cd human-effort && python test_estimator.py          # (+ --live 회귀)
cd agent-effort && python test_agent_effort.py
cd counterfactual-api && python test_compat.py
cd session-api && python test_session_api.py
```
