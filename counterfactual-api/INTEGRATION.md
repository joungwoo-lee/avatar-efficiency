# counterfactual-api 인테그레이션 런북 (통합 수행 AI용)

이 문서는 **기존 시스템(mm_app)에서 구 `CounterfactualEstimator`를 본 모듈로 교체하는
작업을 수행하는 AI/개발자를 위한 실행 절차**다. 이 문서만으로 통합을 완주할 수 있어야 한다.
구 API 계약은 [integ-spec.md](integ-spec.md), 방법론 설계서는
[../human-effort/doc/requirement_based_human_effort_service_design.md](../human-effort/doc/requirement_based_human_effort_service_design.md) (v0.6),
설계 근거는 [../human-effort/doc/DESIGN.md](../human-effort/doc/DESIGN.md), 모듈 개요는 [../human-effort/README.md](../human-effort/README.md).

> **산정 구성 (하이브리드)**: `human_min`은 v0.6 Work Unit 엔진
> (catalog.json × Monte Carlo P50)이, `agent_min` 계열(machine+hitl)은
> integ-spec §3의 primitive×rates.json 방식(agent_effort.py)이 산정한다.
> `estimate_task` 시그니처·출력 키·수치 타입은 integ-spec §2/§6에 100% 맞춰져 있어
> `analysis_cf.py`/`server.py`/`app.js` 무수정 drop-in 교체 가능.
> human 경로에는 기준노동("생성형 AI만 배제, 일반 도구 전부 사용, 최단 경로")
> 강제와 인플레이션 통제(요구사항 발명 금지·분해 상한·단위 일치·`conflicts_with`
> 중복 제거)가 적용된다 — 배경은 DESIGN.md §2.3.

교체 대상: `mm_app` `counterfactual.py`의
`CounterfactualEstimator.estimate_task(title, context, role, skill_names, detail) -> dict`

---

## Step 1. 소스 가져오기

```bash
git clone https://github.com/joungwoo-lee/avatar-efficiency.git   # 또는 기존 클론 git pull
```

세 폴더에서 다음 파일들을 mm_app 안에 **`effort_estimator/`(하이픈 아님, 언더스코어)**
이름의 **한 폴더로 모아** 복사한다 (compat.py는 동일 폴더 import를 우선 시도):

```
human-effort/:       estimator.py engine.py prompts.py catalog.json
                     transcript_requirements.py onprem_llm_sim.py     # 분자 (v0.6)
agent-effort/:       agent_effort.py rates.json                       # 분모 (integ-spec §3)
counterfactual-api/: compat.py                                        # drop-in 어댑터
```

- 폴더명이 `effort_estimator`(언더스코어)여야 Python import가 된다. 하이픈이면 실패.
- `catalog.json`(human 시간분포)과 `rates.json`(agent/hitl 요율) 둘 다 필수.
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

llm 계약 (integ-spec §1, 실물이 이미 만족함): `complete_json(prompt: str, max_tokens: int) -> dict`
(파싱 완료된 dict 반환. JSON 문자열 아님.)

주의: task당 **LLM 3회 호출**(Prompt A-avatar→B two-pass + agent_effort 1회.
검증 실패 시 호출별 1회 재시도, 최악 6회). 첫 단계는 아바타 디스크립션 특화
변환기(A-avatar)다 — 트랜스크립트용 복원 로직이 아니므로 "자동화→시스템 구축"류
오해석이 원천 차단된다. 지연이 문제면 `mode="single"`(총 2회). 선택적으로
`HumanEffortEstimator(critic=True)`로 Pass D(Consistency Critic, 결과를 깎거나
지적만 가능)를 추가할 수 있다 — 기본 OFF.
`max_tokens` 인자는 agent_effort 호출에 적용되고, v0.6 파이프라인은 내부적으로
최소 6000을 보장한다.

## Step 3. 호출부 교체

구 클래스와 이름·시그니처가 같으므로 **import와 생성부만 바꾼다**:

```python
# 구:  from counterfactual import CounterfactualEstimator
# 신:
from effort_estimator import CounterfactualEstimator
ce = CounterfactualEstimator(llm=...)   # 생성자: (llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000)
r = ce.estimate_task(title, context, role, skill_names, detail)   # 호출부 변경 없음
```

`skill_names`는 list 또는 str 모두 허용. `analyze_card`/`average_cards`/`server.py`는
integ-spec §4~5 그대로 무수정.

## Step 4. 검증 (순서대로, 전부 통과해야 완료)

```bash
# 4-1. 오프라인 단위테스트 (네트워크·LLM 불필요, mock)
cd effort_estimator && python test_estimator.py        # "OK" (27 tests) 확인
```

```python
# 4-2. 실물 LLM 스모크 — 작은 업무 1건 (integ-spec §2 키·수치 검증)
r = ce.estimate_task("메일 회신 초안 작성", "부서장 승인 요청", "PM",
                     ["mail-draft", "summarize"], "첨부 보고서(약 800단어) 검토 후 회신(200단어) 작성")
assert r["error"] is None, r["error"]
for k in ("human_min", "agent_min", "agent_human_min", "agent_ai_min",
          "saved_min", "speedup", "human_breakdown", "agent_breakdown",
          "rationale", "confidence", "confidence_notes"):
    assert k in r, f"missing key: {k}"
assert r["agent_min"] > 0 and r["agent_human_min"] > 0   # §6.4 — 수치 필수
assert abs(r["agent_min"] - (r["agent_human_min"] + r["agent_ai_min"])) < 0.01
assert abs(r["saved_min"] - (r["human_min"] - r["agent_min"])) < 0.01
assert "ai_io" in r["agent_breakdown"]
```

```text
# 4-3. 재현성 — 같은 입력 2회 호출 시 human_min 동일해야 함
(human 엔진은 고정 seed Monte Carlo. 차이가 나면 LLM 비결정성 — temperature 0 확인)

# 4-4. 구 구현체 대조 — 구 시스템을 아직 지우기 전이라면
같은 입력 3~5건을 구/신 양쪽에 넣고 비교. agent_min은 동일 방식이라 근접해야 한다.
human_min은 방법론이 바뀌어(primitive→Work Unit WBS 분해) 값이 달라진다 — 소형 업무는
경량 단위·분해 상한 통제로 상식 범위(메일 회신 ~16분), 정식 산출물 업무는 구보다
큰 경향. 절대값 신뢰는 Step 5 보정 후에. 대시보드의 speedup 해석 기준을 함께 갱신할 것.

# 4-5. 인플레이션 회귀 — 소형 업무가 수십배로 나오지 않는지
python test_estimator.py --live  # 메일 스펙 P50 5~90분·≤5 items 자동 검증 포함
```

## Step 5. 보정 (정확도 — 실측 축적 후)

두 카탈로그를 각각 보정한다. 값은 **파일에만** 넣고 프롬프트에 절대 노출하지 않는다
(count/수량 역산 오염 — 회귀 테스트 `test_llm_call_count_and_no_rate_leak`이 감시).

| 대상 | 파일 | 보정 방법 |
|---|---|---|
| human 경로 | `catalog.json` | Work Unit별 `time_model`(triangular min/mode/max, 분/단위)을 실측 인간 작업시간으로 갱신(설계서 §13). `source_type`→`internal_measured`, `sample_count` 갱신 |
| agent 경로 | `rates.json` | 구 `counterfactual.py` `PRIMITIVES`에 튜닝값이 있으면 agent/hitl 카드에 이관. 실측 trajectory 축적 시 갱신 |

충분한 표본 없이 개별 사례로 값을 바꾸지 말 것(설계서 §13.2).

## Step 6. 정리

- 구 클래스는 삭제하지 말고 이름만 바꿔 보존(예: `CounterfactualEstimatorLegacy`) — 롤백용.
- 롤백 = Step 3의 import 한 줄을 되돌리면 끝. 데이터 마이그레이션 없음.

---

## 반환 스키마 (integ-spec §2 완전 준수 + 부가 키)

```jsonc
{
  "error": null,                    // 실패 시 문자열. 예외를 raise하지 않음
  "human_min": 16.1,                // v0.6 엔진 P50 (분) — 숙련자, 생성형 AI만 미사용
  "agent_min": 6.89,                // = agent_human_min + agent_ai_min
  "agent_human_min": 5.2,           // hitl: 감독(지시·검토·승인) + 잔여 직접작업
  "agent_ai_min": 1.69,             // 기계 시간 (ai_io 포함, revision factor 곱)
  "saved_min": 9.21,                // human_min - agent_min
  "speedup": 2.34,                  // human_min / agent_min (agent_min<=0이면 null)
  "human_breakdown": {"research.document_skim": 4.7,            // work_unit_id→평균 분
                      "writing.short_message": 11.7},
  "agent_breakdown": {"draft": 0.4, "instruct": 3.0,            // primitive→분 (기계·사람 합산)
    "ai_io": {"input_words": 900.0, "output_words": 250.0, "minutes": 0.39}},
  "rationale": "한 줄 근거 문자열",
  "confidence": "C (cold-start seed rates/catalog, 미보정)",
  "confidence_notes": [],           // 비어있지 않으면 저신뢰 처리 권장
  // 부가 키 (구 소비측은 무시 가능, 저장 권장)
  "human_p80_min": 20.0,            // P80 (분) — 계획·예산용 보수값
  "estimate_id": "E-xxxxxxxxxx",    // 동일 입력+동일 catalog면 동일 (재현성 추적)
  "catalog_version": "core-0.6.0-seed"
}
```

## 구 대비 의미 변화 (교체 시 인지)

| 항목 | 구 | 신규 |
|---|---|---|
| `human_min` | human primitive count × rates 점추정 | v0.6 Work Unit WBS 분해 × catalog.json 분포 → Monte Carlo **P50** (+`human_p80_min`). 소형 업무는 경량 단위·분해 상한으로 상식 범위, 정식 산출물 업무는 구보다 큰 경향 |
| `agent_*` | primitive×rates | **동일 방식 유지** (agent_effort.py + rates.json) |
| `saved_min`/`speedup` | 동일 방법론 쌍의 차/비 | human 쪽만 방법론 상향 → 계통적으로 커짐. 시계열 비교 시 단절점 표기 필요 |
| `human_breakdown` 키 | primitive 이름 | work_unit_id (예: `research.synthesis`) |
| `confidence` | 문자열 "C (...)" | 동일 형식 유지 |
| LLM 호출 | 1회(+재시도) | 3회: A-avatar+B+agent_effort (single 모드는 2회; critic=True 시 +1) |
| 검토 표시 | 없음 | `confidence_notes`의 `review_required:` 항목 — 있으면 확정값 사용 전 사람 검토 |

## 오류 모드

| 상황 | 동작 |
|---|---|
| LLM 출력 스키마 불량 | 해당 호출 자동 1회 재시도 → 그래도 불량이면 `error` 필드에 기록 (raise 안 함) |
| Catalog에 없는 work_unit_id·수량 불량 (human) | 해당 항목만 미산정 분리, `confidence_notes`에 과소추정 경고 |
| quantity.unit ↔ Work Unit unit 불일치 (human) | 요율 오적용 방지 위해 해당 항목 미산정 분리 + 경고 |
| 동일 요구사항에 배타 단위 중복 계상 (human) | 카탈로그 `conflicts_with` 기준으로 중복 항목 제거 + notes 기록 |
| 미등록 primitive·음수 count (agent) | 해당 항목만 폐기, `confidence_notes`에 기록 |
| hitl 빈 배열 | agent_human_min=0 + notes 경고 (leverage 과대평가 위험) |
| LLM이 시간 필드(minutes/p50 등) 출력 | 검증기가 재귀 제거 후 진행, notes 기록 |
| LLM 통신 실패 | `error` 필드에 예외 문자열, 수치 전부 null |

## 심화 사용 (v0.6 신규 스키마 직접 사용 시)

compat 없이 human-equivalent 전체 구조(요구사항, Work Item 기여도, 증거, P50/P80)가 필요하면:

```python
from effort_estimator import HumanEffortEstimator
est = HumanEffortEstimator(llm)                    # mode="two_pass"|"single", seed, trials 조정 가능
r = est.estimate(spec_text)                        # spec_text: 자유 텍스트 작업 지침서
r["effort"]                                        # {p50_minutes, p80_minutes, mean_minutes, ...}
r["item_contributions"], r["unscored_items"], r["warnings"]

# Review Studio식 수정 후 재계산 (LLM 미호출, 결정론적)
r2 = est.estimate_from_effort_input(edited_effort_engine_input_json)

# 트랜스크립트 케이스 (1단계 별도 모듈 → 공용 2단계)
from effort_estimator import extract_requirements
req, notes = extract_requirements(llm, transcript_text)   # §23 복원: 철회 정리·상태 판정
r3 = est.estimate_from_requirements(req, transcript_text) # 2단계부터 아바타와 동일 경로
```

검증 2회 실패 시 `ValueError` raise (compat과 달리 예외 사용).

## 금지 사항

- 프롬프트에 `catalog.json`의 `time_model`·`rates.json`의 `min_per_unit` 노출 금지 —
  수량/count 역산 오염. (`test_llm_call_count_and_no_rate_leak` 등이 회귀 감시.)
- LLM에게 시간(분·시)·P50/P80을 직접 출력시키는 프롬프트 개조 금지 — 수량·count만.
- Work Unit 단계에서 P50/P80을 먼저 뽑아 합산하는 구조 개조 금지 —
  percentile은 최종 총공수분포에서 한 번만(설계서 §4.6).
- `agent_human_min`/`agent_ai_min` 세부값을 버리고 `agent_min`만 저장하지 말 것 —
  사람 시간과 기계 시간은 다른 자원.
