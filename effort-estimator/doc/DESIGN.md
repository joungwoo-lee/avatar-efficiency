# effort-estimator 설계 근거 (기능·기술 배경·정당화)

대상 독자: 이 모듈의 산정 방식이 신뢰할 만한지 판단해야 하는 사람(도입 결정자, 감사자, 후임 개발자).
방법론 전체는 [requirement_based_human_effort_service_design.md](requirement_based_human_effort_service_design.md) (v0.6, 이하 "방법론 문서"),
사용법은 [README.md](../README.md), 통합 절차는 [INTEGRATION.md](INTEGRATION.md),
구 API 계약은 [integ-spec.md](integ-spec.md).

> 구 primitive×요율 방식(TAEE Phase 1 MVP)의 설계 근거 문서는 본 문서로 대체되었다.
> 구 방식은 agent 경로 산정(agent_path.py)에만 남아 있다.

---

## 1. 기능 — 이 모듈은 무엇을 하는가

**입력**: `할일 + 역할 + 업무 상세 + 사용할 스킬`이 담긴 작업 지침서 텍스트 (업무 실행 **전**).

**출력**: 숙련 실무자가 **생성형 AI 없이**(그 외 일반 업무 도구는 전부 사용) 같은 완료조건을
달성할 때 필요한 Human-Equivalent Effort — 최종 총공수분포에서 한 번 산출한 **P50/P80 (분)**.

부가로 구 Counterfactual API(integ-spec.md) 호환을 위해 agent 경로(machine+hitl) 분도
산정한다(§5 하이브리드).

## 2. 핵심 설계 결정과 근거

### 2.1 LLM에게 시간을 추정시키지 않는다

LLM의 자유서술 시간 추정은 보정 불가·재현 불가·감사 불가다. 대신:

```
LLM      = 요구사항 추출 → 인간 WBS 분해 → Work Unit 매핑·수량화 (시간 필드 금지)
Catalog  = catalog.json — Work Unit별 인간 시간분포 (프롬프트 미노출)
Code     = engine.py — 수량분포 × 시간분포 Monte Carlo(고정 seed) → P50/P80 1회 산출
```

- LLM 출력에 `minutes/hours/p50/...` 필드가 있으면 검증기가 재귀 제거한다.
- 시간분포·요율은 프롬프트에 절대 노출하지 않는다 — 노출 시 LLM이 목표 시간에서
  수량을 역산하는 오염이 생긴다(회귀 테스트가 감시).
- percentile은 최종 총공수분포에서 한 번만 계산한다. 단위별 P50을 합산하면
  분산이 왜곡된다(방법론 문서 §4.6).

### 2.2 재현성

고정 seed Monte Carlo(기본 5000회, seed 42) + temperature 0 + 버전 기록
(methodology/catalog/prompt version, estimate_id는 입력+카탈로그 해시). 같은
EffortEngineInput은 항상 같은 P50/P80을 낸다(`estimate_from_effort_input` 재계산 경로).

### 2.3 기준 노동 정의의 코드화 (인플레이션 사건과 통제)

**사건**: 초기 구현에서 소형 업무(800단어 보고서 검토 + 200단어 회신)가 338.8분으로
산정되는 수십배 상방 편향이 실측됐다. 원인 분석 결과 "human without AI" 취지가
방법론 문서 §3에만 있고 프롬프트·카탈로그·검증기에 전달되지 않았다.

**원인 4개와 통제** (전부 구현·회귀 테스트 존재):

| # | 원인 | 통제 | 위치 |
|---|---|---|---|
| 1 | 요구사항 발명 — "검토"라는 중간 활동을 "핵심 요약 작성"이라는 없는 산출물 Requirement로 승격 → 거기에 section_draft 등 부착 (최대 기여 요인) | 명시된 최종 산출물만 Requirement, 중간 활동은 과정, Requirement 수 ≤ 명시 산출물 수 | Prompt A/C |
| 2 | 과잉분해 — 교과서식 풀프로세스(범위정의→아웃라인→초안→QA→수정) 강제 재현 | 기준노동 정의(생성형 AI만 배제·도구 전부 사용·최단경로) + 분해 상한(소형 업무 ≤5 items) + QA는 수용기준 명시 시만 + few-shot | Prompt B/C |
| 3 | 수량 단위 불일치 — message 단위(건당 ~15분)에 단어수 200을 수량으로 → 3014분 | `quantity.unit` ≠ 카탈로그 `unit` → 미산정 처리 (코드 강제) | estimator.py 검증기 |
| 4 | 중복 계상 — 같은 회신에 short_message + section_draft + edit_proofread 동시 부착 | 카탈로그 `conflicts_with` 배타성 선언 → 동일 요구사항 내 충돌 단위 코드가 제거 | catalog.json + estimator.py |
| 5 | 운영/구축 오해석 — "X 자동화" 제목의 반복 운영 업무를 "그 시스템을 구축하는 SW 프로젝트"로 추출해 SDLC(기능구현·비기능·테스트·리뷰·배포) 전체 계상 | 운영/구축 구분 규칙 + RCA few-shot + SW 엔진 라우팅↔요구사항 deliverable_type 교차검증(two-pass 코드 강제, 불일치 시 미산정) | Prompt A/B/C + estimator.py |

**결과**: 메일 회신 338.8분 → 16.1분(3연속 재현), 경쟁사 보고서 34h → 7.7h,
RCA 운영 업무 SW 단위 0개(3연속 — 종전 sw.* 합계 ~654분 오계상 제거).

### 2.5 구조적 안전망 — Pass D Consistency Critic (사례별 규칙의 한계 극복)

위 통제 1~5는 각각 특정 실패 사례에서 도출된 규칙이라, **세 번째 유형의 오분류**는
막지 못한다. 근본 취약점은 구조 자체다: 유형 분류가 한 번 틀리면 적용 카탈로그의
시간 스케일(분 단위 ↔ 수백 분 단위)이 통째로 바뀌어 오차가 수십 배로 증폭되는데,
분류가 틀렸을 때의 일반 안전장치가 없었다.

이를 위해 방법론 문서 §7.1의 Pass D(Consistency Critic)를 구현하고 two-pass에
기본 적용한다:

- 독립 LLM 호출이 A/B의 출력을 **지침서 원문에 대조**해 재검토: 요구사항 발명,
  엔진 라우팅 오류, 스케일 불일치, 중복 계상, 수량 근거 부재 — 특정 키워드가 아닌
  일반 판정.
- 권한 제한으로 안전 방향 보장: keep/drop/flag만 가능, 작업 추가·시간 추정 불가 —
  **Critic은 결과를 깎거나 지적만 할 수 있고 부풀릴 수 없다.**
- drop → 미산정 처리, flag → `review_reasons` 기록. Critic 실패 시 산정은 진행하되
  `review_required=true`.
- 검토 게이트(방법론 문서 §8): Critic 지적, 미산정 존재, 매핑 신뢰도 <0.6, 전문
  판단 업무 포함 시 `review_required=true` — 저신뢰 결과가 확정값처럼 흘러가는 것을
  구조적으로 차단.

라이브 검증: 메일·RCA·ETL(키워드 규칙에 없는 신규 유형) 3케이스에서 SW 오분류 0,
Critic이 수량 불일치("로그 6건 ≠ 명시 5건")·중복 의심을 일반 규칙 없이 적발.

교훈: 소형 백엔드 LLM은 프롬프트 규칙을 자주 위반한다. 산정 무결성에 직결되는 규칙
(단위 일치, 배타성)은 **프롬프트 순응에 의존하지 말고 결정론적 검증기가 강제**해야 한다.

### 2.4 경량 Work Unit 계층

카탈로그가 정식 산출물급 단위(최소 10분+)만 가지면 LLM이 소형 업무를 중량 단위에
강제 매핑해 바닥값 인플레이션이 생긴다. 1~10분급 경량 단위 6종
(document_skim, quick_lookup, short_message, quick_edit, quick_calculation,
simple_operation)을 두고, 프롬프트가 경량 우선을 지시하며, 정의문에 경량↔중량 경계를
명시한다.

## 3. 실행 모드

- **two_pass (기본)**: Prompt A(요구사항 추출) → Prompt B(분해·매핑). 단계별 감사·재처리
  가능. 각 호출 검증 실패 시 1회 자동 재시도.
- **single**: Prompt C 단일호출. 저지연·대량 배치용. 두 모드는 산정 편향이 다르므로
  혼용하지 않고 하나로 고정할 것.

## 4. 불확실성 표현

- LLM은 수량의 불확실성만 표현한다: `point` / `triangular` / `discrete`.
- Catalog는 시간의 불확실성을 보유한다: `triangular`(expert seed) / `lognormal` /
  `uniform` / `point`, 조건(parameter)별 추가 시간분포, quality tier 스케일.
- 엔진이 두 분포를 곱·합성해 전체 분포를 만들고 P50(중앙)·P80(계획·예산용)을 산출한다.
- 미매핑·검증 탈락 항목은 시간을 추측하지 않고 `unscored_items`로 분리, 과소추정
  경고를 부착한다.

## 5. 하이브리드 compat (구 API 유지)

integ-spec.md §6.4가 `agent_min` 계열 수치를 요구한다(None이면 소비측 TypeError).
agent 경로는 v0.6 방법론 범위 밖이므로 구 primitive×rates 방식(agent_path.py +
rates.json)을 유지해 채운다:

- `human_min` = v0.6 Work Unit 엔진 P50 (방법론 상향)
- `agent_ai_min` / `agent_human_min` = 구 방식 (machine + hitl)
- `speedup` = human_min / agent_min — human 쪽만 방법론이 바뀌어 구 대비 값이
  커지는 경향. 시계열 비교 시 단절점 표기 필요.

## 6. 신뢰수준과 보정 경로

- 현재 `catalog.json`은 expert seed(`source_type=expert`, `sample_count=0`,
  confidence C). 절대값은 실측 보정 전까지 업무 간 상대 비교 용도.
- 보정: 실측 인간 작업시간 축적 → Work Unit별 `time_model` 갱신 →
  `source_type=internal_measured`, `sample_count` 갱신 (방법론 문서 §13).
  충분한 표본 없이 개별 사례로 변경 금지.
- 큰 업무에서 run 간 분해 편차 존재(소형 백엔드 모델 한계) — 정식 산정은 two_pass +
  사람 검토, Golden Dataset 회귀평가로 관리.

## 7. 검증 체계

- 오프라인 27종 (mock): 엔진 결정성, P80≥P50, tier·parameter 효과, 단위 불일치 차단,
  conflicts 중복 제거, 금지필드 제거, 재시도, 요율 미노출, compat 키·수치검산.
- `--live`: 프록시 실호출 + 소형 업무 인플레이션 회귀(메일 스펙 P50 5~90분, ≤5 items).
