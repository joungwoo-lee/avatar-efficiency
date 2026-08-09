# effort-estimator 인테그레이션 스펙 (AI 통합용)

대상: 이 모듈을 호스트 시스템(mm_app 등)에 통합하는 AI/개발자.
설계 배경 불필요 — 이 문서만으로 통합 가능해야 함. 상세는 [README.md](README.md).

## 1. 제공 함수

```python
from estimator import EffortEstimator

est = EffortEstimator(llm)          # llm: 아래 §2 계약 객체
result = est.estimate(spec_text)    # spec_text: str → result: dict (§4)
```

- 구 시스템(`CounterfactualEstimator.estimate_task`) 자리에 그대로 꽂으려면 §7의 `compat.py` 사용.
- 순수 Python 3.8+, 외부 패키지 의존 없음(stdlib만).
- 파일 의존: `estimator.py` + 같은 폴더의 `rates.json` (경로 커스텀: `EffortEstimator(llm, rates_path=...)`).
- 상태 없음·스레드당 인스턴스 자유. 1회 estimate = LLM 1~2회 호출(검증 실패 시에만 2회).

## 2. LLM 의존성 계약 (호스트가 주입)

```python
class YourLLM:
    def complete_json(self, prompt: str, max_tokens: int) -> dict: ...
```

- 반환은 파싱 완료된 dict (JSON 문자열 아님).
- 온프렘 실환경: `mm_app/onprem-llm/onprem_llm.py`의 `OnpremLLM` 그대로 주입.
- 로컬/테스트: 동봉 `onprem_llm_sim.OnpremLLM()` (OpenAI 호환 endpoint,
  env `AE_LLM_BASE` 기본 `http://127.0.0.1:18741/v1`, `AE_LLM_MODEL` 기본 `gpt-5-mini`).
- max_tokens는 2000이면 충분 (`EffortEstimator(llm, max_tokens=...)`로 조정).

## 3. 입력

`spec_text: str` — 자유 텍스트 작업 지침서. 권장 포함 요소(누락 시 정확도 하락, 실패 아님):

```
업무 제목 / 할 일 / 업무 상세 / 완료조건 / 소속 역할 / 연결된 스킬
+ 수량 단서(단어수·문서수·항목수·검증건수)  ← count 근거가 되므로 가장 중요
```

## 4. 출력 스키마

```jsonc
{
  "human_only": { "minutes": 187.5, "hours": 3.12, "breakdown": [/* §4.1 */] },
  "agent": {
    "minutes": 79.2, "hours": 1.32,        // 헤드라인 = machine + hitl 합산
    "machine": {                           // 기계 활성시간 (ai_io 포함, RF 곱 적용)
      "minutes": 29.2, "hours": 0.49,
      "breakdown": [/* §4.1 */],
      "ai_io": { "input_words": 8500, "output_words": 2400, "minutes": 3.6 },
      "revision_factor": 1.0
    },
    "hitl": {                              // 에이전트 운용에 필요한 사람 시간
      "minutes": 50.0, "hours": 0.83, "breakdown": [/* §4.1 */]
    }
  },
  "metrics": {
    "human_labor_leverage": 3.75,   // human_only/hitl. hitl=0이면 null
    "automation_share": 0.733       // 1 - hitl/human_only. human=0이면 null
  },
  "rationale": "LLM의 수량 산정 근거 문장",
  "confidence": "C (cold-start seed rates, 미보정)",
  "confidence_notes": ["폐기·경고 목록. 비어있지 않으면 저신뢰 처리 권장"]
}
```

§4.1 breakdown 항목: `{"primitive": str, "count": float, "unit": str, "minutes": float}`

주의: `agent.minutes`는 machine+hitl 단순 합산 헤드라인. 효율 지표 계산·저장 시에는
내부 `machine.minutes`/`hitl.minutes` 세부값을 함께 보존할 것 — 사람 시간(hitl)과
기계 시간은 다른 자원이며, leverage는 hitl 기준으로만 계산된다.

## 5. 오류 모드

| 상황 | 동작 |
|---|---|
| LLM 출력 스키마 불량 | 오류 내용 첨부해 자동 1회 재호출 |
| 재호출도 불량 | `ValueError` raise — 호출측에서 catch |
| 미등록 primitive·음수 count | 해당 항목만 폐기, `confidence_notes`에 기록 (raise 안 함) |
| hitl 빈 배열 | hitl=0으로 계산 + notes 경고, leverage=null |
| LLM 통신 실패 | llm 객체의 예외 그대로 전파 (시뮬은 `RuntimeError`) |

## 6. 통합 체크리스트

1. `estimator.py`+`rates.json` 복사 또는 서브모듈 참조.
2. 호스트 LLM을 §2 계약으로 래핑해 주입.
3. `python test_estimator.py` (mock, 네트워크 불필요) 통과 확인.
4. 출력 저장 시 `confidence`·`confidence_notes` 동반 저장 (숫자만 떼어 쓰지 말 것).
5. 운영 후 `rates.json` min_per_unit을 실측 trajectory로 보정 — 보정 전 절대값은 비교 용도로만.

## 7. 구 시스템 교체 (CounterfactualEstimator drop-in)

기존 `mm_app` `counterfactual.py`의 `CounterfactualEstimator`를 대체하려면
**`compat.py`를 쓴다** — 구 시그니처·구 반환 스키마 그대로:

```python
from compat import CounterfactualEstimator

ce = CounterfactualEstimator()            # llm 미지정: onprem_llm 자동 import, 없으면 시뮬
ce = CounterfactualEstimator(llm=OnpremLLM())   # 명시 주입 (권장)
r = ce.estimate_task(title, context, role, skill_names, detail)
```

반환(구 스키마 유지 + 부가 키 2개):

```jsonc
{
  "error": null,                    // 실패 시 문자열, raise 안 함 (구 계약 유지)
  "human_min": 12.5,
  "agent_min": 4.2,                 // = agent_human_min + agent_ai_min
  "agent_human_min": 3.8,           // 신규 hitl (감독 + 잔여 직접작업)
  "agent_ai_min": 0.4,              // 신규 machine (ai_io 포함)
  "saved_min": 8.3,                 // human_min - agent_min (완료시간 절감 기준)
  "speedup": 2.98,                  // human_min / agent_min
  "human_breakdown": {"search": 6.0, "read": 6.5},          // primitive→분 flat map
  "agent_breakdown": {"draft": 2.0, "verify": 1.8,          // machine·hitl 동명 primitive는 합산
                      "ai_io": {"input_words": 120, "output_words": 400, "minutes": 0.6}},
  "rationale": "...",
  "confidence": "...", "confidence_notes": [...]            // 부가 키 — 무시 가능, 저장 권장
}
```

구 대비 의미 변화 (교체 시 인지할 것):

| 항목 | 구 | 신규(compat) |
|---|---|---|
| `agent_human_min` | agent 리스트 내 사람 잔여개입 | hitl 카드 = 감독(instruct/review/approve/correct/verify) **+ 잔여 직접작업(draft/edit/data_entry/execute/decide)** — 감독 오버헤드가 추가 계상되므로 구보다 커질 수 있음(더 정확) |
| `speedup` | human/agent_min | 동일 정의 유지. 신규 지표 `human_labor_leverage`(human÷hitl)와 **다른 지표** — 혼동 금지 |
| 요율 | 코드 내 `PRIMITIVES` dict | `rates.json`. 구 dict에 실측 튜닝값이 있으면 rates.json의 seed를 **구 값으로 덮어쓸 것** |
| 실패 | error 필드 | 동일 (compat이 예외를 error 문자열로 변환) |

교체 시 확인 항목 (이쪽에서 확인 불가했던 가정):
1. 구 `CounterfactualEstimator.__init__` 시그니처 — compat은 `(llm=None, rates_path=..., max_tokens=2000)`. 다르면 생성부만 수정.
2. `agent_breakdown["ai_io"]` 내부 필드를 소비하는 코드가 있으면 `{input_words, output_words, minutes}` 형식과 대조.
3. 구 소비측이 `human_breakdown`에 없는 키를 기대하는지 (신규 primitive 어휘: search/read/classify/decide/draft/edit/data_entry/execute/verify/communicate).

## 8. 금지 사항

- 프롬프트(`build_prompt`)에 `rates.json` 요율값 노출 금지 — count 역산 오염.
  (`test_rates_not_in_prompt`가 회귀 감시.)
- LLM에게 시간(분·시)을 직접 출력시키는 프롬프트 개조 금지 — 수량만.
