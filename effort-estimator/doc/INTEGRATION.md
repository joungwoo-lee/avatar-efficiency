# effort-estimator 인테그레이션 런북 (통합 수행 AI용)

이 문서는 **기존 시스템(mm_app)에서 구 `CounterfactualEstimator`를 본 모듈로 교체하는
작업을 수행하는 AI/개발자를 위한 실행 절차**다. 이 문서만으로 통합을 완주할 수 있어야 한다.
배경 설계는 [README.md](../README.md), 설계서는 `../../docs/effort-estimation/`.

교체 대상: `mm_app` `counterfactual.py`의
`CounterfactualEstimator.estimate_task(title, context, role, skill_names, detail) -> dict`
— 본 모듈 `compat.py`가 같은 시그니처·같은 반환 스키마를 제공한다.

---

## Step 1. 소스 가져오기

```bash
git clone https://github.com/joungwoo-lee/avatar-efficiency.git   # 또는 기존 클론 git pull
```

`effort-estimator/` 폴더에서 다음 5개 파일을 mm_app 안에 **`effort_estimator/`
(하이픈 아님, 언더스코어)** 이름의 폴더로 복사한다:

```
estimator.py  compat.py  rates.json  __init__.py  onprem_llm_sim.py
```

- 폴더명이 `effort_estimator`(언더스코어)여야 Python import가 된다. 하이픈이면 실패.
- `onprem_llm_sim.py`는 테스트용 — 운영에 불필요하면 복사 후 제외 가능.
- `test_estimator.py`, `examples/`도 복사하면 Step 4 검증을 그 자리에서 돌릴 수 있다.

## Step 2. LLM 주입

**반드시 실물 LLM을 명시 주입한다.** 자동 감지는 없다
(실환경 `mm_app/onprem-llm/`은 하이픈 폴더라 import 불가 — 미주입 시 시뮬레이터가 잡힌다).

```python
from effort_estimator import CounterfactualEstimator

# 구 counterfactual.py가 OnpremLLM 인스턴스를 만들던 기존 방식을 그대로 재사용해 주입
ce = CounterfactualEstimator(llm=onprem_llm_instance)
```

llm 계약 (실물이 이미 만족함): `complete_json(prompt: str, max_tokens: int) -> dict`
(파싱 완료된 dict 반환. JSON 문자열 아님.)

## Step 3. 호출부 교체

구 클래스와 이름·시그니처가 같으므로 **import와 생성부만 바꾼다**:

```python
# 구:  from counterfactual import CounterfactualEstimator
# 신:
from effort_estimator import CounterfactualEstimator
ce = CounterfactualEstimator(llm=...)          # 생성자: (llm=None, rates_path=..., max_tokens=2000)
r = ce.estimate_task(title, context, role, skill_names, detail)   # 호출부 변경 없음
```

구 생성자 시그니처가 위와 다르면(예: 인자 없이 내부 생성) 생성부 한 줄만 맞춰 수정.
`skill_names`는 list 또는 str 모두 허용.

## Step 4. 검증 (순서대로, 전부 통과해야 완료)

```bash
# 4-1. 오프라인 단위테스트 (네트워크·LLM 불필요, mock)
cd effort_estimator && python test_estimator.py        # "all tests passed" 확인
```

```python
# 4-2. 실물 LLM 스모크 — 작은 업무 1건
r = ce.estimate_task("메일 회신 초안 작성", "부서장 승인 요청", "PM",
                     ["mail-draft", "summarize"], "첨부 보고서(약 800단어) 검토 후 회신(200단어) 작성")
assert r["error"] is None, r["error"]
for k in ("human_min", "agent_min", "agent_human_min", "agent_ai_min",
          "saved_min", "speedup", "human_breakdown", "agent_breakdown", "rationale"):
    assert k in r, f"missing key: {k}"
assert r["agent_human_min"] > 0            # hitl 0이면 프롬프트/모델 점검
assert abs(r["agent_min"] - (r["agent_human_min"] + r["agent_ai_min"])) < 0.01
```

```text
# 4-3. 구현체 대조 — 구 시스템을 아직 지우기 전이라면
같은 입력 3~5건을 구/신 양쪽에 넣고 human_min·agent_min 자릿수(order of magnitude)가
비슷한지 확인. 2배 이상 계통 차이면 Step 5 요율 이관 미완이 원인일 가능성이 높다.
```

## Step 5. 요율 이관 (정확도 — 필수 권장)

구 `counterfactual.py`의 `PRIMITIVES` dict에 실측/튜닝된 min/unit 값이 있으면,
`rates.json`의 seed 값을 **구 값으로 덮어쓴다** (동일 primitive 이름 매칭, human 카드 우선).
rates.json은 cold-start seed(confidence C)라 구 튜닝값이 있으면 그쪽이 더 정확하다.

주의: 값을 **rates.json에만** 넣는다. 프롬프트(`build_prompt`)에 요율을 넣으면 안 된다(§금지).

## Step 6. 정리

- 구 클래스는 삭제하지 말고 이름만 바꿔 보존(예: `CounterfactualEstimatorLegacy`) — 롤백용.
- 롤백 = Step 3의 import 한 줄을 되돌리면 끝. 데이터 마이그레이션 없음.

---

## 반환 스키마 (구 계약 유지 + 부가 키)

```jsonc
{
  "error": null,                    // 실패 시 문자열. 예외를 raise하지 않음 (구 계약 동일)
  "human_min": 12.5,
  "agent_min": 4.2,                 // = agent_human_min + agent_ai_min
  "agent_human_min": 3.8,           // 사람 시간: 감독(지시·검토·승인·수정지시·수동검증) + 잔여 직접작업
  "agent_ai_min": 0.4,              // 기계 시간 (LLM 생성 ai_io 포함, revision factor 곱 적용)
  "saved_min": 8.3,                 // human_min - agent_min
  "speedup": 2.98,                  // human_min / agent_min (agent_min=0이면 null)
  "human_breakdown": {"search": 6.0, "read": 6.5},     // primitive→분 flat map
  "agent_breakdown": {"draft": 2.0, "verify": 1.8,     // 기계·사람 동명 primitive는 합산
                      "ai_io": {"input_words": 120, "output_words": 400, "minutes": 0.6}},
  "rationale": "...",
  "confidence": "C (...)",          // 부가 키 — 구 소비측은 무시 가능, 저장 권장
  "confidence_notes": []            // 비어있지 않으면 저신뢰 처리 권장
}
```

## 구 대비 의미 변화 (교체 시 인지)

| 항목 | 구 | 신규 |
|---|---|---|
| `agent_human_min` | agent 리스트 내 사람 잔여개입 | 감독 행동 + 잔여 직접작업(draft/edit/data_entry/execute/decide). 감독 오버헤드가 추가 계상되어 구보다 커질 수 있음(더 정확) |
| `speedup` | human/agent_min | 동일 정의. 내부 지표 `human_labor_leverage`(human÷hitl)와는 **다른 지표** — 혼동 금지 |
| 요율 | 코드 내 `PRIMITIVES` | 외부 `rates.json` 3카드(human/agent/hitl) + ai_io |
| 프롬프트 | TAXONOMY 노출 | 요율 미노출 (count 역산 오염 방지) |
| LLM 호출 | 1회 고정 | 1회 + 스키마 검증 실패 시 1회 자동 재시도 (최악 2회) |

## 오류 모드

| 상황 | 동작 |
|---|---|
| LLM 출력 스키마 불량 | 자동 1회 재호출 → 그래도 불량이면 `error` 필드에 기록 (raise 안 함) |
| 미등록 primitive·음수 count | 해당 항목만 폐기, `confidence_notes`에 기록 |
| hitl 빈 배열 | agent_human_min=0 + notes 경고 |
| LLM 통신 실패 | `error` 필드에 예외 문자열 |

## 심화 사용 (신규 스키마 직접 사용 시)

compat 없이 세부 구조(count·unit 포함 breakdown, 시간·hours 병기)가 필요하면:

```python
from effort_estimator import EffortEstimator
r = EffortEstimator(llm).estimate(spec_text)   # spec_text: 자유 텍스트 지침서
# r = { human_only: {minutes, hours, breakdown[]},
#       agent: { minutes, hours,
#                machine: {minutes, breakdown[], ai_io{}, revision_factor},
#                hitl:    {minutes, breakdown[]} },
#       metrics: {human_labor_leverage, automation_share},
#       rationale, confidence, confidence_notes }
```

검증 실패 2회 시 `ValueError` raise (compat과 달리 예외 사용).

## 금지 사항

- 프롬프트(`build_prompt`)에 `rates.json` 요율값 노출 금지 — count 역산 오염.
  (`test_rates_not_in_prompt`가 회귀 감시.)
- LLM에게 시간(분·시)을 직접 출력시키는 프롬프트 개조 금지 — 수량만.
- 출력 저장 시 `agent_human_min`/`agent_ai_min` 세부값을 버리고 `agent_min`만 저장하지 말 것
  — 사람 시간과 기계 시간은 다른 자원.
