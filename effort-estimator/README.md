# effort-estimator — 요구사항 기반 Human-Equivalent Effort 산정기

방법론: [doc/requirement_based_human_effort_service_design.md](doc/requirement_based_human_effort_service_design.md) (v0.5)
— 구 설계(doc/DESIGN.md, doc/INTEGRATION.md, primitive×요율 방식)는 이 문서로 대체됨.

**입력**: `할일+역할+업무상세+스킬` 작업 지침서 자유 텍스트 (**업무 실행 전**)
**출력**: 숙련자가 생성형 AI 없이 동일 결과를 만들 때의 Human-Equivalent Effort
— 최종 총공수분포에서 한 번 산출한 **P50/P80 (분 단위)**

## 3계층 분리 (설계서 §1)

```
[LLM]  요구사항 추출 → 인간 WBS 분해 → 엔진 라우팅 → Work Unit 매핑·수량화
        (시간·배수 출력 금지 — minutes/hours/p50/p80 필드는 검증기가 제거)
[Catalog]  catalog.json — Work Unit별 인간 시간분포 (프롬프트 미노출)
[Code]  engine.py — 수량분포 × 시간분포 Monte Carlo(고정 seed) 합성
        → 전체 분포에서 P50/P80 1회 산출 (단위별 percentile 합산 금지)
```

원 설계서는 사후 트랜스크립트 입력 기준이나, 본 모듈은 **사전 지침서** 입력용 각색판:
`<TRANSCRIPT>` → `<WORK_ORDER>`, 수행상태 없음 → 전 요구사항 `status="planned"`,
요청 범위 전체 산정. 나머지 규칙(Catalog ID 강제, 증거 연결, 시간출력 금지)은 설계서 그대로.

## 구성

```
estimator.py   오케스트레이터: Prompt A→B(기본) 또는 C(단일호출) → 검증(+재시도 1회) → 엔진
prompts.py     Prompt A/B/C (설계서 §23~25 각색, Catalog는 시간정보 제거 뷰만 전달)
engine.py      결정론적 Effort Engine: 분포 표본·검증·Monte Carlo·percentile
catalog.json   Work Unit Catalog (expert seed, confidence C — calibration 대상)
agent_path.py  agent/hitl 경로 산정 (doc/integ-spec.md §3 — primitive count × rates.json)
rates.json     agent 경로 요율표 (integ-spec §3 계약, 프롬프트 미노출)
compat.py      구 시스템(CounterfactualEstimator.estimate_task) drop-in 어댑터
               — human_min은 v0.5 엔진 P50, agent_min 계열은 agent_path 산정 (integ-spec 완전 준수)
onprem_llm_sim.py  OnpremLLM.complete_json(prompt, max_tokens)->dict 시뮬 (cursor-proxy)
test_estimator.py  단위테스트(mock) + --live 프록시 실호출
examples/      샘플 작업 지침서
```

## 사용

```bash
python estimator.py examples/sample_spec.txt            # two-pass(A→B) 리포트
python estimator.py examples/sample_spec.txt --json     # JSON 출력
python estimator.py examples/sample_spec.txt --single   # Prompt C 단일호출(저지연)
python estimator.py spec.txt --seed=7 --trials=10000    # 시뮬 파라미터
python test_estimator.py                                # 오프라인 테스트
python test_estimator.py --live                         # + 프록시 라이브 테스트
```

env: `AE_LLM_BASE`(기본 `http://127.0.0.1:18741/v1`), `AE_LLM_MODEL`(기본 `gpt-5-mini`)

```python
from estimator import HumanEffortEstimator
est = HumanEffortEstimator(llm)          # llm: complete_json(prompt, max_tokens)->dict
result = est.estimate(work_order_text)
result["effort"]["p50_minutes"], result["effort"]["p80_minutes"]

# Review Studio 수정 후 재계산 (LLM 미호출, 재현 가능)
est.estimate_from_effort_input(edited_effort_engine_input)
```

## 실환경(mm_app) 연결

`onprem_llm_sim.OnpremLLM`은 실환경 `mm_app/onprem-llm/onprem_llm.py`의
`OnpremLLM.complete_json(prompt: str, max_tokens: int) -> dict` 계약과 동일.
`HumanEffortEstimator(OnpremLLM())`에 실물 인스턴스를 주입하면 끝.

구 계약 소비자는 `compat.CounterfactualEstimator.estimate_task` 그대로 사용
(doc/integ-spec.md §2/§6 완전 준수 — `analysis_cf.py`/`server.py` 무수정 drop-in).
`human_min`=v0.5 P50, `agent_min`=machine+hitl 수치, `speedup`·`saved_min` 계산됨.
human 쪽 방법론 상향으로 speedup이 구보다 계통적으로 커짐 — 해석 기준 갱신 필요.

## 한계 (Phase A~B 수준)

- `catalog.json` 시간분포는 expert seed(`source_type=expert`, `sample_count=0`) —
  절대값은 confidence C. 실측 calibration(설계서 §13) 전에는 업무 간 상대 비교 용도.
- Work Item 간 상관 미반영(독립 표본) — P80이 다소 좁게 나올 수 있음.
- `UNMAPPED_WORK_UNIT` 항목은 미산정 — 총공수 과소추정 경고로 표기.
- Pass D(Consistency Critic), Review Studio UI, tenant 계층 Catalog는 미구현.
