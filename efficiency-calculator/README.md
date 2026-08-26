# efficiency — AI 효율(speedup) 측정

```
speedup = human_min ÷ agent_min
  human_min = 사람이 생성형 AI 없이 직접 하면 걸리는 시간 (분)
  agent_min = AI가 쓴 시간 + 감독하는 사람이 쓴 시간 (분)
```

측정 구도: 사람과 AI의 **협업** — 두 주체의 에포트를 같은 단위(분)로 합산.
숫자 산출 원칙: **LLM은 "무엇을 몇 번"만 정하고, 시간은 코드가 단가표로만 계산.**

## 입구 2개 (API) — 조합 층 없음, 폴더가 입구다

| 질문 | 입구 폴더 | LLM 호출 |
|---|---|---|
| "이 아바타 업무, AI 시키면 얼마 이득?" (사전) | `counterfactual-api/` — 구 계약 drop-in은 `compat.py`(`estimate_task`), 방법론 조합 선택은 `avatar_api.py`(`estimate_avatar`) | **1회** — 한 호출이 human/agent/감독 세 경로를 같은 완료상태 기준으로 분해(integ-spec §3, paths.py) × rates 단가. 분포(P50/P80) 필요 시 `human="workunit"` |
| "실행된 이 세션, 실제 효율은?" (사후) | `session-api/` — 기본 `req_actions_api.py`, 교차확인 `record_actions_api.py` (각각 `measure`/`measure_batch`+CLI) | **1회** — 분모는 기록 실측(0회), 분자는 할일 정리+행동 분해 병합 1회(기본). `calls="staged"`면 2회(단계 감사). 초소형(검토·입력<100단어 & 산출물<50단어)은 자동 제외 |

```python
# 사전
from avatar_api import estimate_avatar          # counterfactual-api/
estimate_avatar(llm, 카드)                       # 기본: 1회 동시 분해
estimate_avatar(llm, 카드, human="workunit")     # 분자만 카탈로그(P50/P80)

# 사후
from req_actions_api import measure             # session-api/
measure(llm, "세션.jsonl")                       # 기본, LLM 1회
measure(llm, "세션.jsonl", calls="staged")       # 할일→행동 2회 (감사 가능)
from record_actions_api import measure as xcheck # 할일 안 거치는 교차확인
```

분자(방법론): req-actions(사전·사후 기본) · record-actions(사후 교차확인) ·
workunit(사전만 — **사후는 폐기**, session-api/workunit_deprecated.py, §20)
분모: agent-llm(사전 기본) · record(사후 고정, LLM 0회)
반환은 공통 스키마: `{human, agent, speedup, notes}` (+excluded).

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
- AI 읽기량은 비율이 아니라 **등급 × 실측으로 환산** — AI는 전수 탐색
  (brute-force), 사람은 전략적 항해(논문 "Strategic Navigation or Stochastic
  Search?"). 기록에서 읽힌 파일을 3등급으로 갈라 **등급별 실측 읽은 단어수**에
  등급 요율을 적용한다: 기여 자료(실측 단어 그대로 정독) · 훑은 후보(실측 단어
  × 탐색요율 = 정독의 1/10) · 헛읽기(기여 확보 후 시행착오, **0** — 사람은
  열지도 않음). 같은 구간 재읽기는 1회. 판별·재생·집계 전부 코드, LLM 0회.
  구현: `human-effort/requirement-actions/requirement_actions.py`의
  `collect_record_stats`(3등급 분류) → `derive_anchors`(읽기 닻 계산) →
  `apply_anchors`(LLM 추정 치환). 근거: human-effort/doc/PROMPT_DESIGN.md.

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
