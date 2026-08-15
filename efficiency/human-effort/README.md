# human-effort — 요구사항 기반 Human-Equivalent Effort 산정기

방법론: [doc/requirement_based_human_effort_service_design.md](doc/requirement_based_human_effort_service_design.md) (v0.6)
· 설계 근거: [doc/DESIGN.md](doc/DESIGN.md)
· 구 API 어댑터·통합 런북: [../counterfactual-api/](../counterfactual-api/)

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
primitive_effort.py  분자 구버전(Phase1) 방식 — LLM 1회가 human 경로를 primitive
               행동+count로 분해 × rates.json human 카드 요율 단순 곱셈.
               Monte Carlo·Work Unit 없음. v0.6과 같은 분자를 재는 다른 자(교차확인용)
onprem_llm_sim.py  OnpremLLM.complete_json(prompt, max_tokens)->dict 시뮬 (cursor-proxy)
test_estimator.py  단위테스트(mock) + --live 프록시 실호출
examples/      샘플 작업 지침서
```

이 폴더는 **분자(사람 w/o 생성형AI)만** 담당한다. 분모(agent_min)는
[`../agent-effort`](../agent-effort), 구 Counterfactual API drop-in 어댑터는
[`../counterfactual-api`](../counterfactual-api).

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

# 구버전(Phase1) 분자 — 교차확인용 (LLM 1회, primitive×human 요율)
from primitive_effort import estimate_human_min
estimate_human_min(llm, spec_text)["human_min"]
```

### 쉬운 요약 — 두 추정법이 왜 다르고, 뭘 고쳤고, 뭘 못 고쳤나

사람 시간 추정법이 2개다. **요구사항 기반**은 "이 결과물을 사람이 만들려면
무슨 일을 얼마나 해야 하나"로 계산하고, **세션기록 기반**은 세션 기록에서
사람의 행동을 추정해 "행동 몇 번 × 행동당 시간"으로 계산한다. 같은 세션인데
세션기록 기반이 요구사항 기반의 1/3이 나오기도, 3배가 나오기도 했다.

고친 것 2개 (둘 다 세션기록 기반 쪽):
1. 읽고 판단하는 일(채점)이 너무 작게 나왔다 → "읽어야 할 자료가 몇 단어인지"를
   안 알려준 게 원인. 알려주게 고침 → 절반쯤 회복.
2. 같은 파일을 여러 번 고쳐 쓰면 고칠 때마다 분량을 전부 더해서 실제보다
   크게 셌다 → 마지막 완성본 기준으로 세게 고침 + "쓴 분량을 수정 분량으로
   또 세지 마라" 규칙 추가.

고친 것 하나 더 (4번): 세션기록 기반이 판단·검증 건수를 단서 없이 맨땅
추정하던 문제 — 기록에서 [작업 구조 참고](검토 파일 목록, 탐색·실행 수행 여부,
지시 왕복 수)를 추출해 "단계의 종류" 단서로 제공. 횟수는 AI 경로라 베끼기 금지
경고 내장. 추가로 **하이브리드 모드** 신설: 1단계가 추출한 요구사항으로 스코프를
고정하고 기록 신호는 규모 단서로만 쓰는 조합 — estimate_human_min(llm, norm,
requirements=req).

하이브리드 실측 (3세션, 요구사항 기반 대비): 조사형 0.64→0.88배로 수렴(개선),
채점형 0.42배(판단 깊이는 행동 단가로 못 담아 불변), 문서형 2.7배(AI 장황함 —
요구사항에 분량 명세가 없어 규모 신호가 이김, 불변). 운용: 세션기록 기반을 쓸
때는 하이브리드가 기본(손해 유형 없음), 문서·채점형은 요구사항 기반이 기준.

고친 것 하나 더 (3번, 2026-08-16 정정): 조사하는 일이 1/3로 작게 나왔던
원인은 "흔적이 없어서"가 아니었다 — 검색한 것, 읽은 자료 분량, 최종 보고 내용
전부 트랜스크립트에 있는데 **정규화 단계에서 잘라내고 안 보여준 것**이었다.
[조사 자료 규모](검토된 자료 총 단어수, 시행착오 포함 상한으로 명시)와
[대화 보고 규모](파일 없으면 보고가 산출물) 신호를 추가 → 조사 세션 27분→56분
(요구사항 기반 75분 대비 0.37→0.75), 채점 세션 82분→114분(172분 대비 0.66).

못 고친 것 1개 (세션기록 기반의 구조적 한계 — 이 유형은 요구사항 기반만 쓴다):
- 문서 대량 생성: AI는 말이 많다. AI가 1.5만 단어를 썼다고 사람도 그만큼 쓸
  필요는 없는데, 세션기록 기반은 "쓰인 단어수 × 단가"라서 AI의 수다를 사람
  노동으로 계산한다. 얼마나 깎아야 할지 근거가 없어 부합 불가.

결론: 코드·조사·채점은 두 추정법이 0.6~0.75 수준으로 수렴 — 병행 가능.
문서 대량 생성만 요구사항 기반을 쓴다. 완전히 맞추려면 진짜 사람이 그 일을
해본 시간 기록이 필요하다.

### primitive 방식 실측 검증·정합화 (2026-08-16, 실세션 6개)

정합화 1차 결과 (②primitive/①요구사항 비율, 수정 전→후):
- 검토·채점형: 0.32x → 0.48x 개선 — [입력 자료 규모] 신호로 읽기 노동 복원. 잔여 과소.
- 코드 구현·설정형: 0.63~0.70x — 안정적. ②×~1.4 보정 계수로 정렬 가능한 영역.
- 문서 대량 생성형: 2.27x → 2.72x — 순계화로도 미해결. 근본 원인은 "AI 산출
  분량 = 사람 필요 분량" 가정: AI는 사람보다 장황하게 쓰고, ①은 요구 충족
  산출물만 계상. **이 유형은 ②를 ①에 부합시킬 수 없음 — ①이 기준 자.**
- 조사·검증형: 0.37x → **0.75x** (정정: 구조적 한계가 아니라 정규화가 조사
  자료·보고 신호를 누락했던 것 — [조사 자료 규모]·[대화 보고 규모] 추가로 해소)

유형별 신뢰 자 규칙: 코드·설정·조사·검토형은 병행(±40% 내), 문서 대량 생성형은
요구사항 기반 채택.

- 입력에서 **AI 도구 사용 통계는 제외**(경로 anchoring 오염), **산출물 규모 실측**
  (Write/Edit 기록된 작성 단어량)은 포함해야 한다. 규모 신호 없이는 측량 불가 —
  13.8h짜리 구현 세션이 54분으로 붕괴함(합산이 요구사항 기반의 28%).
  규모 신호 포함 시 합산 기준 요구사항 기반과 2% 차로 수렴 (1,411 vs 1,439분).
- **잔여 한계**: 파일 산출물이 없는 조사·검토·판단 업무는 primitive가 구조적으로
  과소(작성량에 노동이 안 잡힘 — 조사 세션 28 vs 75분, 채점 54 vs 172분).
  이런 유형은 요구사항 기반(v0.6)이 맞는 자다.
- **운용 원칙**: 두 자 병행, 괴리가 큰 케이스(3배↑/0.3배↓)는 사람 검토 트리거.

## 실환경(mm_app) 연결

`onprem_llm_sim.OnpremLLM`은 실환경 `mm_app/onprem-llm/onprem_llm.py`의
`OnpremLLM.complete_json(prompt: str, max_tokens: int) -> dict` 계약과 동일.
`HumanEffortEstimator(OnpremLLM())`에 실물 인스턴스를 주입하면 끝.

구 계약(Counterfactual API) 소비자는 `../counterfactual-api/compat.py` 사용 —
integ-spec §2/§6 완전 준수 drop-in. 통합 절차는 `../counterfactual-api/INTEGRATION.md`.

## 한계 (Phase A~B 수준)

- `catalog.json` 시간분포는 expert seed(`source_type=expert`, `sample_count=0`) —
  절대값은 confidence C. 실측 calibration(설계서 §13) 전에는 업무 간 상대 비교 용도.
- Work Item 간 상관 미반영(독립 표본) — P80이 다소 좁게 나올 수 있음.
- `UNMAPPED_WORK_UNIT` 항목은 미산정 — 총공수 과소추정 경고로 표기.
- Review Studio UI, tenant 계층 Catalog는 미구현. Pass D는 critic=True 옵션.
