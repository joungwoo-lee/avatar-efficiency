# 사전 에이전트화 에포트·효율 추정기 설계서
## Task Agentization Effort Estimator (TAEE)

- 문서 버전: 1.0
- 목적: 업무를 실행하기 전에, 동일한 요구사항을 **AI 미사용 인간**과 **지정된 에이전트+스킬**이 각각 수행할 때 필요한 시간을 추정하고 에이전트화 효율을 계산한다.
- 기본 산정 단위: 시간
- 금액 산정: 범위 밖. 필요 시 시간 결과에 별도 임금/요금 모델을 곱한다.
- 주요 참조: Mohammad El-Ramly, *ACEM: A Cost Estimation Model for Agentic Software Engineering*, arXiv:2608.02582, 2026-08-03.
- 구현 원칙: LLM은 업무 구조와 분류를 제안하고, 최종 시간 계산은 버전이 고정된 결정론적/확률적 추정 엔진이 수행한다.

---

# 0. 핵심 결론

구현 가능하다.

입력으로 다음이 주어진다고 가정한다.

1. 할 일과 완료조건
2. 수행 역할
3. 업무 맥락과 제약
4. 사용할 에이전트
5. 사용할 에이전트 스킬과 도구

시스템은 동일한 업무를 두 개의 실행경로로 재구성한다.

- **Human-only Path**: AI를 쓰지 않는 기준 숙련자가 합리적으로 수행하는 작업경로
- **Agentic Path**: 지정된 에이전트와 스킬을 사용하고 필요한 HITL 감독을 포함한 작업경로

두 경로는 반드시 같은 요구 범위, 같은 완료조건, 같은 품질수준을 만족해야 한다.

핵심 출력은 다음과 같다.

- `human_only_effort`: AI 미사용 인간 활성 노동시간
- `agent_machine_effort`: 에이전트/도구의 기계 활성시간
- `agent_elapsed_time`: 에이전트 경로의 예상 완료 경과시간
- `hitl_human_effort`: 에이전트 운용에 실제 필요한 인간 활성 노동시간
- `human_blocking_latency`: 사람의 승인/판단을 기다리느라 생기는 예상 지연시간
- `human_labor_leverage`: 인간 노동이 몇 배 증폭되는지
- `cycle_speedup`: 완료시간이 몇 배 빨라지는지
- `automation_share`: 인간 직접 노동이 얼마나 제거되는지
- `human_bottleneck_index`: 에이전트 운영에서 사람이 병목이 되는 정도
- `confidence`: 추정 신뢰도와 P50/P80 범위

**단일 "AI 시간"으로 모두 합치지 않는다.**

사람 1시간과 기계 1시간은 같은 자원이 아니고, 여러 에이전트가 병렬로 움직이면 기계시간의 합과 실제 경과시간도 다르다. 따라서 최소한 `Human effort`, `Machine effort`, `Elapsed time`을 분리한다.

---

# 1. 문제 정의

## 1.1 입력 질문

다음과 같은 업무 명세가 이미 작성되어 있다고 가정한다.

> "이 일을 이 역할이 수행해야 한다. 이 업무의 입력·산출물·제약·완료조건은 다음과 같다. 에이전트는 X이고 사용할 수 있는 스킬은 A, B, C이다."

이때 시스템이 답해야 할 질문은 다음이다.

### Q1. AI 미사용 인간은 얼마나 일해야 하는가?

기준 숙련자가 현재 주어진 요구사항과 업무자료를 출발점으로 하여, AI를 사용하지 않고 동일한 완료상태에 도달하기 위한 **활성 노동시간**을 추정한다.

### Q2. 지정된 에이전트는 얼마나 실행되어야 하는가?

에이전트가 실제로 수행할 추론, 문서/파일 읽기, 도구 호출, 산출물 생성, 검증, 재시도 등을 계획하고 **Machine effort**와 **critical-path elapsed time**을 추정한다.

### Q3. 사람은 에이전트에 얼마나 붙어 있어야 하는가?

프롬프트/지시 변환, 결과 읽기, 판단, 승인, 수정지시, 수동검증 등 **HITL 인간 활성시간**을 추정한다.

### Q4. 따라서 에이전트화가 얼마나 효율적인가?

같은 결과를 기준으로 인간 단독 경로와 에이전트 경로를 비교한다.

---

# 2. 산정 경계

## 2.1 시작점

기본 시작점은 **입력 업무 명세가 존재하는 시점**이다.

즉, 사용자가 TAEE에 입력하기 위해 이미 작성한 다음 내용의 작성시간은 기본적으로 계산하지 않는다.

- 할 일
- 역할
- 업무 설명
- 사용할 에이전트
- 사용할 스킬

단, 업무 자체에 "요구사항 정의", "기획서 작성", "대상 선정" 등이 포함되어 있다면 해당 작업은 정상적으로 계산한다.

## 2.2 종료점

`acceptance_criteria`가 충족되고 지정된 산출물이 생성·검증된 시점이다.

종료점은 단순히 "파일이 생성됨"이 아니라 다음의 조합이다.

- 요구사항 충족
- 산출물 생성
- 필요한 품질검사 통과
- 필요한 사람 승인 완료

## 2.3 공정성 규칙

Human-only와 Agentic 비교는 반드시 다음을 동일하게 고정한다.

- 업무 범위
- 품질 수준
- 정확성 기준
- 검증 수준
- 산출물 포맷
- 규정/보안 조건

Agentic Path에서 테스트와 검토를 생략해 놓고 Human-only Path에는 모두 포함하는 비교는 금지한다.

---

# 3. 용어

| 용어 | 정의 |
|---|---|
| Work Unit | 독립적으로 목적·입력·산출물·완료조건을 정의할 수 있는 최소 업무 단위 |
| Human Action | 사람이 수행하는 읽기, 탐색, 판단, 작성, 검토, 검증 등의 행동 |
| Agent Action | 한 번의 모델 판단, 스킬 호출, 도구 호출, 파일 처리, 검증 등 에이전트 실행 단위 |
| Skill | 특정 업무 행동을 에이전트가 수행할 수 있게 하는 명시적 능력·워크플로·도구 묶음 |
| HITL | 에이전트 업무 중 필요한 사람의 지시, 검토, 승인, 수정, 검증 |
| Human-only Effort | AI 없이 사람이 수행할 활성 노동시간 |
| Agent Machine Effort | 에이전트와 도구가 실제 작업을 수행하는 기계시간의 합 |
| Agent Elapsed Time | 병렬성을 고려한 에이전트 경로의 완료 경과시간 |
| HITL Human Effort | 에이전트를 운용하기 위해 사람이 실제로 소비하는 활성 노동시간 |
| Human Blocking Latency | 에이전트가 사람의 응답을 기다려 진행하지 못하는 시간 |
| Agentization Efficiency | 같은 완료상태를 기준으로 Human-only와 Agentic 경로를 비교한 효율 지표 |

---

# 4. 입력 계약

권장 입력은 YAML 또는 JSON이다.

```yaml
task:
  id: TASK-001
  title: ""
  objective: ""
  deliverables: []
  acceptance_criteria: []
  exclusions: []

role:
  name: ""
  seniority: ""
  domain_expertise: []
  required_authority: []
  baseline_familiarity: medium

work_context:
  description: ""
  inputs: []
  systems: []
  constraints: []
  dependencies: []
  volume:
    items: null
    files: null
    pages: null
    records: null
  ambiguity: low|medium|high
  novelty: low|medium|high
  risk: low|medium|high|safety_critical
  regulatory_requirements: []
  confidentiality: low|medium|high

agent_plan:
  agent_id: ""
  model_family: ""
  autonomy_target: assisted|supervised|autonomous
  skills: []
  tools: []
  parallel_agents_allowed: 1
  context_strategy: persistent|segmented|reset
  human_review_policy: auto|milestone|work_unit|action

calibration_profile:
  organization_id: ""
  human_rate_card_version: ""
  agent_rate_card_version: ""
  hitl_rate_card_version: ""
```

## 4.1 Skill 스키마

```yaml
skills:
  - skill_id: research-web
    version: "2.1"
    capabilities:
      - web_search
      - source_selection
      - source_reading
      - citation_generation
    supported_artifacts:
      - research_note
      - report
    constraints:
      - requires_network
    expected_reliability:
      simple: 0.97
      medium: 0.90
      complex: 0.76
    expected_action_latency:
      p50_seconds: 30
      p80_seconds: 70
```

`expected_reliability`와 `expected_action_latency`는 가능하면 실제 trajectory에서 보정한다.

---

# 5. 출력 계약

```json
{
  "task_id": "TASK-001",
  "human_only": {
    "effort_p50_hours": 12.4,
    "effort_p80_hours": 17.0
  },
  "agentic": {
    "machine_effort_p50_hours": 2.8,
    "machine_effort_p80_hours": 4.7,
    "elapsed_p50_hours": 2.1,
    "elapsed_p80_hours": 3.8,
    "hitl_effort_p50_hours": 1.5,
    "hitl_effort_p80_hours": 2.4,
    "human_blocking_latency_p50_hours": 0.4
  },
  "efficiency": {
    "human_labor_leverage_p50": 8.27,
    "cycle_speedup_p50": 5.90,
    "automation_share_p50": 0.879,
    "human_bottleneck_index": 0.31
  },
  "confidence": {
    "grade": "B",
    "main_uncertainties": [],
    "calibration_coverage": 0.72
  }
}
```

---

# 6. 전체 처리 아키텍처

```text
Task/Role/Work/Agent/Skills 입력
        |
        v
1. Spec Normalizer
        |
        v
2. Work Decomposer
        |
        +----------------------+
        |                      |
        v                      v
3A. Human Path Builder    3B. Agent Path Builder
        |                      |
        v                      v
4A. Human Action Qty      4B. Skill Coverage / Agent Actions
        |                      |
        |                      v
        |                5. RF / CF / HITL
        |                      |
        +----------+-----------+
                   |
                   v
6. Rate & Distribution Engine
                   |
                   v
7. DAG Scheduler / Monte Carlo
                   |
                   v
8. Efficiency & Bottleneck Metrics
                   |
                   v
9. Explanation / Audit Output
```

---

# 7. 업무 분해

Human-only와 Agentic Path를 별개로 처음부터 생성하지 않는다.

먼저 업무 자체를 **중립적인 Work Unit Graph**로 분해한다.

각 Work Unit은 다음 필드를 가진다.

```json
{
  "work_unit_id": "WU-03",
  "goal": "최종 보고서에 사용할 신뢰 가능한 데이터 확보",
  "inputs": ["시장 목록"],
  "outputs": ["검증된 데이터셋"],
  "acceptance_criteria": ["출처 존재", "중복 제거"],
  "dependencies": ["WU-01"],
  "artifact_type": "dataset",
  "human_complexity": "medium",
  "agent_complexity": "simple",
  "risk": "medium"
}
```

권장 Work Unit 범주:

- requirements
- information_gathering
- analysis
- decision
- design
- artifact_creation
- data_transformation
- communication
- execution
- review
- validation
- integration
- documentation
- handoff
- implementation
- test_generation
- build
- debugging
- deployment

LLM은 Work Unit 구조화를 담당하되 최종 시간을 직접 결정하지 않는다.

---

# 8. 인간 난이도와 에이전트 난이도를 분리한다

같은 일이 사람에게 어렵다고 에이전트에게도 반드시 어려운 것은 아니다.

예:

- 표준 형식 문서 100개 일괄 변환
  - Human complexity: 반복노동이 큼
  - Agent complexity: 낮음

- 짧은 법률 승인 판단
  - Human complexity: 중간
  - Agent execution complexity: 낮을 수 있음
  - Agent oversight/risk complexity: 매우 높음

각 Work Unit에 다음 두 변수를 독립적으로 둔다.

```yaml
human_complexity:
  cognitive: low|medium|high
  volume: numeric
  ambiguity: low|medium|high
  familiarity: low|medium|high

agent_complexity:
  context_load: low|medium|high
  reasoning_depth: low|medium|high
  tool_depth: low|medium|high
  multimodality: low|medium|high
  context_persistence: low|medium|high
```

이 분리는 ACEM의 중요한 문제의식을 차용한다.

---

# 9. Human-only Path 산정

기준 숙련자는 `role`에 정의된 업무를 정상적으로 맡길 수 있는 실무자로 둔다.

행동 분류:

| 코드 | 행동 | 대표 수량 |
|---|---|---|
| H1 | 요구·맥락 읽기 | 단어, 페이지, 요구항목 |
| H2 | 기존 자료 파악 | 파일, 화면, 함수, 레코드 |
| H3 | 검색·탐색 | 질의, 결과묶음, DB조회 |
| H4 | 분류·선별 | 항목 수 |
| H5 | 판단·설계 | 의사결정 수, 인터페이스 수 |
| H6 | 작성·편집 | 의미 단위, 절, 함수, 슬라이드 |
| H7 | 데이터 입력·변환 | 레코드, 행, 파일 |
| H8 | 실행·조작 | 명령, 시스템 조작, 제출 |
| H9 | 출력·산출물 검토 | 페이지, diff, 레코드, 산출물 |
| H10 | 기능·내용 검증 | 시나리오, 샘플, 체크항목 |
| H11 | 오류수정 | 예상 결함 사이클 |
| H12 | 통합·패키징·전달 | 패키지, PR, 보고서, 전달 건 |
| H13 | 커뮤니케이션 | 메시지, 승인요청, 회의 |

예:

```text
H1 요구 읽기       = 2,400 words
H3 웹 검색         = 8 queries
H4 후보 선별       = 35 items
H5 판단            = 5 medium decisions
H6 보고서 작성     = 6 sections
H9 보고서 검토     = 18 pages
H10 사실 검증      = 20 claims
```

시간은 다음처럼 계산한다.

```text
action_time = quantity * calibrated_time_per_unit
```

요율은 단일값이 아니라 P50/P80 분포로 관리한다.

Human-only Path는 **최소 합리적 숙련자 경로**로 정의한다.

---

# 10. Agentic Path 산정

각 Work Unit마다 다음을 결정한다.

1. 어떤 Skill이 해당 Work Unit을 수행할 수 있는가?
2. 에이전트가 완전 수행 가능한가, 일부만 가능한가?
3. 예상 Agent Action 수는 얼마인가?
4. 실패·수정 가능성은 얼마인가?
5. 문맥이 얼마나 누적되는가?
6. 사람 검토가 어디에서 필요한가?
7. 작업이 병렬화 가능한가?

---

# 11. Skill Coverage Model

각 Work Unit이 요구하는 capability 집합과 Skill의 capability 집합을 비교한다.

Coverage 등급:

- `FULL`: 필요한 capability와 도구가 모두 있음
- `PARTIAL`: 일부는 에이전트, 일부는 인간 필요
- `NONE`: 에이전트 경로에서 인간 수행
- `BLOCKED`: 권한·규정·물리적 제약으로 에이전트 사용 불가

스킬이 많다고 항상 빠르지 않다. 다음 오버헤드를 고려한다.

- skill instruction/context load
- 초기 환경 탐색
- 인증·권한
- 스킬 간 handoff
- 중복 context
- 결과 포맷 변환
- 추가 검증부담

부분 자동화는 Work Unit을 다시 분할한다.

```text
WU-5
  -> WU-5A agent-research
  -> WU-5B human-judgement
  -> WU-5C agent-drafting
  -> WU-5D human-approval
```

---

# 12. Agent Action Model

Agent Action 종류:

| 코드 | 행동 |
|---|---|
| A1 | plan |
| A2 | read_context |
| A3 | retrieve/search |
| A4 | reason/decide |
| A5 | invoke_skill |
| A6 | invoke_tool |
| A7 | generate_artifact |
| A8 | inspect_output |
| A9 | validate/test |
| A10 | repair/retry |
| A11 | integrate |
| A12 | summarize/handoff |

실제 운영 trajectory에서 다음 셀별 분포를 보정한다.

```text
(agent_id, model, skill_id, action_type, artifact_type, complexity)
    -> P50/P80 active duration
```

Cold start에서는 `BaseAgentTime(type, complexity, skill, agent)`를 사용한다.

토큰 데이터를 쓸 경우 토큰은 최종 목적값이 아니라 중간 feature다.

---

# 13. ACEM에서 차용할 핵심 기술

ACEM은 agentic development cost를 LLM, HITL, infrastructure로 분해하고 RF, CF, HIS를 도입한다. TAEE는 금액 대신 시간을 예측하도록 이 구조를 변형한다.

## 13.1 Task → Agent Action → Tool Call 계층

ACEM의 계층적 분해를 다음처럼 일반화한다.

```text
Job
  -> Work Unit
      -> Agent Action
          -> Tool Call
```

업무 크기와 실행 메커니즘을 분리할 수 있다는 장점이 있다.

## 13.2 Artifact Type × Complexity 기반 Base Resource

ACEM은 task의 기본 토큰량을 `artifact type × complexity` 셀로 보정한다.

TAEE는 이를 시간으로 변환한다.

```text
BaseAgentTime =
  lookup(agent, skill, artifact_type, agent_complexity)
```

예:

| Agent | Skill | Artifact | Complexity | P50 |
|---|---|---|---|---:|
| agent-A | research | source_set | simple | 4 min |
| agent-A | research | source_set | complex | 18 min |
| agent-A | doc | report_section | medium | 7 min |

## 13.3 Revision Factor (RF)

에이전트 출력이 거절되거나 잘못되어 재시도되는 오버헤드를 별도 계수로 모델링한다.

```text
RF = 1 + rejection_rate * mean_retry_count
```

TAEE에서는:

```text
expected_agent_work =
  base_agent_work * RF
```

동시에 사람의 오류 확인·수정지시는 HITL에 별도 계산한다.

## 13.4 Context Factor (CF)

긴 agent pipeline에서 문맥이 누적될수록 뒤쪽 action이 더 무거워지는 현상을 모델링한다.

Cold-start 단순형:

```text
CF_position = 1 + alpha * task_position_ratio
```

운영형은 다음 feature를 사용한다.

- estimated_context_tokens
- carried_artifact_count
- previous_tool_output_size
- conversation_turn_count
- summarization/reset 여부

실제 context-inclusive duration 또는 token을 이미 관측한 사후분석에는 CF를 다시 적용하지 않는다.

## 13.5 HITL Intensity Score (HIS)

사람 감독 강도를 4단계로 둔다.

| Level | 감독 정책 | 기본 checkpoint |
|---|---|---|
| HIS-1 Minimal | 마일스톤에서만 검토 | feature/job 단위 |
| HIS-2 Standard | Work Unit 완료마다 검토 | work-unit 단위 |
| HIS-3 Elevated | 주요 agent task마다 검토 | task 단위 |
| HIS-4 Continuous | 거의 모든 action 승인 | action 단위 |

결정 변수:

- domain risk
- agent/skill reliability
- task complexity
- regulatory requirement
- irreversibility
- external side effect

## 13.6 Coarse planning input → calibrated execution resource

ACEM의 실용적인 특징은 미래의 모든 agent action을 사용자가 직접 나열할 필요가 없다는 것이다.

TAEE도 사용자가 다음만 적도록 한다.

- 할 일
- 역할
- 업무
- 산출물
- 에이전트
- 스킬

시스템이 Work Unit을 분해하고 과거 calibration에서 action 수와 시간분포를 추정한다.

## 13.7 Pilot-based calibration

새 Agent/Skill 등록 시 대표 업무를 실행하여 다음을 수집한다.

- base action duration
- rejection rate
- retry count
- context growth
- review count
- review active time
- human correction time
- acceptance success

이 데이터로 rate card를 갱신한다.

---

# 14. ACEM에서 그대로 쓰지 않을 부분

- 통화비용은 제외한다.
- Infrastructure cost는 기본 제외한다.
- 인프라 대기가 완료시간을 늦추면 비용이 아니라 elapsed latency로 포함한다.
- Token은 필요할 경우 중간 feature로만 쓴다.
- ACEM의 HITL이 review/rework 중심인 점을 확장해 instruction, output reading, approval, manual validation, final acceptance까지 포함한다.

---

# 15. HITL Human Effort 모델

HITL 행동:

| 코드 | 행동 |
|---|---|
| U1 | 업무명세를 agent instruction으로 변환 |
| U2 | prompt/command 작성 |
| U3 | agent 출력 읽기 |
| U4 | diff/산출물 검토 |
| U5 | 승인·선택·판단 |
| U6 | 오류진단 |
| U7 | corrective instruction 작성 |
| U8 | 수동 검증 |
| U9 | 직접 수정 |
| U10 | 최종 승인·전달 |

개념적으로:

```text
HITL_i =
  instruction_time
  + review_checkpoint_count * review_duration
  + rejection_probability * correction_duration
  + manual_validation_time
  + required_human_only_subtask_time
```

검토시간은 output length, artifact type, risk, novelty, evidence availability, reviewer familiarity를 반영한다.

---

# 16. Human Blocking Latency

사람 노동량과 사람 때문에 생긴 대기시간은 다르다.

예:

```text
Agent approval request: 10:00
Human response:         10:25
Actual read/decision:    3 min

Human Active Effort = 3 min
Human Blocking Latency = 25 min
```

사전추정에서 Blocking Latency는 조직의 reviewer response profile이 있어야 한다.

없으면 HITL effort만 계산하고 blocking latency는 낮은 신뢰도로 표시한다.

---

# 17. Agent reliability와 Skill reliability

다음 단위로 관리한다.

```text
(agent, skill, task_type, domain, complexity)
    -> first-pass acceptance
    -> rejection rate
    -> retry distribution
```

샘플이 적으면 상위 범주 평균으로 shrink한다.

---

# 18. 에이전트 실행시간 계산

```text
MachineEffort_i =
  BaseAgentTime_i * RF_i * CF_i
  + ToolTime_i
  + MachineValidation_i
```

병렬 수행이 있으면:

- `Machine Effort`: 모든 machine node duration 합
- `Agent Elapsed`: DAG의 critical path duration

을 각각 계산한다.

---

# 19. Human-only와 Agentic 대응관계

출력에는 Work Unit별 대응관계를 남긴다.

```json
{
  "work_unit": "WU-04",
  "human_only": {
    "actions": ["검색", "자료선별", "요약", "검증"],
    "p50_minutes": 160
  },
  "agentic": {
    "skills": ["research", "citation-check"],
    "machine_p50_minutes": 21,
    "hitl_p50_minutes": 14
  }
}
```

이 구조가 audit의 핵심이다.

---

# 20. 최종 효율 지표

## Human Labor Leverage

```text
Human Labor Leverage =
  Human-only active effort
  / Agentic HITL human effort
```

사람 노동 1시간이 AI 미사용 인간 몇 시간짜리 결과를 생산하는지 나타낸다.

## Automation Share

```text
Automation Share =
  1 - HITL Human Effort / Human-only Effort
```

## Cycle Speedup

```text
Cycle Speedup =
  Human-only elapsed time
  / Agentic elapsed time
```

## Agent Throughput

```text
Agent Throughput =
  Human-only equivalent effort
  / Agent machine critical-path time
```

## Human Bottleneck Index

```text
Human Bottleneck Index =
  expected human-blocking critical-path time
  / agentic total critical-path elapsed time
```

보조지표:

```text
HITL Duty Cycle =
  HITL active human time
  / Agentic elapsed time
```

단일 Agentization Efficiency Score는 기본적으로 만들지 않는다. 노동절감과 완료속도는 다른 현상이기 때문이다.

---

# 21. 불확실성

모든 추정값은 P50/P80을 출력한다.

불확실성 원천:

- 업무분해
- 수량 추정
- 인간 요율
- Agent action duration
- first-pass acceptance
- retry count
- context growth
- review intensity
- human response latency

Monte Carlo 절차:

1. Work Unit 수량 샘플
2. Human rate 샘플
3. Agent duration 샘플
4. rejection/retry 샘플
5. HITL duration 샘플
6. DAG critical path 계산
7. 5,000~20,000회 반복
8. P50/P80/P95 저장

---

# 22. Calibration 데이터

## Human Rate Card

```text
(role, domain, action_type, complexity, familiarity)
    -> unit
    -> P50/P80 time
```

## Agent Rate Card

```text
(agent, model, skill, action_type, artifact_type, complexity)
    -> base machine duration
    -> tool duration
```

## Reliability Card

```text
(agent, skill, task_type, complexity)
    -> first-pass acceptance
    -> rejection rate
    -> retry distribution
```

## HITL Card

```text
(role, artifact_type, risk, review_type, quantity)
    -> review duration
    -> correction duration
```

## Context Card

```text
(agent, model, context_strategy)
    -> alpha
    -> latency/context regression
```

---

# 23. Cold-start 모드

우선순위:

1. 동일 조직 + 동일 agent/skill 실측
2. 동일 조직 + 유사 task
3. 동일 agent/skill 외부 benchmark
4. 일반 category prior
5. 전문가 seed rate

Cold-start 결과는 P80 폭을 크게 하고 confidence C/D를 부여한다.

---

# 24. 실제 데이터로 지속 보정

실제 trajectory가 생기면 다음을 비교한다.

```text
Predicted:
  Work Unit
  Agent Action count
  Machine time
  HITL time
  RF
  CF
  HIS

Observed:
  actual actions
  actual machine duration
  actual human interventions
  actual rejection/retry
  actual context
  actual acceptance
```

오차를 BaseAgentTime, rejection rate, retry count, context multiplier, review duration에 되먹임한다.

---

# 25. 주 함수

```python
estimate_agentization_efficiency(
    spec: TaskSpecification,
    calibration: CalibrationProfile,
    options: EstimateOptions
) -> AgentizationEstimate
```

내부 의사코드:

```text
function estimate_agentization_efficiency(spec, calibration):

    normalized = normalize(spec)
    work_graph = decompose_into_work_units(normalized)
    validate_same_acceptance_scope(work_graph)

    for wu in work_graph:

        human_complexity = classify_human_complexity(wu, spec.role)
        human_actions = synthesize_human_actions(wu)
        human_quantities = quantify(human_actions, wu, spec)
        human_time = rate_human_actions(human_quantities)

        coverage = match_skills(wu, spec.agent_plan.skills)

        if coverage == NONE or coverage == BLOCKED:
            add_human_fallback(wu)
            continue

        agent_complexity = classify_agent_complexity(wu, spec.agent_plan)
        agent_actions = synthesize_agent_actions(wu, coverage)

        base_machine_time = rate_agent_actions(agent_actions)

        rf = estimate_revision_factor(wu, agent, skill)
        cf = estimate_context_factor(wu, work_graph, agent_plan)
        his = classify_hitl_intensity(wu, agent, skill)

        hitl = estimate_hitl(wu, agent_actions, his, rf)

        add_agentic_node(
            machine = base_machine_time * rf * cf,
            hitl = hitl
        )

    simulations = monte_carlo(human_path, agent_path, dependencies)
    metrics = calculate_efficiency(simulations)

    return auditable_report(...)
```

---

# 26. Work Decomposer 출력 계약

```json
{
  "work_units": [
    {
      "id": "WU-01",
      "goal": "",
      "artifact_type": "",
      "input_refs": [],
      "output_description": "",
      "acceptance_criteria": [],
      "dependencies": [],
      "workload_drivers": [],
      "required_capabilities": [],
      "human_complexity_evidence": [],
      "agent_complexity_evidence": [],
      "risk_factors": []
    }
  ]
}
```

금지:

- LLM이 `human_hours = 12`처럼 직접 시간을 출력
- 근거 없는 task count
- 없는 Skill capability를 임의로 가정

---

# 27. HIS 결정 규칙

MVP:

```text
if regulatory_mandated or safety_critical:
    HIS-4
else if domain_risk == high:
    HIS-3
else if reliability == low:
    HIS-3
else if domain_risk == medium and reliability != high:
    HIS-3
else if complexity in {medium, high}:
    HIS-2
else:
    HIS-1 or HIS-2
```

irreversible external side-effect가 있으면 최소 HIS-3.

---

# 28. 일반 업무용 Task Size Vector

Story Point 하나에 의존하지 않는다.

```yaml
task_size:
  information_volume:
    documents: 20
    pages: 140
    records: 5000
  artifact_volume:
    report_sections: 8
    spreadsheets: 2
  decisions:
    routine: 4
    analytical: 3
    high_risk: 1
  interactions:
    systems: 3
    stakeholders: 2
  validation:
    checks: 25
    scenarios: 6
```

Software domain에서는 Story Point, Function Point, Use Case Point를 추가 feature로 받을 수 있다.

---

# 29. 예시

입력:

```yaml
task:
  title: "월간 경쟁사 분석 보고서 작성"
  objective: "경쟁사 10곳의 지난 30일 제품·가격·마케팅 변화를 조사하고 15페이지 보고서를 작성한다."
  deliverables:
    - "15페이지 내외 보고서"
    - "근거 링크 목록"
  acceptance_criteria:
    - "10개 경쟁사 모두 포함"
    - "중요 주장에 출처 포함"
    - "가격 변동 검증"
    - "요약 및 경영 시사점 포함"

role:
  name: "시장 리서치 애널리스트"
  seniority: "mid"

work_context:
  ambiguity: medium
  novelty: medium
  risk: low

agent_plan:
  agent_id: "research-agent"
  autonomy_target: supervised
  skills:
    - research-web
    - spreadsheet-analysis
    - report-writing
    - citation-check
```

중립 Work Unit:

```text
WU1 요구 및 분석 프레임 이해
WU2 경쟁사별 자료 수집
WU3 자료 신뢰도/중복 선별
WU4 가격·제품 변화 구조화
WU5 패턴 분석
WU6 경영 시사점 판단
WU7 보고서 작성
WU8 출처/수치 검증
WU9 최종 검토·전달
```

설명용 가상 결과:

```text
Human-only P50          15.5 h
Agent Machine P50        2.8 h
HITL P50                 1.6 h
Agent Elapsed P50        3.1 h

Human Labor Leverage     9.7x
Automation Share        89.7%
Cycle Speedup             5.0x
```

실제 운영값은 calibration profile로 계산해야 한다.

---

# 30. 품질·적합성 Gate

다음 gate를 통과해야 강한 에이전트화 권고를 허용한다.

- required capabilities 충족
- legal/regulatory human requirement 충족
- expected acceptance probability 기준 이상
- 검증 가능성 존재
- irreversible risk 통제 가능
- 주요 데이터 접근 가능
- 사람 fallback 정의

Gate 실패 시 효율값은 계산할 수 있어도 `not_recommended`를 반환한다.

---

# 31. 신뢰도

A:
- Human rate 실측 충분
- 동일 agent+skill trajectory 표본 충분
- Work Unit 수량 명확
- acceptance/HITL 데이터 충분

B:
- 주요 셀은 실측
- 일부 유사 task로 보간

C:
- Cold-start prior 비중 큼
- 중요한 수량 또는 reliability 불확실

D:
- 업무 요구 모호
- capability 확인 불가
- rate data 거의 없음

---

# 32. 검증

Human-only:
- 같은 유형 task를 실제 사람이 AI 없이 수행
- 활성시간 기록
- P50 오차와 P80 coverage 평가

Agentic:
- 실제 trajectory에서 machine active time, retry, context, HITL event, acceptance 수집

전체:
- predicted human-only vs observed human-only
- predicted HITL vs observed HITL
- predicted elapsed vs observed elapsed

---

# 33. Ablation

다음 요소를 하나씩 제거해 예측오차 변화를 본다.

- RF 제거
- CF 제거
- HIS 제거
- skill reliability 제거
- human/agent complexity 분리 제거
- Task Size Vector 제거
- context reset feature 제거

---

# 34. API

```text
POST /estimate
POST /compare-agents
POST /calibrate
GET  /estimate/{id}/explain
```

`compare-agents`는 동일 업무에서 서로 다른 Agent+Skill 조합을 같은 기준으로 비교한다.

---

# 35. 최소 저장 테이블

```text
task_spec
work_unit
skill_registry
skill_capability
human_rate_card
agent_rate_card
agent_reliability
hitl_rate_card
context_profile
estimate_run
estimate_work_unit
observed_trajectory
observed_human_action
calibration_run
```

---

# 36. 구현 단계

## Phase 1 - Deterministic MVP

- YAML 입력
- Work Unit LLM 분해
- Human Action 분해
- Skill capability matching
- 고정 P50 rate
- Human/HITL/Machine 시간 합산
- 기본 efficiency 출력

## Phase 2 - ACEM-derived dynamics

- RF
- CF
- HIS
- Agent reliability
- context segmentation
- P50/P80

## Phase 3 - Monte Carlo / DAG

- 확률분포
- 병렬 agent
- critical path
- blocking latency

## Phase 4 - Continuous calibration

- trajectory ingest
- rate auto-calibration
- drift detection
- agent/skill versioning

---

# 37. 구현상 핵심 규칙

1. Human-only와 Agentic은 동일 완료상태를 비교한다.
2. LLM에게 최종 시간을 직접 찍게 하지 않는다.
3. 시간은 행동수량 × 보정요율로 계산한다.
4. Human complexity와 Agent complexity를 분리한다.
5. Agent 이름이 아니라 Agent × Skill × Task Type reliability를 사용한다.
6. Retry는 RF로, 사람 수정은 HITL로 각각 계산한다.
7. Context 오버헤드는 미래 예측에서만 CF로 보정한다.
8. 실제 context-inclusive trajectory에는 CF를 재적용하지 않는다.
9. 사람 활성노동과 사람 응답 대기시간을 분리한다.
10. Machine effort와 elapsed time을 분리한다.
11. 노동 레버리지와 cycle speedup을 함께 보고한다.
12. Cold-start 추정은 넓은 불확실성과 낮은 신뢰도를 표시한다.

---

# 38. ACEM에서 차용하는 특징적 기술 요약

1. **업무 크기 → 실행 자원으로 가는 calibration bridge**
   - 거친 요구사항/업무 크기를 과거 pilot 실행과 연결해 실제 Agent resource를 예측한다.

2. **Artifact Type × Complexity 기반 Base Resource**
   - task 종류와 난이도별로 기본 자원소모를 따로 보정한다.
   - TAEE에서는 BaseTokens보다 BaseAgentTime이 핵심이다.

3. **Revision Factor**
   - first-pass 실패와 retry가 Agent resource를 얼마나 팽창시키는지 명시적으로 모델링한다.

4. **Context Factor**
   - 장기 pipeline에서 context 누적 때문에 뒤 작업이 더 무거워지는 현상을 별도 모델링한다.

5. **HITL Intensity Score**
   - "Agent가 할 수 있는가"와 별개로 "사람이 얼마나 자주 봐야 하는가"를 독립 변수로 둔다.

6. **Pilot-based calibration**
   - 상수를 보편값으로 두지 않고 Agent/Skill/Domain/조직별 실제 실행으로 보정한다.

---

# 39. ACEM 대비 TAEE의 확장

| ACEM | TAEE |
|---|---|
| 소프트웨어 중심 | 일반 지식업무 + 소프트웨어 |
| 입력: SP/UCP/FP 등 | 할 일·역할·업무·Agent·Skills |
| 출력: 비용 | 출력: 시간 |
| LLM token cost | Agent machine effort / elapsed |
| HITL review + rework | instruction + read + review + decision + correction + validation |
| Infrastructure cost | 기본 제외 |
| Human-only baseline 없음 | Human-only counterfactual path 포함 |
| Agentic cost estimate | Human-vs-Agent efficiency estimate |
| token 중심 | time 중심 |
| agent 일반 | Agent × Skill reliability 중심 |

TAEE의 핵심 신규 구조는 다음이다.

> **동일한 요구사항에서 Human-only Path와 Agentic Path를 동시에 합성하고, ACEM식 agent dynamics를 Agentic Path에 적용하여 두 시간분포를 직접 비교한다.**

---

# 40. 최종 권고

제품 UI 최상단에는 다음을 노출한다.

```text
Human-only Effort       12.4 h
Agentic HITL Effort      1.5 h
Agentic Elapsed Time     2.1 h

Human Labor Leverage     8.3x
Cycle Speedup             5.9x
Automation Share         87.9%
```

`Agent Machine Effort`와 `Human Blocking Latency`는 진단용으로 추가한다.

한 숫자로 에이전트화 효율을 강제하기보다 `Human Labor Leverage + Cycle Speedup + Risk Gate`의 3축으로 판단하는 것을 기본으로 한다.

---

# 참고

ACEM은 2026-08-03 공개된 이론적 모델 구조이며 실제 프로젝트 데이터로 아직 검증되지 않았다. 저자는 RF, CF, HIS 및 sizing-to-resource mapping을 조직별 pilot data로 calibration할 것을 전제로 한다. 따라서 TAEE에서도 논문의 예시 상수를 운영값으로 사용하지 않고 실제 Agent/Skill trajectory로 보정해야 한다.
