# session-api — 세션 측정 API (사후, 실행된 세션의 AI 효율)

실행된 Claude Code 세션 트랜스크립트(JSONL) 1개를 넣으면
**"이 세션이 실제로 얼마나 효율적이었나"**를 계산한다.

```
speedup = human_min(분자) ÷ agent_min(분모)

분자: 트랜스크립트에서 완료된 요구사항 복원(설계서 §23, 철회 정리·delivered 판정)
      → 사람 w/o 생성형AI 견적  (../human-effort, LLM 2회)
분모: 트랜스크립트에 기록된 실제 동작 실측 × 요율  (../agent-effort/transcript_actual,
      LLM 미사용 — tool 호출·생성/읽기 단어(기계) + 지시·검토·중단(hitl))
      서브에이전트 파일의 기계 동작 자동 합산
```

사전(아바타 정의 시점) 측정은 [`../counterfactual-api`](../counterfactual-api) —
같은 speedup 정의, 입력만 다름.

## 사용

```bash
python session_api.py session.jsonl [s2.jsonl ...]   # 세션별 + 합산 리포트
python session_api.py session.jsonl --json
python session_api.py session.jsonl --actual-only    # 분모 실측만 (LLM 불필요)
python test_session_api.py                           # 오프라인 테스트 (mock)
```

```python
from session_api import measure_session, JsonRetryLLM
llm = JsonRetryLLM(OnpremLLM())          # 프록시 불량 JSON 자동 재시도
r = measure_session(llm, "session.jsonl")
r["speedup"]                             # human_p50 / agent_total
r["speedup_vs_hitl"]                     # 사람 감독시간만 분모로
r["human"]["review_required"]            # True면 human 견적 사람 검토 필요
```

## 해석 주의

- 분자(Work Unit 자)와 분모(primitive 실측 자)는 보정 전 — 절대값보다 세션 간
  **상대 비교** 용도 (../agent-effort/README.md 한계 절).
- 잡담·테스트성 세션은 요구사항 자체가 무의미해 수치 의미 없음.
- `review_required` 플래그가 선 세션의 human 견적은 확정값으로 쓰지 말 것.
