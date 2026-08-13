# 결과물 기반 Human Equivalent Effort 측정 방법론

## 1. 개요

AI의 효율을 현실적으로 측정하려면 AI가 만들어낸 산출량 자체를 사람의 작업시간으로 환산해서는 안 된다. AI는 산출물을 빠르게 많이 만들 수 있기 때문에, 실제로 필요하지 않은 목업·중간 산출물·시행착오까지 사람의 작업량으로 환산하면 AI 효율이 과대평가될 수 있다.

본 문서는 이를 보정하기 위한 **결과물 기반 Human Equivalent Effort 측정 방법론**을 제안한다. 여기서는 이 방법론을 편의상 **OBHE(Outcome-Based Human Effort)**라고 부른다.

OBHE의 핵심 정의는 다음과 같다.

> **주어진 최종 결과물과 동일한 요구사항·기능·품질 상태를, 해당 업무에 숙련된 사람이 AI 없이 정상적인 작업방식으로 달성하는 데 필요한 person-hours**

핵심 흐름은 다음과 같다.

**최종 결과물 → 실제 달성된 Outcome 추출 → 불필요한 AI 산출물 제거 → 기준 인간 작업경로 복원 → 행동별 작업량 산출 → 행동별 Human Time Rate 적용 → Reference Human Effort 산출**

기준 인간 작업시간은 다음 원리로 계산한다.

**기준 인간 작업시간 = 모든 필수 인간 행동의 (행동량 × 표준 단위시간)의 합 + 정상적인 인간 재작업 및 검증 비용**

---

## 2. 연구 기반

OBHE는 단일 기존 연구를 그대로 적용한 것이 아니라, 여러 연구에서 검증된 아이디어를 조합해 구성한 방법론이다.

| 연구 | 핵심 아이디어 | OBHE에서 사용하는 부분 | 변경·확장한 부분 |
|---|---|---|---|
| Epoch AI, Codex Engineer Effort (2026) | 최종 merged PR을 보고 숙련 개발자가 AI 없이 동일한 net change를 만드는 시간을 추정 | 최종 결과물에서 counterfactual human work path 복원 | 정확한 산출물 복제 대신 동일 요구·품질 상태 달성으로 변경 |
| METR Transcript Analysis (2026) | 성공한 net output만 인간시간으로 환산하고 실패·AI setup·AI 자체 오류·과도한 planning은 제거 | AI 고유 작업경로를 인간 작업량에서 제거 | transcript가 없어도 artifact에서 이를 역산하도록 확장 |
| METR Task Substitution & Uplift (2026) | AI가 싸게 만든 Cadillac task 때문에 시간절감이 가치증가보다 크게 측정될 수 있음 | 불필요·optional 산출물을 Human Effort에서 분리 | 필요 산출물과 잉여 산출물을 별도 계측 |
| Standard Coder, Wright & Ziegler (2019) | 실제 개발자들의 변경물과 실제 노동시간으로 ‘표준 개발자’를 학습 | Reference Human과 행동 시간요율을 실제 데이터에서 구축 | 코드 변경뿐 아니라 모든 지식노동 행동으로 확대 |
| COSMIC | 기능 크기와 실제 work-hour 관계를 조직 데이터로 calibration | 조직별 local calibration 및 동일 activity scope 원칙 | 하나의 size 변수 대신 행동들의 조합으로 세분화 |
| CodeBERT Effort Estimation | 완성 코드 자체에 인간 effort를 예측할 수 있는 정보가 존재 | artifact 자체에서 effort driver 추출 가능성의 근거 | black-box 직접 시간예측은 보조모델로만 사용 |
| Anthropic Productivity Estimation | LLM human-time 추정은 상대적 난이도에는 신호가 있지만 systematic bias가 존재 | LLM을 작업경로·난이도 추론기로 사용 | 최종 시간 결정권을 LLM에서 제거 |
| TDABC, Kaplan & Anderson | 활동별 unit time과 transaction 수로 총 시간을 계산하고 complexity를 time equation으로 표현 | Human Action Rate Card의 직접적인 계산 구조 | 원가회계 대신 인간 작업량 산정에 적용 |
| HIE 연구 (2026) | 생성보다 validation·manual correction 등 인간 oversight가 주요 effort driver | 검증을 독립 행동으로 강제 계측 | AI 측 HIL과 인간 counterfactual 검증을 분리 |

---

## 3. 1단계: 결과물을 그대로 세지 않고 Net Accepted Outcome을 만든다

이 단계는 **Epoch AI와 METR**의 아이디어를 기반으로 한다.

Epoch는 PR 전체 개발과정을 그대로 재현하지 않고, 최종 merge된 **net change**를 기준으로 숙련 개발자가 수행했을 일을 추정한다. 또한 단순 LOC가 아니라 실제 변경의 의미와 난이도를 본다.

METR은 더 적극적으로 성공한 결과만 계산하고, 실패·버려진 시도·agent setup·AI가 만든 오류 수정·AI 때문에 길어진 planning 등을 human-equivalent time에서 제거한다.

따라서 OBHE의 첫 번째 산출물은 최종 파일 자체가 아니라 **Net Accepted Outcome**이다.

예를 들어 AI가 다음을 만들었다고 가정한다.

- 최종 보고서 1개
- 중간 보고서 6개
- 조사자료 80개
- prototype 4개

실제로 최종 보고서 하나만 채택되었다면, 인간 작업량을 계산할 때 중간 보고서 6개와 prototype 4개를 모두 사람이 만들었다고 가정하면 안 된다.

**최종 결과를 달성하는 데 실제로 필요했던 일만 남긴다.**

이 단계가 첫 번째 과장 제거 장치다.

---

## 4. 2단계: Exact Replication과 Necessary Outcome을 구분한다

이 단계는 **Epoch AI와 METR Task Substitution 연구**를 결합한다.

Epoch도 자신들의 방식이 productivity gain의 상한이 될 수 있다고 지적한다. AI가 없었다면 사람이 최종 AI 산출물을 그대로 만들지 않고, 덜 만들거나 다른 방식으로 만들 가능성이 있기 때문이다.

METR은 이를 더 일반화하여, AI로 어떤 작업이 매우 싸지면 원래 하지 않았을 작업까지 하게 되고, 이 새로운 task mix 전체를 인간시간으로 환산할 경우 실제 가치 증가보다 효율이 과대평가될 수 있다고 설명한다.

따라서 OBHE에서는 두 수치를 분리한다.

| 지표 | 의미 |
|---|---|
| Human Replication Effort | 사람이 최종 AI 산출물을 거의 그대로 복제하는 데 필요한 시간 |
| Reference Human Effort | 동일한 요구사항·기능·품질을 사람이 정상적으로 달성하는 데 필요한 시간 |

AI 효율 계산에는 **Reference Human Effort**를 사용한다.

예를 들어 AI가 100페이지 분석자료를 생성했지만 실제 의사결정에 필요한 내용은 20페이지 수준이라면, 100페이지 전체를 사람이 작성하는 시간을 분모에 넣으면 안 된다.

이 차이를 별도 지표로 계산할 수도 있다.

**Output Inflation = Human Replication Effort / Reference Human Effort**

Output Inflation이 클수록 AI가 실제 필요 이상의 산출물을 만들어 효율이 부풀려지고 있음을 의미한다.

---

## 5. 3단계: 결과물을 Outcome Unit으로 분해한다

이 단계는 **COSMIC과 CodeBERT 계열의 effort estimation 아이디어**를 일반화한다.

COSMIC은 소스코드 줄 수가 아니라 **사용자가 받는 기능량**을 측정한다. 이후 기능 크기와 실제 work-hour 데이터를 조직별로 축적해 effort를 추정한다.

CodeBERT 기반 연구는 완성된 코드 자체에 인간 effort를 예측할 수 있는 정보가 포함되어 있다는 가능성을 보여준다.

이를 일반 지식노동으로 확장하면 결과물을 단순 파일 수, 페이지 수, LOC가 아니라 **기능적 완료 단위(Outcome Unit)**로 분해해야 한다.

### 보고서 예시

| Outcome Unit | 수량 예시 |
|---|---:|
| 검증된 사실 | 34개 |
| 비교 대상 | 8개 |
| 분석 결론 | 6개 |
| 계산·모델 | 3개 |
| 차트 | 7개 |
| 의사결정 제안 | 4개 |

### 반도체 검증 예시

| Outcome Unit | 수량 예시 |
|---|---:|
| 검증된 requirement | 42개 |
| testcase | 120개 |
| corner case | 18개 |
| 발견·분석된 defect | 7개 |
| regression set | 1개 |
| sign-off evidence | 42개 |

즉 결과물의 물리적 크기보다 **그 안에서 완료된 기능적 결과의 양**이 작업량 계산의 출발점이 된다.

---

## 6. 4단계: Outcome에서 Reference Human Path를 복원한다

이 단계는 **Epoch AI의 counterfactual human reasoning**을 발전시킨 부분이다.

Epoch는 최종 결과물을 보고 숙련 개발자가 해당 변경을 수행하려면 무엇을 읽고, 설계하고, 작성하고, 시험해야 하는지를 추론한다.

OBHE에서는 이 중간 reasoning 자체를 정식 계측 대상으로 승격한다.

### 범용 Human Action Taxonomy

| 코드 | 인간 행동 | 의미 |
|---|---|---|
| H1 | Context Acquisition | 관련 자료·기존 상태 이해 |
| H2 | Information Acquisition | 검색, 조회, 데이터 수집 |
| H3 | Analysis / Diagnosis | 분석, 비교, 문제 원인 판단 |
| H4 | Design / Decision | 구조 설계, 접근법 결정 |
| H5 | Construction / Transformation | 작성, 구현, 모델링, 편집 |
| H6 | Execution | 계산, simulation, query, 실험 실행 |
| H7 | Verification | 검토, 테스트, fact-check, validation |
| H8 | Integration / Finalization | 병합, 정리, 형식화, 최종화 |
| H9 | Coordination | 필수 승인·협의가 완료조건인 경우 |

예를 들어 시장분석 보고서의 Reference Human Path는 다음처럼 복원될 수 있다.

**관련 기존자료 파악 → 자료 탐색 → 핵심 자료 정독 → 데이터 추출 → 비교분석 → 계산 → 결론 도출 → 보고서 구조 설계 → 작성 → 차트 작성 → 사실검증 → 최종 리뷰**

중요한 점은 이것이 **AI가 실제로 밟은 작업경로가 아니라**, 사람이 정상적으로 밟았을 기준 작업경로라는 것이다.

---

## 7. 5단계: 각 행동의 Workload Driver를 결과물에서 센다

단순히 “분석 2시간”이라고 적으면 근거를 감사할 수 없다.

각 행동에는 결과물에서 추출 가능한 **측정 가능한 작업량 driver**를 붙여야 한다.

| 행동 | 주요 Workload Driver |
|---|---|
| 문서 읽기 | 페이지, 정보밀도, 전문난이도 |
| 자료 검색 | 필요한 유효 source 수, 탐색 난이도 |
| 비교 분석 | 대상 수 × 비교 dimension 수 |
| 데이터 분석 | dataset 수, 변수 수, transformation 깊이 |
| 설계 | component 수, interface 수, constraint 수 |
| 코드 작성 | 기능단위, transformation impact, dependency |
| 테스트 | testcase 수 × 실행·판정 난이도 |
| fact-check | 검증해야 하는 주장 수 × 출처 난이도 |
| 보고서 작성 | 의미 있는 section·argument 수 |
| 최종 검토 | 검토 대상량 × quality·risk level |

이 구조는 HIE 연구에서 제시된 Context Completeness, Transformation Impact, Iteration, Oversight 등 단순 산출량 외 effort driver와도 방향성이 맞는다.

---

## 8. 6단계: Human Action Rate Card를 만든다

이 단계는 **TDABC와 Standard Coder**가 핵심 이론적 근거다.

Kaplan과 Anderson의 Time-Driven Activity-Based Costing은 기본적으로 다음 두 요소로 시간을 계산한다.

1. 활동 1회에 필요한 시간
2. 그 활동의 발생량

또한 단순 평균이 아니라 task 특성에 따라 추가시간이 붙는 **time equation**을 사용한다.

OBHE에서는 이를 사람 작업량 계산으로 확장한다.

### Human Action Rate Card 예시

| Human Action | 기본 단위시간 | 추가 Driver 예시 |
|---|---:|---|
| 일반 source 판별 | source당 1분 | 전문자료 +2분 |
| 논문 핵심 파악 | 논문당 12분 | 수식·방법론 복잡 +8분 |
| 주장 검증 | claim당 3분 | 다중출처 필요 +4분 |
| 비교분석 | cell당 2분 | 정성적 판단 +3분 |
| chart 제작 | chart당 15분 | 데이터 cleaning +20분 |
| testcase 작성 | case당 10분 | 복잡 edge case +15분 |

이 값은 예시이며 실제 운영에서는 **조직의 human-only 업무 데이터로 구축**해야 한다.

Standard Coder 연구의 핵심도 특정 개인이 아니라 **표준적인 개발자(Standard Coder)**의 작업시간을 실제 데이터에서 학습한다는 데 있다.

OBHE에서는 이를 일반화하여 **Standard Human Action Rate**를 정의한다.

즉 개인별 편차 대신:

> 우리 조직의 해당 직무에서 적정 숙련도를 가진 사람이 이 행동 1단위를 수행할 때의 표준시간 분포

를 사용한다.

---

## 9. 시간요율 학습

시간요율은 다음 데이터에서 구축하는 것이 바람직하다.

| 데이터 | 사용 방법 |
|---|---|
| 실제 human-only 업무 로그 | 최우선 ground truth |
| 화면·툴·activity log | 행동시간 자동 추출 |
| 문서 history, VCS, workflow log | 행동 발생과 duration 추론 |
| timesheet + 산출물 | coarse calibration |
| SME 추정 | 데이터가 부족한 초기 단계 |

COSMIC 역시 기능 크기와 실제 work hours를 조직별로 축적하여 local calibration할 것을 권장한다.

따라서 특정 조직의 시간요율을 다른 조직에 그대로 적용하는 것은 적절하지 않다.

---

## 10. 단일 시간요율보다 Time Equation을 사용한다

“논문 한 편 읽기 = 15분”처럼 고정된 단위시간만 사용하면 업무 복잡도를 반영하기 어렵다.

예를 들어 다음처럼 구성한다.

**논문 파악 시간 = 기본 확인시간 + 본문 길이 시간 + 전문성 난이도 추가시간 + 수식·실험방법 분석시간 + 결과 교차검증시간**

SW 개발이라면:

**변경 구현시간 = 기본 변경시간 + 영향받는 component 수 + interface 변경 + 신규 알고리즘 + regression 범위 + 안전·성능 제약**

이처럼 행동시간을 여러 complexity driver의 조합으로 계산하는 것이 TDABC의 time equation과 같은 원리다.

---

## 11. LLM의 역할: 시간을 결정하지 않고 작업경로를 복원한다

Anthropic, METR, Epoch 결과를 보면 LLM의 human-time 추정에는 유용한 신호가 있지만 편향과 모델 간 편차가 존재한다.

따라서 다음 구조는 피해야 한다.

**Artifact → LLM → 17.3시간**

권장 구조는 다음이다.

**Artifact → LLM → Human Action Ledger → Human Rate DB → 12~18시간**

LLM은 다음만 추론한다.

- 무슨 일을 해야 했는가
- 몇 단위인가
- 얼마나 복잡한가
- 왜 그 행동이 필요한가

최종 시간은 조직의 실측 Human Rate DB가 결정한다.

---

## 12. 복원된 행동마다 증거를 남긴다

LLM이 임의로 human path를 상상하지 않도록 각 action row에 근거를 저장해야 한다.

| 필드 | 내용 |
|---|---|
| Outcome | 어떤 최종 결과를 위한 행동인가 |
| Human Action | 사람이 무엇을 해야 하는가 |
| Evidence | 결과물의 어떤 부분에서 추론했는가 |
| Quantity | 몇 단위인가 |
| Complexity Driver | 무엇 때문에 어려운가 |
| Role | 어떤 숙련자의 일인가 |
| Time Rate Source | 어떤 실측 데이터에서 rate를 가져왔는가 |
| P50 time | 일반적인 시간 |
| P80 time | 보수적 시간 |
| Confidence | 근거의 강도 |

따라서 최종적으로 “18시간”이 나오더라도 그 근거를 모든 행동 단위까지 역추적할 수 있다.

---

## 13. Verification은 반드시 독립 행동으로 둔다

HIE 연구에서는 validation과 manual correction이 중요한 effort driver로 나타났다.

따라서 결과물 기반 인간 작업경로를 복원할 때:

**작성 4시간**

으로 끝내면 안 되고,

**작성 4시간 + 검증 2시간**

처럼 검증을 별도 행동으로 계측해야 한다.

다만 다음 둘은 분리해야 한다.

- **AI가 만들었기 때문에 필요한 HIL verification** → AI 실제 비용에 포함
- **사람이 직접 만들어도 정상적으로 필요한 verification** → Reference Human Effort에 포함

두 비용을 섞으면 중복계산이 발생한다.

---

## 14. 정상적인 사람의 시행착오도 반영한다

METR는 AI 때문에 생긴 불필요한 오류 수정은 human counterfactual에서 제거한다.

하지만 그렇다고 사람을 완벽한 one-shot 작업자로 가정해서도 안 된다.

숙련된 사람도 정상적으로 다음과 같은 흐름을 가진다.

**초안 → 확인 → 작은 수정 → 재검증**

따라서 다음 둘을 구분한다.

- **AI-induced rework** → Human Effort에서 제외
- **Normal Human Rework** → 실제 historical human data에서 평균적으로 관찰되는 수준을 포함

이를 **Expected Human Rework**로 계측한다.

---

## 15. 숙련도 차이 보정

Reference Human의 정의가 불명확하면 결과가 크게 흔들릴 수 있다.

권장 기준은 다음과 같다.

> **해당 업무를 독립 수행할 수 있고, 조직의 일반적 업무환경과 필요한 domain context를 이미 가진 직무 P50 숙련자**

충분한 데이터가 있다면 개인별 속도차와 task 난이도를 분리하기 위해 mixed-effects 모델 등을 사용할 수 있다.

예:

- task complexity 효과
- domain 효과
- worker 숙련도 효과

---

## 16. 최종 계산 구조

작업마다 다음과 같은 Human Action Ledger를 만든다.

| Human Action | Workload | Standard Time | 추정 시간 |
|---|---:|---:|---:|
| 자료 탐색 | 15 source | source당 표준시간 | 0.8h |
| 자료 이해 | 8 source | source별 난이도 보정 | 1.7h |
| 데이터 추출 | 35 item | item별 요율 | 1.2h |
| 비교 분석 | 24 cell | cell별 요율 | 1.4h |
| 판단·설계 | 4 decision | 난이도별 요율 | 1.8h |
| 본문 생성 | 6 argument unit | unit별 요율 | 2.3h |
| chart 생성 | 5개 | chart별 요율 | 1.2h |
| 사실 검증 | 31 claim | claim별 요율 | 1.6h |
| 최종 검토 | 1 complete artifact | 크기·위험도 보정 | 0.8h |

여기에 정상적인 Human Rework를 추가하면 **Reference Human Effort**가 된다.

---

## 17. 결과는 단일 숫자가 아니라 범위로 제공한다

Counterfactual human-time 자체에는 불확실성이 존재한다.

따라서 다음처럼 표시하는 것이 적절하다.

- P50: 15시간
- P80: 21시간
- Confidence: B

Confidence는 최소한 다음 세 요소로 결정한다.

1. Outcome 복원 신뢰도
2. Human Path 복원 신뢰도
3. Rate DB 신뢰도

---

## 18. 반드시 별도로 보존해야 할 세 숫자

| 지표 | 의미 |
|---|---|
| HRE | 완성된 AI artifact를 사람이 그대로 재현할 시간 |
| RHE | 동일한 유효 결과를 사람이 정상적으로 만드는 시간 |
| AI Actual Effort | AI 실행 + 실제 HIL + 기타 비용 |

예를 들어:

- HRE = 100시간
- RHE = 40시간
- AI Actual Effort = 20시간

이면 AI가 만들어낸 산출량을 그대로 사람시간으로 환산할 경우 5배 효율처럼 보인다.

하지만 실제 동일 가치 상태를 사람이 달성하는 데 필요한 시간은 40시간이므로 현실화된 효율은:

**40 / 20 = 약 2배**

가 된다.

즉 기존 방식의 5배와 현실화된 2배의 차이가 **AI 산출물 증폭에 의한 과장**이다.

---

## 19. 기존 방법 대비 차이

### Epoch·METR식

**결과물 → LLM → 사람이 걸릴 시간**

### COSMIC식

**기능 크기 → 통계 모델 → 사람이 걸릴 시간**

### CodeBERT식

**Artifact → ML model → effort**

### OBHE

**결과물 → 필요한 Outcome → 기준 인간 행동경로 → 행동량 → 실측 행동시간요율 → 인간 작업시간**

OBHE의 핵심 차별점은 **Human Work Path를 명시적인 계측 객체로 만든 것**이다.

따라서 결과가 틀렸을 때도 다음과 같이 원인을 분석할 수 있다.

- 검색량이 과대추정되었다.
- 검증 요율이 잘못되었다.
- 불필요한 분석 단계가 포함되었다.
- 특정 complexity driver가 과대평가되었다.

즉 단순한 black-box 시간 추정보다 훨씬 감사 가능하고 보정 가능하다.

---

## 20. 실제 시스템 구현 구조

### Layer 1 — Outcome Reconstruction

결과물, before-state, requirement를 읽고 **최종적으로 무엇이 달성되었는가**를 구조화한다.

여기에는 Epoch의 **net output**과 METR의 **net successful output** 개념을 적용한다.

### Layer 2 — Reference Human Path Generator

각 Outcome에 대해 **AI가 없다면 숙련된 사람이 어떤 정상 경로로 만들었을 것인가**를 Human Action Ledger로 생성한다.

Epoch의 counterfactual human reasoning을 사용하되, exact artifact replication이 아니라 **necessary outcome reproduction**으로 수정한다.

### Layer 3 — Empirical Human Rate Engine

각 행동에 대해:

**수량 × Human Time Equation**

을 적용한다.

여기에는 다음 아이디어를 사용한다.

- Standard Coder: empirical standard worker
- COSMIC: organization-specific calibration
- TDABC: unit-time 및 time-equation 구조

---

## 21. 검증 방법

OBHE는 새로운 조합이므로 실제 human-only task로 검증해야 한다.

같은 historical task에 대해 다음 모델을 비교한다.

| 모델 | 예측 방식 |
|---|---|
| Baseline A | LLM 직접 시간추정 |
| Baseline B | Size·complexity regression |
| Baseline C | Artifact ML estimator |
| Proposed | OBHE 행동경로 모델 |

실제 person-hours를 ground truth로 사용하여 다음 지표를 비교한다.

- MAE
- multiplicative error
- P50 / P80 calibration
- task length에 따른 systematic bias
- 조직별 calibration 성능

특히 Anthropic 연구에서 관찰된 **짧은 업무 과대추정 / 긴 업무 과소추정** 문제가 OBHE에서는 줄어드는지 확인해야 한다.

---

## 22. 핵심 정의

OBHE의 핵심을 한 문장으로 정리하면 다음과 같다.

> **AI의 산출량을 사람시간으로 환산하지 말고, 최종 유효 결과를 사람이 달성하기 위해 수행했어야 할 표준 행동들의 양을 복원한 뒤, 실제 인간 행동 데이터에서 얻은 시간요율로 환산한다.**

Epoch와 METR은 **무엇을 counterfactual로 측정해야 하는가**를 제공한다.

Standard Coder와 COSMIC은 **Reference Human을 실제 조직 데이터로 calibration해야 한다**는 원리를 제공한다.

TDABC는 **행동량 × 단위시간이라는 계산 엔진**을 제공한다.

CodeBERT와 Anthropic 연구는 **artifact와 LLM에서 effort 신호를 얻을 수 있지만 직접 시간예측만으로는 한계가 있다**는 근거를 제공한다.

HIE 연구는 **검증·판단 등 사람이 담당하는 행동을 누락해서는 안 된다**는 근거를 제공한다.

이 구조는 SW 개발뿐 아니라 반도체 설계·검증, 리서치, 보고서 작성, 데이터 분석, 기획, 법무 등 다양한 지식노동에 확장할 수 있다.

---

# 참고문헌 및 출처

1. **Epoch AI — Codex engineer effort estimates**  
   https://epoch.ai/data-insights/codex-engineer-effort

2. **METR — Exploratory transcript analysis for estimating time savings from coding agents**  
   https://metr.org/notes/2026-02-17-exploratory-transcript-analysis-for-estimating-time-savings-from-coding-agents/

3. **METR — Task substitution and uplift**  
   https://metr.org/blog/2026-05-08-task-substitution-and-uplift/

4. **Wright & Ziegler — The Standard Coder (2019)**  
   https://arxiv.org/abs/1903.02436

5. **COSMIC — Estimating with Software Size**  
   https://cosmic-sizing.org/cosmic-sizing/estimating-with-software-size/

6. **Tenekeci et al. — Software Effort Estimation with CodeBERT**  
   https://ceur-ws.org/Vol-3852/paper1.pdf

7. **Anthropic — Estimating Productivity Gains**  
   https://www.anthropic.com/research/estimating-productivity-gains

8. **Kaplan & Anderson — Time-Driven Activity-Based Costing**  
   https://www.hbs.edu/ris/Publication%20Files/04-045_d62528d4-7931-4ea1-a205-d9683c639d6e.pdf

9. **HIE Research — Hybrid Intelligence Effort**  
   https://link.springer.com/article/10.1007/s10791-026-10331-6
