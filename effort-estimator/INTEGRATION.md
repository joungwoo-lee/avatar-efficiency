# effort-estimator 인테그레이션 스펙 (AI 통합용)

대상: 이 모듈을 호스트 시스템(mm_app 등)에 통합하는 AI/개발자.
설계 배경 불필요 — 이 문서만으로 통합 가능해야 함. 상세는 [README.md](README.md).

## 1. 제공 함수

```python
from estimator import EffortEstimator

est = EffortEstimator(llm)          # llm: 아래 §2 계약 객체
result = est.estimate(spec_text)    # spec_text: str → result: dict (§4)
```

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
    "machine_minutes": 29.2, "machine_hours": 0.49,   // 기계 활성시간 (ai_io 포함, RF 곱 적용)
    "hitl_minutes": 50.0,    "hitl_hours": 0.83,      // 에이전트 운용에 필요한 사람 시간
    "breakdown_machine": [/* §4.1 */], "breakdown_hitl": [/* §4.1 */],
    "ai_io_minutes": 3.6, "revision_factor": 1.0
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

주의: "AI 에이전트 에포트"를 한 값으로 쓰려면 machine_minutes가 아니라
**(machine_minutes, hitl_minutes) 쌍**을 유지할 것. hitl을 버리면 효율 과대평가.

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

## 7. 금지 사항

- 프롬프트(`build_prompt`)에 `rates.json` 요율값 노출 금지 — count 역산 오염.
  (`test_rates_not_in_prompt`가 회귀 감시.)
- LLM에게 시간(분·시)을 직접 출력시키는 프롬프트 개조 금지 — 수량만.
