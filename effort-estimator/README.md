# effort-estimator — 요구사항 기반 Human-Equivalent Effort 산정기

방법론: [doc/requirement_based_human_effort_service_design.md](doc/requirement_based_human_effort_service_design.md) (v0.6)
· 설계 근거: [doc/DESIGN.md](doc/DESIGN.md) · 통합 런북: [doc/INTEGRATION.md](doc/INTEGRATION.md)
· 구 API 계약: [doc/integ-spec.md](doc/integ-spec.md)

**입력**: 아바타 디스크립션 — `할일+역할+업무상세+스킬` 업무 정의 텍스트 (**업무 실행 전**)
**출력**: 숙련자가 생성형 AI 없이 동일 결과를 만들 때의 Human-Equivalent Effort
— 최종 총공수분포에서 한 번 산출한 **P50/P80 (분 단위)**

## 케이스 분리

기본 구조(설계서 원안)는 `클로드코드 트랜스크립트 → [A] 요구사항 추출 → [B] 분해·매핑
→ [코드] 견적`이다. 본 모듈은 **첫 단계만 아바타 특화로 교체**한 케이스:

- 트랜스크립트 케이스(원안 Prompt A, §23): 수행된 일의 **복원** — 철회·대체 정리,
  수행상태(delivered/partial) 판정. **`transcript_requirements.py` 별도 1단계 모듈**로
  제공 — `extract_requirements(llm, transcript)` → `estimate_from_requirements(req)`.
- **아바타 케이스(본 모듈, Prompt A-avatar)**: 업무 정의의 **변환**. 아바타 입력의
  확정 의미(스킬=이미 존재하는 도구, 반복 업무 1회분, 명시 산출물만, 역할=기준 인물)를
  전제로 하므로 "자동화 → 시스템 구축" 같은 복원식 오해석이 끼어들 여지가 없다.
- 이후 단계(Prompt B → Effort Engine)는 두 케이스 공용 —
  `HumanEffortEstimator.estimate_from_requirements(requirements_v1_json)`이 공용 진입점.

```python
# 트랜스크립트 케이스 사용법 (1단계 모듈 → 공용 2단계)
from transcript_requirements import extract_requirements
from estimator import HumanEffortEstimator
req, notes = extract_requirements(llm, transcript_text)      # 1단계: 복원 (§23)
result = HumanEffortEstimator(llm).estimate_from_requirements(req, transcript_text)
# status: delivered=전체, partial=완료범위만, not_delivered=제외 (§24)
```

## 3계층 분리 (설계서 §1)

```
[LLM]  요구사항 추출 → 인간 WBS 분해 → 엔진 라우팅 → Work Unit 매핑·수량화
        (시간·배수 출력 금지 — minutes/hours/p50/p80 필드는 검증기가 제거)
[Catalog]  catalog.json — Work Unit별 인간 시간분포 (프롬프트 미노출)
[Code]  engine.py — 수량분포 × 시간분포 Monte Carlo(고정 seed) 합성
        → 전체 분포에서 P50/P80 1회 산출 (단위별 percentile 합산 금지)
```

기준 노동(설계서 §3) 강제 사항 — "human without **generative** AI":
- 배제는 생성형 AI뿐. 검색엔진·오피스·스프레드시트·템플릿·자동화 스크립트 등
  일반 업무 도구는 전부 정상 사용 + 합리적 최단 경로 (프롬프트·카탈로그 명기)
- 과잉분해 금지: 지침서에 명시된 산출물·완료조건에 필요한 작업만, 소형 업무 ≤5개,
  요구사항 발명 금지 (Prompt A/B/C 규칙)
- 경량 단위 6종(document_skim, short_message 등)으로 소형 업무 바닥값 제거
- 코드 강제: quantity.unit ↔ Work Unit unit 불일치 → 미산정, 카탈로그
  `conflicts_with` 단위 배타성 위반 → 중복 제거 (프롬프트 순응에만 의존하지 않음)

원 설계서는 사후 트랜스크립트 입력 기준이나, 본 모듈은 **사전 지침서** 입력용 각색판:
`<TRANSCRIPT>` → `<WORK_ORDER>`, 수행상태 없음 → 전 요구사항 `status="planned"`,
요청 범위 전체 산정. 나머지 규칙(Catalog ID 강제, 증거 연결, 시간출력 금지)은 설계서 그대로.

## 구성

```
estimator.py   오케스트레이터: Prompt A-avatar→B(기본, 2회) 또는 C(단일호출) → 검증 → 엔진
               critic=True 옵션: Pass D Consistency Critic(설계서 §7.1) 추가 —
               keep/drop/flag만 가능(부풀리기 불가), 기본 OFF
prompts.py     Prompt A-avatar/B/C/D (Catalog는 시간정보 제거 뷰만 전달)
transcript_requirements.py  1단계 모듈(트랜스크립트 케이스, 설계서 §23 Prompt A)
               — extract_requirements() 출력이 estimate_from_requirements()로 연결
engine.py      결정론적 Effort Engine: 분포 표본·검증·Monte Carlo·percentile
catalog.json   Work Unit Catalog (expert seed, confidence C — calibration 대상)
agent_path.py  agent/hitl 경로 산정 (doc/integ-spec.md §3 — primitive count × rates.json)
rates.json     agent 경로 요율표 (integ-spec §3 계약, 프롬프트 미노출)
compat.py      구 시스템(CounterfactualEstimator.estimate_task) drop-in 어댑터
               — human_min은 v0.6 엔진 P50, agent_min 계열은 agent_path 산정 (integ-spec 완전 준수)
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
`human_min`=v0.6 P50, `agent_min`=machine+hitl 수치, `speedup`·`saved_min` 계산됨.
human 쪽만 방법론이 바뀌어 정식 산출물 업무의 speedup이 구보다 커지는 경향 —
대시보드 해석 기준 갱신 필요 (doc/INTEGRATION.md 구 대비 표 참조).

## 한계 (Phase A~B 수준)

- `catalog.json` 시간분포는 expert seed(`source_type=expert`, `sample_count=0`) —
  절대값은 confidence C. 실측 calibration(설계서 §13) 전에는 업무 간 상대 비교 용도.
- Work Item 간 상관 미반영(독립 표본) — P80이 다소 좁게 나올 수 있음.
- `UNMAPPED_WORK_UNIT` 항목은 미산정 — 총공수 과소추정 경고로 표기.
- Pass D(Consistency Critic), Review Studio UI, tenant 계층 Catalog는 미구현.
