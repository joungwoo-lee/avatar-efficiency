# effort-estimator 인테그레이션 런북 (통합 수행 AI용)

이 문서는 **기존 시스템(mm_app)에서 구 `CounterfactualEstimator`를 본 모듈로 교체하는
작업을 수행하는 AI/개발자를 위한 실행 절차**다. 이 문서만으로 통합을 완주할 수 있어야 한다.
방법론 설계서는 [requirement_based_human_effort_service_design.md](requirement_based_human_effort_service_design.md) (v0.5),
모듈 개요는 [README.md](../README.md).

> **방법론 변경 고지 (중요)**: 본 모듈은 v0.5 설계서 기준으로 재개발되어
> **Human-Equivalent Effort(P50/P80, 분 단위)만** 산정한다. 구 모듈의
> agent/machine/hitl 경로 산정은 범위 밖(설계서 §2.3 비목표)이 되었고,
> compat의 `agent_min` 계열 반환값은 **`None`** 이다. 소비측이 `agent_min`,
> `saved_min`, `speedup`을 실사용 중이면 **교체 전에 해당 로직을 먼저 분리**할 것.

교체 대상: `mm_app` `counterfactual.py`의
`CounterfactualEstimator.estimate_task(title, context, role, skill_names, detail) -> dict`
— 본 모듈 `compat.py`가 같은 시그니처를 제공한다(반환 의미는 위 고지 참조).

---

## Step 1. 소스 가져오기

```bash
git clone https://github.com/joungwoo-lee/avatar-efficiency.git   # 또는 기존 클론 git pull
```

`effort-estimator/` 폴더에서 다음 7개 파일을 mm_app 안에 **`effort_estimator/`
(하이픈 아님, 언더스코어)** 이름의 폴더로 복사한다:

```
estimator.py  engine.py  prompts.py  catalog.json  compat.py  __init__.py  onprem_llm_sim.py
```

- 폴더명이 `effort_estimator`(언더스코어)여야 Python import가 된다. 하이픈이면 실패.
- `catalog.json`은 필수 — Work Unit Catalog(시간분포)가 여기만 있다. `rates.json`은 폐기됨.
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

주의: 신규는 기본 **two-pass(A→B)라 LLM을 2회 호출**한다(+검증 실패 시 단계별 1회 재시도,
최악 4회). 지연이 문제면 `CounterfactualEstimator(llm=..., mode="single")`로 Prompt C
단일호출 사용 — 단 두 모드는 산정 편향이 다르므로(설계서 §25) 혼용하지 말고 하나로 고정.

## Step 3. 호출부 교체

구 클래스와 이름·시그니처가 같으므로 **import와 생성부만 바꾼다**:

```python
# 구:  from counterfactual import CounterfactualEstimator
# 신:
from effort_estimator import CounterfactualEstimator
ce = CounterfactualEstimator(llm=...)   # 생성자: (llm=None, catalog_path=..., max_tokens=6000, mode="two_pass")
r = ce.estimate_task(title, context, role, skill_names, detail)   # 호출부 변경 없음
```

구 생성자 시그니처가 위와 다르면(예: 인자 없이 내부 생성) 생성부 한 줄만 맞춰 수정.
`skill_names`는 list 또는 str 모두 허용.

**소비측 값 사용 변경**: `human_min`(=P50 분)과 부가 키 `human_p80_min`만 사용.
`agent_min`/`agent_human_min`/`agent_ai_min`/`saved_min`/`speedup`은 항상 `None` —
이 값을 읽어 연산하는 코드는 None-guard 또는 제거.

## Step 4. 검증 (순서대로, 전부 통과해야 완료)

```bash
# 4-1. 오프라인 단위테스트 (네트워크·LLM 불필요, mock)
cd effort_estimator && python test_estimator.py        # "OK" (20 tests) 확인
```

```python
# 4-2. 실물 LLM 스모크 — 작은 업무 1건
r = ce.estimate_task("메일 회신 초안 작성", "부서장 승인 요청", "PM",
                     ["mail-draft", "summarize"], "첨부 보고서(약 800단어) 검토 후 회신(200단어) 작성")
assert r["error"] is None, r["error"]
assert r["human_min"] and r["human_min"] > 0
assert r["human_p80_min"] >= r["human_min"]
assert r["agent_min"] is None                      # 신규 계약 — None이 정상
assert r["human_breakdown"], "work unit breakdown 비어 있음"
```

```text
# 4-3. 재현성 — 같은 입력 2회 호출 시 human_min 동일해야 함
(엔진은 고정 seed Monte Carlo. 차이가 나면 LLM 비결정성 — temperature 0 확인)

# 4-4. 구 구현체 대조 — 구 시스템을 아직 지우기 전이라면
같은 입력 3~5건을 구/신 양쪽에 넣고 human_min 자릿수(order of magnitude)를 비교.
신규 catalog.json은 expert seed(confidence C)라 절대값 차이는 정상 —
계통적으로 5배 이상 차이면 Work Unit 매핑 결과(warnings, unscored)를 먼저 확인.
```

## Step 5. Catalog 보정 (정확도 — 실측 축적 후)

구 `rates.json` 요율 이관은 **하지 않는다** — primitive 체계(행동×count)와 Work Unit
체계(작업단위×시간분포)는 구조가 달라 호환되지 않는다.

대신 `catalog.json`의 Work Unit별 `time_model`(triangular min/mode/max, 분/단위)을
조직 실측 인간 작업시간으로 보정한다(설계서 §13):

- 값을 **catalog.json에만** 넣는다. 프롬프트에는 시간정보가 절대 들어가지 않는다
  (`prompts.catalog_prompt_view`가 time_model을 제거 — 회귀 테스트
  `test_two_pass_calls_and_no_rate_leak`이 감시).
- 보정 시 `source_type`을 `internal_measured`로, `sample_count`를 표본 수로 갱신.
- 충분한 표본 없이 개별 사례로 값을 바꾸지 말 것(설계서 §13.2).

## Step 6. 정리

- 구 클래스는 삭제하지 말고 이름만 바꿔 보존(예: `CounterfactualEstimatorLegacy`) — 롤백용.
- 롤백 = Step 3의 import 한 줄을 되돌리면 끝. 데이터 마이그레이션 없음.

---

## 반환 스키마 (구 키 유지 + 의미 변경 + 부가 키)

```jsonc
{
  "error": null,                    // 실패 시 문자열. 예외를 raise하지 않음 (구 계약 동일)
  "human_min": 2054.8,              // Human-Equivalent Effort P50 (분)
  "agent_min": null,                // ▼ 신규 방법론 범위 밖 — 항상 null
  "agent_human_min": null,
  "agent_ai_min": null,
  "saved_min": null,
  "speedup": null,
  "human_breakdown": {"research.source_deep_review": 377.5, "...": 0},  // work_unit_id→평균 분
  "agent_breakdown": {},            // 항상 빈 객체
  "rationale": "R-001 경쟁사 5곳 ...; R-002 ...",   // 요구사항 제목 목록
  // 부가 키 (구 소비측은 무시 가능, 저장 권장)
  "human_p80_min": 2241.1,          // P80 (분) — 계획·예산용 보수값
  "estimate_id": "E-xxxxxxxxxx",    // 동일 입력+동일 catalog면 동일 (재현성 추적)
  "catalog_version": "core-0.5.0-seed",
  "confidence": 0.79,               // Work Item 매핑 신뢰도 평균 (0~1)
  "warnings": []                    // 미산정(unscored)·저신뢰·전문검토 경고 — 비면 정상
}
```

## 구 대비 의미 변화 (교체 시 인지)

| 항목 | 구 | 신규 |
|---|---|---|
| 산정 대상 | human + agent(machine/hitl) 2경로 | **human-equivalent만** (설계서 §2.3) |
| 산정 방식 | primitive count × rates.json 점요율 | Work Unit 수량분포 × catalog.json 시간분포 → Monte Carlo |
| 출력 | P50 점추정 | 최종 총공수분포에서 P50/P80 1회 산출 |
| `human_min` | primitive 합산 점추정 | 분포 P50. `human_p80_min` 병용 권장 |
| `agent_*`, `saved_min`, `speedup` | 수치 | **null** |
| 요율/기준 | `rates.json` | `catalog.json` (Work Unit Catalog) |
| LLM 호출 | 1회(+재시도 1회) | two-pass 2회 / single 1회 (+단계별 재시도 1회) |

## 오류 모드

| 상황 | 동작 |
|---|---|
| LLM 출력 스키마 불량 | 해당 단계 자동 1회 재호출 → 그래도 불량이면 `error` 필드에 기록 (raise 안 함) |
| Catalog에 없는 work_unit_id·수량 불량 | 해당 항목만 unscored로 분리, `warnings`에 과소추정 경고 |
| LLM이 시간 필드(minutes/p50 등) 출력 | 검증기가 재귀 제거 후 계속 진행, warnings에 기록 |
| PROFESSIONAL_REVIEW 포함 | 결과는 나오되 "전문가 검토 없이 확정값 사용 금지" 경고 부착 |
| LLM 통신 실패 | `error` 필드에 예외 문자열 |

## 심화 사용 (신규 스키마 직접 사용 시)

compat 없이 전체 구조(요구사항, Work Item별 기여도, 증거, 시뮬레이션 파라미터)가 필요하면:

```python
from effort_estimator import HumanEffortEstimator
est = HumanEffortEstimator(llm)                    # mode="two_pass"|"single", seed, trials 조정 가능
r = est.estimate(spec_text)                        # spec_text: 자유 텍스트 작업 지침서
r["effort"]                                        # {p50_minutes, p80_minutes, mean_minutes, p50/p80_person_hours}
r["item_contributions"]                            # Work Item별 평균 기여 분·비중
r["unscored_items"], r["warnings"], r["notes"]     # 미산정·경고

# Review Studio식 수정 후 재계산 (LLM 미호출, 결정론적)
r2 = est.estimate_from_effort_input(edited_effort_engine_input_json)
```

검증 2회 실패 시 `ValueError` raise (compat과 달리 예외 사용).

## 금지 사항

- 프롬프트에 `catalog.json`의 `time_model`·시간값 노출 금지 — 수량 역산 오염.
  (`test_two_pass_calls_and_no_rate_leak`이 회귀 감시.)
- LLM에게 시간(분·시)·P50/P80을 직접 출력시키는 프롬프트 개조 금지 — Work Unit 수량만.
- Work Unit 단계에서 P50/P80을 먼저 뽑아 합산하는 구조 개조 금지 —
  percentile은 최종 총공수분포에서 한 번만(설계서 §4.6).
- `human_p80_min`을 버리고 `human_min`만 저장하지 말 것 — 계획·예산은 P80 기준.
