# 멀티세션 AI 트레젝토리 기반 반사실적 인간 직행 노동량 산정 시스템 설계서

- 문서 버전: 2.0
- 상태: 구현 기준 설계
- 대상: Claude Code 및 유사 코딩 에이전트의 멀티세션 트레젝토리
- 주 산출물: 프로젝트/작업패키지 연결, 최종 수용 상태, 인간 직행 작업경로, 인간등가노동 P50/P80, 실제 인간 투입, 노동 레버리지, 신뢰도 및 근거

---

## 0. 한 줄 정의

이 시스템은 AI가 실제로 거친 시행착오 경로를 사람의 작업량으로 환산하지 않는다. 대신 여러 세션과 파일 변경을 하나의 프로젝트와 작업패키지로 연결하고, 최종적으로 수용된 결과 상태를 복원한 뒤, **초기 시점의 정보만 가진 기준 숙련자가 동일한 결과와 품질을 만들기 위해 선택할 수 있었던 최소 합리적 직행 경로**를 재구성하여 사람의 활성 노동시간을 산정한다.

이 값의 이름을 본 문서에서는 `Direct Human Equivalent Effort`, 약칭 `DHEE`라고 한다.

---

# 1. 문제 정의

## 1.1 왜 관측된 AI 경로를 그대로 사람 노동으로 계산하면 안 되는가

생성형 AI 기반 작업은 다음 특성을 가진다.

1. 사용자가 의도를 한 번에 완전히 전달하기 어렵다.
2. AI는 목업, 대안, 임시 구현을 매우 낮은 한계비용으로 반복 생성한다.
3. AI는 같은 파일을 여러 번 읽고, 같은 문제를 여러 방식으로 탐색하며, 잘못된 접근을 빠르게 폐기한다.
4. 사용자는 여러 후보를 보며 목적지를 점진적으로 구체화한다.
5. 결과적으로 실제 트레젝토리는 인간이 같은 최종 결과를 만들 때의 일반적인 작업경로보다 길 수 있다.

따라서 다음 계산은 금지한다.

> 인간등가노동 = AI가 수행한 읽기 + 검색 + 수정 + 실패 + 재시도 전체를 인간 시간요율로 환산

이 방법은 AI 특유의 경로 팽창을 인간 노동으로 잘못 간주한다.

반대로 다음 계산도 금지한다.

> 인간등가노동 = 최종 변경 라인 수 또는 최종 파일 분량만으로 계산

이 방법은 요구 해석, 코드베이스 파악, 설계 판단, 검색, 테스트 설계, 리뷰, 통합 같은 보이지 않는 필수 작업을 누락한다.

본 시스템의 목적은 두 오류 사이에서 **감사 가능하고 재현 가능한 반사실적 인간 노동 기준선**을 만드는 것이다.

---

# 2. 핵심 산정 원칙

## 2.1 산정 대상

DHEE는 다음 조건을 만족하는 인간 작업경로의 활성 노동시간이다.

- 동일한 시작 상태에서 출발한다.
- 동일한 요구 범위를 충족한다.
- 동일하거나 명시적으로 동등한 품질 기준을 충족한다.
- 최종 산출물의 정답을 미리 알고 있다고 가정하지 않는다.
- AI가 실제로 저지른 오해, 중복 탐색, 폐기된 목업은 재현하지 않는다.
- 숙련자에게도 합리적으로 필요한 탐색, 설계 판단, 검증은 포함한다.
- 기존 라이브러리, 템플릿, 코드, 조직 지식을 합법적으로 재사용할 수 있으면 재사용한다.

## 2.2 세 가지 시간을 절대 혼합하지 않는다

### A. Direct Human Equivalent Effort, DHEE

동일한 최종 수용 결과를 기준 숙련자가 최소 합리적 직행 경로로 만들 때 필요한 활성 노동시간.

### B. Actual Human-in-the-Loop Effort, AHIE

실제 AI 사용 중 사람이 투입한 프롬프트 작성, 출력 읽기, 승인, 수동 검토, 직접 테스트 등의 활성 노동시간.

### C. Machine Elapsed Time, MET

모델 생성, 빌드, 테스트, 패키징, 배포 등 기계가 소비한 경과시간.

생산성 비교의 기본 지표는 다음과 같다.

- 노동 레버리지 = DHEE / AHIE
- 순노동 절감 = DHEE - AHIE
- 경로 팽창률 = 관측된 AI 행동량 / 합성된 직행 행동량

기계 대기시간은 사람 노동시간에 자동 합산하지 않는다.

---

# 3. 분석 단위

원본의 `session`을 곧바로 프로젝트나 노동 산정 단위로 사용하지 않는다.

## 3.1 Event

한 번의 관측 행위.

예:

- 사용자 메시지
- 어시스턴트 메시지
- 파일 읽기
- 파일 편집
- 검색
- 명령 실행
- 테스트 실행
- Git 동작
- 승인/취소

## 3.2 Episode

같은 저장소, 목표, 브랜치, 문맥이 유지되는 연속 이벤트 구간.

한 세션은 여러 에피소드로 분할될 수 있다.

## 3.3 Session

Claude Code 또는 다른 에이전트가 저장하는 물리적 대화/도구 이력 컨테이너.

## 3.4 Project

동일 제품 또는 저장소 계보를 공유하는 장기 작업 범위.

## 3.5 Work Package

하나의 수용 가능한 목표로 닫히는 기능, 버그 수정, 문서, 분석, 마이그레이션 등의 단위.

노동량은 기본적으로 Work Package 단위로 계산한다.

## 3.6 Final Accepted State

다음의 묶음이다.

- 수용된 요구
- 최종 산출물 스냅샷
- 테스트/빌드/리뷰/승인/배포 증거
- 제외되거나 되돌린 변경

`마지막 이벤트`와 동의어가 아니다.

---

# 4. 시스템 경계와 구성요소

파이프라인은 다음 순서를 따른다.

1. `IngestAdapter`
2. `EventNormalizer`
3. `EpisodeSegmenter`
4. `ProjectLinker`
5. `WorkPackagePartitioner`
6. `FinalStateResolver`
7. `DirectPathSynthesizer`
8. `ActionQuantifier`
9. `RateEngine`
10. `ActualHumanEffortEstimator`
11. `MetricEngine`
12. `ReportBuilder`
13. `AuditStore`

모든 단계는 입력과 출력 JSON을 저장할 수 있어야 하며, 각 단계는 독립 재실행 가능해야 한다.

---

# 5. 구현 권장 디렉터리 구조

```text
human_effort_estimator/
  pyproject.toml
  README.md
  config/
    default.yaml
    rate_card.example.yaml
  schemas/
    normalized_event.schema.json
    episode.schema.json
    project.schema.json
    work_package.schema.json
    final_state.schema.json
    direct_path.schema.json
    estimate.schema.json
  src/
    hee/
      cli.py
      config.py
      models.py
      ingest/
        base.py
        claude_jsonl.py
        generic_jsonl.py
      normalize/
        event_normalizer.py
        path_normalizer.py
        git_context.py
      segment/
        episode_segmenter.py
      link/
        candidate_generator.py
        feature_extractor.py
        project_linker.py
        cluster_guard.py
      partition/
        work_package_partitioner.py
      state/
        final_state_resolver.py
        diff_manifest.py
      path/
        direct_path_synthesizer.py
        dependency_builder.py
        action_mapper.py
        prompts.py
      quantify/
        action_quantifier.py
        code_metrics.py
        document_metrics.py
      rates/
        rate_card.py
        monte_carlo.py
      actual/
        human_effort.py
      report/
        json_report.py
        markdown_report.py
      audit/
        provenance.py
        hashing.py
      llm/
        client.py
        structured_output.py
  tests/
    fixtures/
    unit/
    integration/
    golden/
```

언어는 Python 3.12 이상을 권장하지만 핵심은 구현 언어가 아니라 데이터 계약과 결정론적 계산의 분리다.

---

# 6. 입력 데이터 계약

## 6.1 원칙

Claude Code 또는 다른 에이전트의 원본 형식을 비즈니스 로직에 직접 노출하지 않는다. 원천별 `IngestAdapter`가 공통 이벤트로 변환한다.

원본 파일 포맷이 버전마다 달라질 수 있으므로 파서는 다음 전략을 사용한다.

1. 파일별 스키마 프로파일링
2. 알려진 필드 매핑
3. 알 수 없는 필드는 `source_payload_ref`에 보존
4. 필수 필드 누락 시 이벤트를 폐기하지 않고 `parse_warnings` 기록
5. 원본 파일 해시 보존

## 6.2 NormalizedEvent

권장 모델:

```json
{
  "event_id": "evt_...",
  "source": {
    "source_type": "claude_code_jsonl",
    "source_file_hash": "sha256:...",
    "source_record_index": 102,
    "schema_version": "unknown-or-version"
  },
  "session_id": "session-uuid",
  "parent_session_id": null,
  "subagent_id": null,
  "timestamp": "2026-08-09T10:15:13+09:00",
  "duration_ms": null,
  "actor": "human",
  "event_type": "prompt",
  "cwd": "/workspace/app",
  "repo": {
    "root": "/workspace/app",
    "remote_fingerprint": "sha256:...",
    "branch": "feature/export",
    "head": "abcdef1"
  },
  "task_refs": ["GH-123"],
  "goal_text": "CSV export 기능 추가",
  "file_actions": [],
  "command": null,
  "validation": null,
  "text": {
    "raw_ref": "blob:...",
    "redacted_text": "CSV export 기능 추가",
    "word_count": 4,
    "char_count": 17
  },
  "status": "success",
  "parse_warnings": [],
  "evidence_ref": "source-file.jsonl#102"
}
```

## 6.3 event_type 표준값

최소 다음 값을 지원한다.

```text
prompt
assistant_message
read_file
search_files
search_web
edit_file
create_file
delete_file
move_file
command
build
test
lint
format
git_status
git_diff
git_commit
git_checkout
git_merge
git_push
pr_create
pr_merge
artifact_create
artifact_view
human_approve
human_reject
human_cancel
session_start
session_end
unknown
```

## 6.4 FileAction

```json
{
  "path_before": "src/export.ts",
  "path_after": "src/export.ts",
  "operation": "edit",
  "before_hash": "sha256:...",
  "after_hash": "sha256:...",
  "added_lines": 42,
  "deleted_lines": 7,
  "is_generated": false,
  "is_vendor": false,
  "is_lockfile": false
}
```

## 6.5 Git 정보 수집

가능하면 이벤트 시점 또는 세션 시점의 다음 값을 보강한다.

```text
repo root
remote URL fingerprint
branch
HEAD
merge base
commit ancestry
changed file set
commit messages
PR/issue references
```

보안상 원격 URL 원문을 저장할 필요가 없으면 정규화 후 해시한다.

---

# 7. Episode 분할 알고리즘

## 7.1 목적

한 session 안에서 서로 다른 작업을 분리한다.

## 7.2 경계 신호

### Strong boundary

하나만 발생해도 기본적으로 새 에피소드 후보를 연다.

- Git repository 변경
- cwd가 다른 repository로 이동
- branch/worktree 전환 후 목표 변경
- 명시적 새 ticket/issue 시작
- 사용자 메시지에 새 작업 선언
- 완료 커밋/PR 이후 전혀 다른 요청

### Medium boundary

2개 이상 동시 발생 시 분할 후보.

- 목표 임베딩 유사도 급락
- 변경 파일 집합의 Jaccard 유사도 급락
- 모듈 경계 이동
- 테스트 대상 변경
- 긴 비활성 간격

### Merge-back signal

분할 후보가 있었더라도 다음이 강하면 다시 합친다.

- 동일 ticket/PR
- 동일 최종 산출물
- 동일 변경 파일 집합
- 직전 실패의 후속 수정
- 동일 수용 기준

## 7.3 기본 파라미터

초기값은 설정파일로 둔다.

```yaml
episode:
  inactivity_minutes: 120
  semantic_break_threshold: 0.35
  file_jaccard_break_threshold: 0.10
  medium_signals_required: 2
```

수치는 운영 라벨셋으로 보정한다.

## 7.4 의사코드

```text
function segment_session(events):
    episodes = []
    current = new_episode(events[0])

    for event in events[1:]:
        strong = detect_strong_boundary(current, event)
        medium_count = count_medium_boundaries(current, event)

        if strong or medium_count >= MEDIUM_REQUIRED:
            candidate = new_episode(event)
            if should_merge_back(current, candidate, lookahead_events):
                current.add(event)
            else:
                episodes.append(current)
                current = candidate
        else:
            current.add(event)

    episodes.append(current)
    return episodes
```

## 7.5 Episode 출력

```json
{
  "episode_id": "ep_001",
  "session_id": "s_001",
  "start_event_id": "evt_01",
  "end_event_id": "evt_47",
  "repo_fingerprint": "repo_abc",
  "branch": "feature/export",
  "task_refs": ["GH-123"],
  "goal_summary": "CSV export 기능 구현",
  "file_set": ["src/export.ts", "test/export.test.ts"],
  "boundary_open_reason": ["session_start"],
  "boundary_close_reason": ["new_ticket"],
  "confidence": 0.93
}
```

---

# 8. 프로젝트 연결 알고리즘

## 8.1 프로젝트와 작업패키지를 구분해야 하는 이유

같은 repository에서 여러 기능과 버그를 처리할 수 있으므로 `same repo = same work package`가 아니다.

반대로 동일 프로젝트가 여러 worktree, branch, cwd, session에 걸칠 수 있으므로 `same folder`만으로 연결할 수도 없다.

프로젝트는 장기 계보, 작업패키지는 최종 목표 단위다.

## 8.2 Candidate generation

모든 episode 쌍을 비교하면 O(N^2)이 되므로 다음 blocking key 중 하나라도 공유하는 쌍만 후보로 만든다.

- same parent/resume/fork lineage
- same repo fingerprint
- commit ancestry overlap
- same ticket/PR ID
- overlapping changed file fingerprint
- explicit artifact hash relationship

후보가 전혀 없더라도 semantic match가 매우 높은 최근 episode는 제한적으로 추가할 수 있다.

## 8.3 Pairwise link features

초기 feature와 점수:

| Feature | 초기 점수 | 설명 |
|---|---:|---|
| explicit resume/fork/parent | 강제 연결 | 직접 계보 |
| same repo fingerprint | +30 | 프로젝트 정체성 |
| commit ancestry/common HEAD | +20 | 개발 계보 |
| same ticket/PR | +15 | 명시적 작업 연결 |
| weighted file-set Jaccard | 최대 +15 | 산출물 결합 |
| goal semantic similarity | 최대 +10 | 의미 연결 |
| temporal proximity | 최대 +5 | 보조 신호 |
| branch/environment similarity | 최대 +5 | 보조 신호 |

감점:

| Conflict | 감점/처리 |
|---|---|
| different repo and no cross-artifact relation | 강제 분리 |
| same monorepo but separate modules/goals/files | -20 |
| explicit new unrelated project | -15 이상 |
| contradictory ticket IDs | -20 |

## 8.4 연속형 feature 계산 예

```text
file_score = 15 * weighted_jaccard(file_set_a, file_set_b)
semantic_score = 10 * cosine_similarity(goal_embedding_a, goal_embedding_b)
time_score = 5 * exp_decay(hours_between, half_life=72h)
```

수식 구현은 일반 부동소수 연산으로 한다.

## 8.5 임계값

```yaml
project_link:
  auto_link: 80
  guarded_link: 65
  review_low: 45
```

- 80 이상: 자동 연결
- 65~79: cluster consistency 검사 후 연결
- 45~64: 검토 큐
- 45 미만: 분리

자동 연결 구간은 재현율보다 정밀도를 우선한다.

## 8.6 단순 Union-Find 금지

A-B, B-C가 연결된다고 A-C가 무조건 같은 프로젝트인 것은 아니다.

따라서 새 episode를 cluster에 넣을 때 `cluster_guard`를 수행한다.

필수 검사:

- 대표 repo와 모순 없음
- 서로 양립 불가능한 ticket 집합 없음
- monorepo module이 완전히 분리되지 않음
- cluster medoid와 최소 유사도 충족
- 새로운 episode가 기존 cluster의 artifact lineage와 최소 하나 연결

## 8.7 출력

각 episode는 다음처럼 다대다 소속 근거를 가진다.

```json
{
  "project_id": "proj_001",
  "episode_members": [
    {
      "episode_id": "ep_001",
      "link_score": 94.2,
      "reasons": ["same_repo", "same_ticket", "file_overlap"],
      "manual_override": null
    }
  ]
}
```

---

# 9. Work Package 분할

## 9.1 분할 기준

같은 project 내부 episode를 다음 기준으로 다시 그룹화한다.

1. ticket/issue/PR ID
2. 사용자 요청의 목표 의미
3. 최종 산출물 결합
4. 변경 파일/테스트 결합
5. 완료 경계
6. 승인/배포 경계

## 9.2 공유 비용

다음은 work package마다 중복 계산하지 않는다.

- 최초 repository 구조 파악
- 공통 환경 설정
- 공통 아키텍처 판단
- 공통 dependency 설치

`shared_cost_nodes`로 project에 기록한 뒤 작업패키지에 배부한다.

배부 방식은 설정 가능하게 한다.

```text
equal
proportional_to_direct_effort
manual
```

MVP는 `equal` 또는 `manual`만 지원해도 된다.

---

# 10. 최종 수용 상태 FinalStateResolver

## 10.1 목적

로그의 마지막 순간이 아니라 실제로 수용된 결과를 찾는다.

## 10.2 완료 증거 우선순위

1. 사용자 명시적 승인
2. PR merge
3. release/deploy
4. final commit + 관련 test/build 성공
5. artifact 생성 + 검증 성공
6. 마지막 성공 검증 후 본질적 변경 없음 + 완료 선언
7. 위 증거가 없으면 마지막 일관된 산출물 상태를 잠정 채택

## 10.3 FinalState 모델

```json
{
  "work_package_id": "wp_123",
  "baseline_ref": {
    "commit": "abc000",
    "artifact_hashes": []
  },
  "final_ref": {
    "commit": "abc999",
    "artifact_hashes": ["sha256:..."]
  },
  "accepted_requirements": [
    {
      "id": "req_1",
      "text": "CSV 내보내기 기능 제공",
      "status": "accepted",
      "evidence_refs": ["evt_301", "commit:abc999"]
    }
  ],
  "deliverables": [
    {
      "type": "code",
      "path": "src/export.ts",
      "hash": "sha256:..."
    }
  ],
  "quality_evidence": [
    {
      "type": "test",
      "status": "pass",
      "evidence_ref": "evt_295"
    }
  ],
  "reverted_items": [],
  "confidence": 0.91,
  "assumptions": []
}
```

## 10.4 완료 후보 선택 알고리즘

```text
candidates = completion_markers(work_package.events)
for candidate in reverse_chronological(candidates):
    state = reconstruct_state(candidate)
    if has_acceptance_evidence(state) and no_material_change_after(candidate):
        return state

return last_coherent_state_with_low_confidence()
```

## 10.5 material change 정의

다음 중 하나면 본질적 변경으로 본다.

- accepted requirement 관련 코드 변경
- 공개 인터페이스 변경
- 테스트 기대값 변경
- 최종 산출물 내용 변경
- 사용자 요구 수정

다음은 보통 material change로 보지 않는다.

- 포맷팅만 변경
- lockfile 자동 변화
- 생성물 재생성
- 메타데이터만 변경

단, 프로젝트 규칙으로 override 가능해야 한다.

---

# 11. Direct Human Path 재구성

이 단계가 시스템의 핵심이다.

## 11.1 정의

`Direct Human Path`는 초기 시점에 이용 가능한 요구, 코드베이스, 문서, 도구, 조직 지식을 가진 기준 숙련자가 Final Accepted State를 달성하기 위해 선택할 수 있었던 **최소 충분하고 합리적인 작업 그래프**다.

최단 경로가 아니다. `합리적 직행 경로`다.

## 11.2 기준 숙련자 Persona

모든 추정에는 persona가 필수다.

예:

```yaml
persona:
  role: software_engineer
  seniority: senior
  stack_familiarity: high
  repository_familiarity: medium
  domain_familiarity: medium
  toolset:
    - IDE
    - git
    - web_search
    - project_tests
```

Persona가 다르면 같은 작업도 DHEE가 달라진다.

## 11.3 사후지식 방지 원칙

Final State를 알고 분석하지만, 인간 작업자에게 정답을 공짜로 주지 않는다.

### 허용

- 최종 diff를 사용해 어떤 변경이 실제로 필요했는지 식별
- 폐기된 AI 변경을 제거
- 최종 dependency graph를 복원

### 금지

- 최종 해결책을 사람이 처음부터 알고 있었다고 가정
- 최종 파일명을 보고 관련 파일을 즉시 정확히 찾았다고 가정
- 실제로 불확실했던 API/라이브러리 동작 조사 비용을 0으로 처리
- 테스트가 없는데 검증 비용을 0으로 처리

## 11.4 경로 생성 절차

1. accepted requirements를 원자 요구로 분해
2. baseline-final semantic diff 생성
3. 최종 변경을 의미 변경 단위로 그룹화
4. 각 변경의 선행 의존성 추적
5. human work breakdown structure 생성
6. AI 반복/오해/되돌림 제거
7. 필수 탐색/판단/검증을 다시 삽입
8. 각 작업을 HumanAction으로 변환
9. 행동별 수량 산출
10. 모든 노드에 근거 등급 부여

## 11.5 작업 그래프 Node 유형

최소 다음 유형을 지원한다.

```text
UNDERSTAND_REQUIREMENTS
LOCATE_RELEVANT_CONTEXT
READ_EXISTING_ARTIFACT
SEARCH_EXTERNAL_INFORMATION
MAKE_DESIGN_DECISION
IMPLEMENT_CHANGE
WRITE_TEST
RUN_TOOL
REVIEW_OUTPUT
DEBUG_EXPECTED
VALIDATE_FUNCTIONALITY
INTEGRATE
DOCUMENT
PACKAGE_OR_DELIVER
```

## 11.6 DirectPathNode

```json
{
  "node_id": "dp_10",
  "type": "READ_EXISTING_ARTIFACT",
  "title": "export 관련 기존 서비스 구조 파악",
  "depends_on": ["dp_01"],
  "rationale": "기존 API 스타일을 유지하기 위해 필요",
  "evidence": [
    {
      "kind": "structural",
      "ref": "final_diff:src/export.ts"
    }
  ],
  "evidence_grade": "B",
  "counterfactual_rule": "required_for_competent_implementation",
  "actions": []
}
```

## 11.7 LLM의 역할

LLM은 다음에 사용 가능하다.

- goal summary
- accepted requirement extraction
- semantic change grouping
- dependency hypothesis
- direct path draft
- human action classification
- rationale generation

LLM이 직접 최종 시간을 결정하게 하지 않는다.

시간 계산은 구조화된 actions와 rate card로 결정론적으로 수행한다.

## 11.8 Direct Path 생성용 LLM 출력 계약

LLM은 반드시 JSON으로만 반환하도록 한다.

예시 개념 스키마:

```json
{
  "nodes": [
    {
      "temp_id": "n1",
      "type": "UNDERSTAND_REQUIREMENTS",
      "title": "요구 확인",
      "depends_on": [],
      "why_required": "최종 수용 요구를 이해해야 구현 범위를 결정할 수 있음",
      "evidence_refs": ["req_1"],
      "knowledge_available_at_start": true,
      "would_exist_without_ai_mistakes": true
    }
  ],
  "excluded_observed_actions": [
    {
      "evidence_ref": "evt_88",
      "reason": "discarded_mockup"
    }
  ],
  "uncertainties": []
}
```

## 11.9 프롬프트 템플릿

```text
SYSTEM:
You reconstruct a counterfactual human work path from an AI-agent trajectory.
Do not replay the agent's mistakes.
Do not assume the human knows the final solution in advance.
Include only actions a competent practitioner would reasonably need from the initial state to the accepted final state.
Include necessary exploration, design decisions, verification, and integration.
Use the provided evidence IDs. Return only valid JSON matching the schema.

USER:
Baseline state:
{baseline_summary}

Accepted requirements:
{accepted_requirements}

Final semantic changes:
{semantic_diff}

Observed relevant evidence:
{evidence_bundle}

Reference persona:
{persona}

Produce the minimum sufficient reasonable human work graph.
```

프롬프트 버전을 provenance에 반드시 저장한다.

---

# 12. 사람 행동 분류 HumanAction Taxonomy

각 DirectPathNode를 하나 이상의 계량 가능한 행동으로 분해한다.

## A1. REQUIREMENT_READING

측정 단위:

- word_count
- requirement_item_count
- page_count

## A2. CONTEXT_READING

측정 단위:

- effective_lines
- function_count
- component_count
- document_words

`effective_lines`는 generated/vendor/lockfile/format-only를 제외한 관련 코드 범위다.

## A3. SEARCH

측정 단위:

- query_count
- result_set_count
- result_pages_reviewed

검색어 작성과 검색결과 판독을 분리해도 된다.

## A4. DESIGN_DECISION

측정 단위:

- decision_count
- complexity: low / medium / high
- risk: normal / high

예:

- API shape 결정
- 데이터 모델 변경
- 예외처리 정책
- 라이브러리 선택

## A5. IMPLEMENTATION

LOC보다 의미 변경 단위를 우선한다.

측정 단위 우선순위:

1. semantic_change_unit
2. function/component/config-block count
3. refined changed LOC

## A6. TOOL_EXECUTION_HANDLING

기계 실행시간이 아니라 사람이 명령을 준비하고 결과를 해석하는 활성시간을 측정한다.

측정 단위:

- execution_count
- result_block_count

## A7. REVIEW

대상:

- diff
- 로그
- 생성 문서
- 데이터 결과
- 화면

측정 단위:

- refined_changed_lines
- output_words
- page_count
- artifact_count

## A8. FUNCTIONAL_VALIDATION

측정 단위:

- scenario_count
- flow_count
- sample_count

## A9. EXPECTED_DEBUGGING

AI가 실제 실패한 횟수를 사용하지 않는다.

대신 해당 작업 난이도와 조직 통계에서 숙련자에게 기대되는 결함 수정 사이클을 사용한다.

초기 MVP에서는 다음 중 하나를 선택한다.

- rate card의 expected_debug_cycles
- 전문가 지정값
- 0으로 두되 confidence를 낮춤

## A10. INTEGRATION_AND_DELIVERY

측정 단위:

- PR count
- package count
- release count
- documentation section count

---

# 13. 행동 수량화 규칙

## 13.1 관련 코드 읽기 범위

전체 repository LOC를 사용하지 않는다.

다음의 합집합에서 읽기 후보를 만든다.

- 최종 변경 파일의 직접 dependency
- 최종 변경 파일이 참조한 인터페이스
- 관련 테스트
- 관련 설정
- 작업 요구에서 직접 언급된 파일
- 실제 트레젝토리에서 반복적으로 참조되었고 최종 변경 근거가 된 파일

그 후 최소 충분 집합을 선택한다.

## 13.2 구현량 정제

다음 변경은 별도 분류하거나 구현량에서 제외한다.

- generated code
- vendored code
- lockfile
- formatter-only
- snapshot mass update
- binary
- copied template with trivial substitution

## 13.3 의미 변경 단위 추출

AST를 사용할 수 있으면 다음 기준으로 묶는다.

- 함수 추가/변경
- 클래스/컴포넌트 추가/변경
- API endpoint
- schema migration
- config block
- test scenario group

AST를 사용할 수 없으면 diff hunk와 파일 유형을 기반으로 heuristic grouping한다.

## 13.4 문서 작업

코드가 아닌 문서는 다음 단위를 지원한다.

- 읽기 word count
- 작성 word count
- section count
- table count
- figure count
- review page count

---

# 14. Rate Card

## 14.1 개념

Rate는 돈이 아니라 `단위 행동당 활성시간`이다.

임금 비용이 필요하면 노동시간 계산 후 별도의 wage rate를 곱한다.

## 14.2 스키마

```yaml
rate_card_version: "2026-Q3-v1"
rates:
  - rate_id: read_code_medium
    action_type: CONTEXT_READING
    unit: effective_lines
    role: software_engineer
    seniority: senior
    stack: typescript
    familiarity: medium
    complexity: medium
    distribution:
      type: lognormal
      p50_per_unit_minutes: 0.30
      p80_per_unit_minutes: 0.48
    sample_count: 44
    source: internal_benchmark
```

위 숫자는 포맷 예시일 뿐 운영 기준값이 아니다.

## 14.3 필수 conditioning field

가능한 경우 다음 조건을 rate lookup에 사용한다.

```text
role
seniority
stack
domain
repository familiarity
domain familiarity
complexity
risk
action subtype
```

## 14.4 fallback hierarchy

정확한 rate가 없을 경우 다음 순서로 fallback한다.

```text
exact role + stack + familiarity + complexity
role + stack + complexity
role + action type + complexity
role + action type
global action type
```

fallback할수록 uncertainty를 넓힌다.

## 14.5 Rate calibration

조직 내 수동 수행 샘플로 보정한다.

샘플 수집 시 다음을 분리한다.

- active work
- machine waiting
- interruption
- meeting
- unrelated multitasking

각 행동별로 중앙값과 P80을 추정한다.

표본이 적으면 상위 그룹으로 shrinkage한다.

---

# 15. 노동량 계산

## 15.1 단일 행동

기본 계산:

```text
action_time = quantity * sampled_unit_rate + fixed_overhead
```

## 15.2 전체 작업패키지

```text
work_package_effort = sum(all action_time) + allocated_shared_cost
```

## 15.3 Monte Carlo

수량 또는 요율이 분포를 가지면 반복 샘플링한다.

권장 기본값:

```yaml
monte_carlo:
  iterations: 10000
  random_seed: 42
```

출력:

```text
P20
P50
P80
P95
mean
```

공식 보고의 기본값은 P50과 P80이다.

## 15.4 수량 불확실성

LLM이 추정한 수량은 단일값 대신 가능한 경우 범위로 표현한다.

```json
{
  "quantity": {
    "distribution": "triangular",
    "min": 2,
    "mode": 3,
    "max": 5
  }
}
```

정확히 계산 가능한 LOC, word count, test count는 deterministic으로 둔다.

---

# 16. Actual Human-in-the-Loop Effort

DHEE와 별도 계산한다.

## 16.1 프롬프트 작성

가능한 데이터:

- 이전 AI 응답 종료 시각
- 사용자 프롬프트 제출 시각
- 텍스트 길이
- 키입력 telemetry

키입력 telemetry가 없으면 다음과 같이 추정한다.

```text
lower bound = text length 기반 최소 작성시간
upper bound = 관측 dwell time에서 장기 idle 제거
central estimate = min(dwell-adjusted estimate, calibrated writing model)
```

## 16.2 AI 출력 읽기

다음 중 더 타당한 값을 사용한다.

- output word count * calibrated reading rate
- 다음 사용자 행동까지 dwell time

장기 idle은 제거한다.

## 16.3 승인/선택

권한 승인, 옵션 선택, 재시도, 취소 등의 이벤트를 count하여 fixed 또는 calibrated rate 적용.

## 16.4 수동 검토/테스트

사람이 실제 수행한 diff 검토, 브라우저 확인, 파일 열람, 외부 시스템 조작은 별도 계상한다.

## 16.5 관측 등급

- A: focus/typing/approval/manual-validation telemetry 존재
- B: message/tool timestamp 존재
- C: message sequence와 content만 존재

AHIE 결과에는 등급과 구간을 같이 표시한다.

---

# 17. 신뢰도와 근거 모델

## 17.1 Evidence grade

각 DirectPath action은 다음 등급 중 하나를 가진다.

### E1 Direct

원본 로그 또는 final diff에서 직접 확인되는 사실.

### E2 Structural

정적 분석, dependency, Git, 테스트 구조로 강하게 추론됨.

### E3 Model Inference

LLM 또는 heuristic이 추론했으나 직접 증거는 제한적.

### E4 Assumption

운영자가 명시적으로 둔 가정.

## 17.2 전체 confidence component

```text
project_link_confidence
work_package_confidence
final_state_confidence
direct_path_evidence_coverage
quantity_confidence
rate_quality
actual_human_observation_quality
```

## 17.3 등급

### A

- 프로젝트 연결이 강함
- 최종 수용 증거가 직접적
- direct path 대부분 E1/E2
- 조직 rate sample 충분

### B

- 일부 E3 존재
- 주요 가정은 제한적

### C

- final state 또는 rate quality가 약함
- 수동 검토 필요

### D

- 로그 누락 또는 수용 상태 불명확
- 참고값만 허용

---

# 18. 최종 출력 JSON 계약

```json
{
  "schema_version": "2.0",
  "project_id": "proj_001",
  "project_summary": "대시보드 기능 개선",
  "session_membership": [],
  "work_packages": [
    {
      "work_package_id": "wp_001",
      "goal": "CSV export 추가",
      "episode_ids": ["ep_01", "ep_04"],
      "baseline": {},
      "final_state": {},
      "direct_path": {
        "nodes": [],
        "actions": []
      },
      "effort_estimate": {
        "persona_id": "senior_ts_medium_familiarity",
        "rate_card_version": "2026-Q3-v1",
        "p20_minutes": 310,
        "p50_minutes": 450,
        "p80_minutes": 612,
        "p95_minutes": 790
      },
      "actual_human_effort": {
        "observation_grade": "B",
        "p50_minutes": 78,
        "range_minutes": [60, 110]
      },
      "metrics": {
        "labor_leverage_p50": 5.77,
        "net_labor_saving_p50_minutes": 372,
        "agent_path_inflation": 2.4
      },
      "confidence": {
        "grade": "B",
        "components": {}
      },
      "assumptions": []
    }
  ],
  "provenance": {
    "input_hashes": [],
    "parser_version": "...",
    "feature_version": "...",
    "llm_model": "...",
    "prompt_version": "...",
    "rate_card_version": "...",
    "random_seed": 42,
    "generated_at": "..."
  }
}
```

---

# 19. CLI 계약

최소 다음 명령을 제공한다.

```bash
hee ingest INPUT_DIR --out normalized/
hee segment normalized/ --out episodes.json
hee link episodes.json --out projects.json
hee partition projects.json --out work_packages.json
hee resolve-final work_packages.json --out final_states.json
hee synthesize-path final_states.json --out direct_paths.json
hee estimate direct_paths.json --rate-card config/rates.yaml --out estimates.json
hee report estimates.json --format markdown --out report.md
hee run INPUT_DIR --config config/default.yaml --out run_001/
```

`hee run`은 모든 중간 산출물을 보존해야 한다.

---

# 20. 설정파일

```yaml
version: 1

persona:
  role: software_engineer
  seniority: senior
  stack_familiarity: high
  repository_familiarity: medium
  domain_familiarity: medium

episode:
  inactivity_minutes: 120
  semantic_break_threshold: 0.35
  file_jaccard_break_threshold: 0.10
  medium_signals_required: 2

project_link:
  auto_link: 80
  guarded_link: 65
  review_low: 45
  semantic_model: "configured-embedding-model"

final_state:
  require_quality_evidence_for_high_confidence: true

path_synthesis:
  llm_enabled: true
  prompt_version: "direct-path-v1"
  require_evidence_refs: true

rates:
  card_path: "config/rate_card.yaml"

monte_carlo:
  iterations: 10000
  random_seed: 42

privacy:
  store_raw_prompts: false
  hash_remote_urls: true
  redact_secrets: true
```

---

# 21. 결정론적 로직과 LLM 로직의 경계

## 반드시 결정론적으로 처리

- 원본 해시
- timestamp 정렬
- path normalization
- Git ancestry
- file diff
- LOC/word count
- exact test count
- link score 계산
- threshold 적용
- Monte Carlo
- metric 계산
- schema validation
- provenance

## LLM 사용 가능

- 목표 요약
- 요구 추출
- 의미 유사도 보조
- semantic change grouping
- direct path 초안
- 작업 이유 설명
- E3 추론

## 사람 검토 필요

- 45~64점 project link
- 서로 충돌하는 final state 후보
- 고액/고위험 작업
- confidence C/D
- 새로운 rate card 승인

---

# 22. 감사 가능성 요구사항

최종 숫자 하나에서 역으로 다음이 모두 추적되어야 한다.

```text
DHEE P50
 -> action time samples
 -> rate_id
 -> action quantity
 -> DirectPathNode
 -> evidence_refs
 -> normalized events / git state / final diff
 -> original source record
```

어느 숫자도 근거 없이 LLM의 자연어 판단만으로 생성되면 안 된다.

---

# 23. 예외 처리

## 23.1 Monorepo

같은 Git root만으로 project/work package를 합치지 않는다. module path, ticket, file set, test target을 함께 본다.

## 23.2 여러 worktree

repo fingerprint와 commit ancestry로 연결한다.

## 23.3 한 session에서 여러 project

Episode 분할 후 session-to-project를 다대다로 표현한다.

## 23.4 생성 코드

직접 구현량에서 제외하거나 매우 낮은 작성요율 + 별도 검토요율로 처리한다.

## 23.5 템플릿 복사

처음부터 작성했다고 보지 않는다.

직행 경로:

```text
템플릿 탐색 -> 적합성 판단 -> 적용/수정 -> 검증
```

으로 계산한다.

## 23.6 외부 회의/요구 확인

로그 밖이라 관측 불가능하면 0으로 두지 않는다.

`unobserved_external_work`로 남긴다.

## 23.7 사후 결함

안정화 창을 설정한다.

예: 완료 후 7일 또는 다음 release까지.

그 기간 내 원 작업으로 귀속되는 수정은 final accepted state와 노동량을 재계산할 수 있다.

## 23.8 요구가 AI 사용 중 진화한 경우

초기 요구만으로 최종 상태를 설명할 수 없으면 `scope_evolution`을 기록한다.

이때 두 지표를 분리할 수 있다.

- `DHEE_final_scope`: 최종 확정 범위를 처음부터 알고 있었다는 업무 발주 관점
- `DHEE_discovery_inclusive`: 합리적인 요구 탐색/결정 비용까지 포함한 제품 탐색 관점

생산성 보고 목적에 따라 어느 값을 쓰는지 명시해야 한다.

이 구분은 매우 중요하다. AI와의 목업 과정이 단순 낭비가 아니라 요구 발견 과정이었다면 전부 제거해서는 안 된다.

---

# 24. 가장 중요한 개념적 보정: 시행착오와 요구 탐색을 구분

AI의 반복은 세 종류로 분류해야 한다.

## R1. Agent Waste

AI만의 오해/중복/불필요한 반복.

예:

- 같은 파일 반복 읽기
- 잘못된 API 사용 후 되돌림
- 명백히 폐기된 대안 구현

DHEE에서 제거한다.

## R2. Necessary Problem Solving

사람도 합리적으로 해야 하는 탐색/실험.

예:

- 문서에 없는 라이브러리 동작 확인
- 불명확한 오류 원인 재현
- 성능 trade-off 비교

DHEE에 최소 합리량을 포함한다.

## R3. Requirement Discovery

사용자가 목업을 보며 무엇을 원하는지 결정한 과정.

예:

- UI 안을 보고 요구 수정
- 보고서 목업을 보고 지표 정의 변경
- 프로토타입 후 제품 범위 축소

이것은 단순 낭비가 아니다.

따라서 시스템은 `R3`를 별도 태그로 보존하고, 업무 생산성 지표에서는 목적에 따라 포함/제외할 수 있어야 한다.

---

# 25. Path Inflation 분석

AI 시행착오 자체도 진단 가치가 있으므로 버리지 않고 별도 지표로 저장한다.

예시:

```text
observed_file_reads = 47
counterfactual_human_reads = 11
read_inflation = 4.27

observed_edit_cycles = 13
counterfactual_expected_edit_cycles = 3
edit_inflation = 4.33
```

이 지표는 에이전트 품질과 프롬프트/워크플로 개선에 사용할 수 있지만 DHEE에 직접 더하지 않는다.

---

# 26. 검증 설계

이 시스템의 연구적 신뢰성은 여기서 결정된다.

## 26.1 Dataset A: Project/Episode linkage gold set

전문가가 session/episode를 직접 라벨링한다.

측정:

```text
precision
recall
F1
auto-link precision
cluster purity
```

운영에서는 auto-link precision을 특히 높게 유지한다.

초기 목표 예:

```text
auto-link precision >= 0.98
overall F1 >= 0.90
```

## 26.2 Dataset B: Final state gold set

실제 merge, release, deploy, 승인 기록이 있는 작업을 사용한다.

측정:

```text
final state accuracy
accepted deliverable recall
false-final rate
```

## 26.3 Dataset C: Human direct-path benchmark

핵심 검증셋.

절차:

1. 실제 작업의 baseline과 요구만 전문가에게 제공
2. 전문가가 AI 트레젝토리와 final solution을 보지 않은 상태에서 작업 계획 작성
3. 가능하면 실제로 작업 수행
4. 화면/IDE/명령을 기록해 행동별 활성시간 수집
5. 별도 분석자는 AI trajectory 기반으로 Direct Human Path를 재구성
6. 둘을 비교

측정:

```text
action coverage
extra-action rate
missing-action rate
sequence/dependency similarity
DHEE absolute error
DHEE log error
P50 interval coverage
P80 interval coverage
```

## 26.4 Counterfactual leakage test

최종 해답을 본 path synthesizer가 지나치게 낙관적인 경로를 만드는지 검사한다.

방법:

- Human blind path와 비교
- final solution에서만 알 수 있었던 정보가 무료로 주입되었는지 reviewer가 판정
- 누락된 exploration/validation 수 집계

`leakage rate`를 논문의 핵심 지표로 둔다.

## 26.5 Ablation

다음 모델을 비교한다.

### Baseline 1: Observed trajectory replay

AI의 관측 행동 전체를 사람 rate로 변환.

예상: 과대평가.

### Baseline 2: Final diff size only

LOC/word/page만으로 계산.

예상: 과소평가.

### Baseline 3: Expert top-down estimate

전문가가 작업 설명만 보고 시간 추정.

### Proposed

Evidence-Constrained Counterfactual Direct Path.

비교할 것:

```text
median absolute percentage error
median absolute error
bias
interval calibration
inter-rater agreement
```

## 26.6 Inter-rater reliability

Direct path gold label은 전문가 2인 이상이 독립 작성한다.

불일치 자체를 문제 난이도의 신호로 보존한다.

---

# 27. 테스트 전략

## 27.1 Unit tests

필수:

- path normalization
- repo fingerprint
- weighted Jaccard
- time decay
- link score
- strong conflict override
- generated-code filtering
- rate fallback
- Monte Carlo seed reproducibility
- metric calculation

## 27.2 Golden tests

작은 trajectory fixture를 만들고 기대하는 다음 결과를 고정한다.

```text
episode boundaries
project clusters
work packages
final state
DirectPath actions
effort P50/P80 tolerance
```

LLM이 포함된 golden test는 model drift에 취약하므로 구조 검증과 의미 판정 테스트를 분리한다.

## 27.3 Adversarial fixtures

최소 다음 케이스를 포함한다.

1. 같은 folder, 다른 project
2. 다른 worktree, 같은 project
3. 한 session 안의 두 project
4. 여러 session에 걸친 한 bug fix
5. final event가 실패 상태
6. 완료 후 revert
7. 대량 generated code
8. 사용자 요구가 중간에 변경
9. AI가 10개 mockup을 만들고 1개만 채택
10. 외부 문서 검색이 필수였던 작업

---

# 28. MVP 구현 순서

## Phase 1. Ingest + Normalization

완료 기준:

- 실제 trajectory 파일을 손실 없이 파싱
- 원본 record와 normalized event 역추적 가능
- parser regression test 존재

## Phase 2. Episode + Project + Work Package

완료 기준:

- 라벨셋 생성
- auto-link precision 측정
- manual review queue 구현

## Phase 3. Final State

완료 기준:

- Git diff와 validation evidence로 final state 생성
- false-final case fixture 통과

## Phase 4. Direct Path

완료 기준:

- structured JSON path 생성
- 각 node에 evidence refs 존재
- agent waste / necessary exploration / requirement discovery 분리

## Phase 5. Quantification + Rate Engine

완료 기준:

- deterministic quantities 계산
- rate card lookup
- P50/P80 재현성

## Phase 6. Validation Harness

완료 기준:

- human baseline record import
- proposed vs baseline error report 자동 생성

---

# 29. 운영 보고서 형식

프로젝트마다 다음을 보여준다.

```text
Project
  Work Package
    연결된 sessions/episodes
    최종 수용 요구
    baseline/final state
    인간 직행 경로
      행동
      수량
      rate
      시간기여
      evidence
    DHEE P50/P80
    실제 인간 투입
    노동 레버리지
    순노동 절감
    path inflation
    confidence
    assumptions
```

숫자만 제시하지 않는다.

특히 `5.8x productivity` 같은 단독 숫자는 금지한다. 반드시 기준 persona, scope, quality, AHIE observation grade를 함께 표시한다.

---

# 30. 보안과 개인정보

트레젝토리에는 소스코드, API key, 고객정보가 포함될 수 있다.

필수:

- 원본 immutable storage
- secret scanning
- prompt/source redaction option
- remote URL hashing
- RBAC
- per-project access control
- retention policy
- provenance log

LLM을 외부 API로 호출하는 경우 raw source 전송 여부를 정책화한다.

가능하면 semantic summary와 필요한 최소 snippet만 전송한다.

---

# 31. 구현 시 금지사항

1. session을 곧바로 project로 간주하지 말 것.
2. same folder만으로 project를 연결하지 말 것.
3. 마지막 event를 final state로 간주하지 말 것.
4. observed AI retries를 human debugging 횟수로 사용하지 말 것.
5. LLM에게 최종 시간을 직접 묻지 말 것.
6. LOC 하나만으로 작성시간을 결정하지 말 것.
7. machine wait를 human active labor에 넣지 말 것.
8. 최종 답을 아는 hindsight를 인간에게 무료로 부여하지 말 것.
9. 요구 탐색을 무조건 AI 낭비로 제거하지 말 것.
10. confidence 없이 단일 숫자만 출력하지 말 것.

---

# 32. 구현 완료 정의

다른 에이전트가 이 문서만 보고 구현할 경우 최소 성공 조건은 다음이다.

- trajectory adapter 1종 이상
- normalized event schema
- episode segmentation
- project clustering + review band
- work package partition
- final accepted state resolution
- Direct Human Path JSON 생성
- HumanAction 수량화
- versioned rate card
- reproducible Monte Carlo P50/P80
- AHIE 추정
- project/work-package JSON report
- provenance trace
- unit/golden/adversarial tests

다음까지 구현되면 연구용 프로토타입으로 본다.

- human blind baseline import
- direct-path accuracy metrics
- effort prediction error metrics
- ablation experiment runner
- interval calibration report

---

# 33. 논문화할 때의 연구 가설

## H1. Observed-path replay bias

에이전트의 실제 시행착오 경로를 인간 행동으로 환산하는 방식은 동일 결과를 만드는 인간의 실제 노동량을 체계적으로 과대추정한다.

## H2. Artifact-size bias

최종 diff/LOC만 사용하는 방식은 탐색, 판단, 검증을 누락하여 인간 노동량을 체계적으로 과소추정한다.

## H3. Direct-path superiority

Evidence-Constrained Counterfactual Direct Path 방식은 위 두 baseline 및 단순 top-down 전문가 추정보다 실제 인간 수행시간을 더 잘 예측한다.

## H4. Multi-session reconstruction value

session 단위로 독립 산정한 뒤 합산하는 방법보다 project/work-package 계보를 복원한 방법이 중복 컨텍스트 비용과 공유비용을 더 정확하게 처리한다.

## H5. Uncertainty calibration

행동별 rate 분포와 근거 수준을 사용한 P80 구간은 실제 인간 수행시간에 대해 목표 coverage에 가깝게 보정될 수 있다.

---

# 34. 논문용 핵심 연구질문

### RQ1

멀티세션 에이전트 트레젝토리에서 동일 프로젝트와 작업패키지를 얼마나 정확하게 복원할 수 있는가?

### RQ2

최종 수용 상태와 트레젝토리 증거만으로 인간의 최소 합리적 직행 작업경로를 얼마나 충실하게 복원할 수 있는가?

### RQ3

재구성된 행동경로 기반 노동량 추정은 관측 AI 경로 재생, 최종 산출물 크기, 전문가 top-down 추정과 비교해 실제 인간 노동시간을 더 정확하게 예측하는가?

### RQ4

추정 오차의 주된 원인은 프로젝트 연결, final-state 판정, path synthesis, quantity estimation, rate calibration 중 무엇인가?

### RQ5

AI 경로 팽창률과 실제 인간 노동 레버리지는 어떤 관계를 가지는가?

---

# 35. 연구에서 반드시 수집해야 할 데이터

논문으로 만들려면 설계만으로는 부족하다.

최소 다음 데이터가 필요하다.

```text
30~50개 이상 실제 project/work-package
100개 이상 multi-session trajectories 권장
각 work-package의 명시적 final accepted state
전문가 session/project/work-package label
일부 task에 대한 blind human direct-path
일부 task에 대한 실제 human execution time
행동별 active-time telemetry 또는 화면 기록
AI trajectory full logs
Git baseline/final snapshots
quality/test evidence
```

표본 수는 효과크기와 분산에 따라 power analysis로 최종 결정한다.

---

# 36. 연구적 차별점

본 방법의 핵심 기여 후보는 다음 네 가지다.

## Contribution 1. 새로운 측정대상

`실제 AI 경로 비용`이 아니라 `최종 AI 산출물에 대응하는 반사실적 인간 직행 노동량`을 정의한다.

## Contribution 2. 멀티세션 계보 복원

물리 session을 그대로 쓰지 않고 episode -> project -> work package -> final accepted state 계층을 복원한다.

## Contribution 3. Evidence-constrained path synthesis

최종 상태에서 역산하되 hindsight leakage를 통제하고, AI 낭비와 필수 문제해결과 요구 탐색을 구분한다.

## Contribution 4. 행동 기반 확률적 노동량 모델

재구성된 인간 작업경로를 계량 가능한 행동으로 분해하고 조직별 rate distribution으로 P50/P80을 산정한다.

---

# 37. 관련 연구와의 위치

본 연구는 아래 계열과 인접하지만 동일하지 않다.

1. Human-calibrated AI capability benchmark
   - 사람이 실제로 task를 수행한 시간을 직접 측정해 AI task horizon을 정의한다.
   - 본 방법은 인간 baseline이 없는 실제 운영 로그에서도 인간 baseline을 사후 추정하는 것이 목적이다.

2. AI-assisted developer productivity RCT
   - AI 허용/금지 조건의 실제 completion time을 비교한다.
   - 본 방법은 실험군/대조군이 없는 운영 데이터에서 work package별 counterfactual human effort를 추정한다.

3. Agentic software cost estimation
   - LLM token, HITL, infrastructure cost를 모델링한다.
   - 본 방법의 DHEE는 agent 운영 비용이 아니라 동일 산출물의 human-only effort baseline이다.

4. Agent trajectory efficiency/redundancy 연구
   - agent의 불필요한 context/read/action을 줄인다.
   - 본 방법은 agent 효율 최적화 자체보다 인간의 대체 노동량을 추정한다.

5. 전통적 software effort estimation
   - size, function point, story point, historical project data 등으로 미래 effort를 예측한다.
   - 본 방법은 완료된 AI-generated result와 trajectory evidence를 사용하여 사후 counterfactual effort를 복원한다.

---

# 38. 논문으로 만들 때의 가장 큰 위험

## 38.1 Ground truth 부재

반사실적 인간 노동량은 본질적으로 관측되지 않는다.

해결:

- 동일/유사 task의 blind human execution
- independent expert path
- RCT subset
- multiple raters

를 사용해 triangulation한다.

## 38.2 Hindsight leakage

final diff를 보는 순간 path가 지나치게 짧아질 수 있다.

해결:

- blind human path 비교
- leakage annotation
- minimum exploration rules
- final-solution-sensitive ablation

## 38.3 Rate card overfitting

한 조직의 rate가 다른 조직에 적용되지 않을 수 있다.

해결:

- organization-specific calibration
- hierarchical rate model
- cross-organization validation

## 38.4 Scope discovery ambiguity

AI 목업이 요구를 발견하는 과정이었다면 제거 여부에 따라 productivity가 크게 달라진다.

해결:

- Agent Waste / Necessary Problem Solving / Requirement Discovery 3분류
- final-scope-only와 discovery-inclusive 결과를 함께 제시

## 38.5 Quality mismatch

사람과 AI가 만든 결과의 품질이 다르면 시간 비교가 무의미하다.

해결:

- final accepted state에 quality evidence 포함
- post-completion defect window 포함
- human evaluator acceptance rubric 사용

---

# 39. 논문 실험의 최소 형태

가장 현실적인 첫 논문은 다음 범위가 적절하다.

## 대상

Git 기반 소프트웨어 개발 작업만 포함.

## 데이터

실제 Claude Code 멀티세션 100개 이상, 작업패키지 50개 이상.

## 비교법

- observed trajectory replay
- diff/LOC model
- expert top-down
- proposed direct-path model

## Ground truth subset

20~30개 작업은 인간이 baseline부터 직접 수행하며 활성시간을 기록.

## 결과

- project linking accuracy
- final state accuracy
- path action precision/recall
- effort MAE/MdAPE
- P50/P80 calibration
- hindsight leakage rate

이 정도면 방법론 논문으로 명확한 메시지를 만들 수 있다.

---

# 40. 참고 연구

설계의 학술적 위치를 잡기 위한 핵심 참고자료다.

1. Kwa et al. (2025), *Measuring AI Ability to Complete Long Tasks*. 인간이 실제 수행한 시간으로 AI의 task-completion time horizon을 정의.
2. Rein et al. (2025), *HCAST: Human-Calibrated Autonomy Software Tasks*. 189개 소프트웨어/ML/보안 작업에 대해 563개 인간 baseline을 수집.
3. Becker et al. (2025), *Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity*. 실제 OSS 개발자를 대상으로 AI 허용/금지 RCT 수행.
4. El-Ramly (2026), *ACEM: A Cost Estimation Model for Agentic Software Engineering*. LLM, HITL, infrastructure 관점의 agentic cost model 제안.
5. Yin and Feng (2026), *Do AI Agents Know When a Task Is Simple? Toward Complexity-Aware Reasoning and Execution*. minimum-sufficient execution과 agent redundancy를 연구.
6. Xiao et al. (2025), *Reducing Cost of LLM Agents with Trajectory Reduction*. agent trajectory의 redundant/expired information을 줄이는 비용 최적화 연구.
7. Robles et al. (2022), *Development Effort Estimation in Free/Open Source Software from Activity in Version Control Systems*. version-control activity에서 개발 effort를 추정하는 기존 계열.
8. Card, Moran, Newell (1980), *The Keystroke-Level Model for User Performance Time with Interactive Systems*. 행동 단위 시간 모델링의 고전적 선례.
9. Jørgensen (2004), *Top-down and bottom-up expert estimation of software development effort*. 소프트웨어 노력의 top-down/bottom-up 전문가 추정 비교.

---

# 41. 최종 구현 지침

구현자는 먼저 정확한 시간 추정보다 **계보와 근거의 정확성**을 우선해야 한다.

우선순위는 다음과 같다.

1. 원본을 잃지 않는 정규화
2. session을 episode로 올바르게 분할
3. project/work package를 과결합하지 않기
4. 실제 final accepted state 확정
5. Direct Human Path의 모든 노드에 근거 연결
6. 행동 수량화
7. rate calibration
8. uncertainty
9. productivity metric

초기 버전에서는 DirectPathSynthesizer가 완전 자동일 필요가 없다.

가장 현실적인 MVP는 다음이다.

> 결정론적 로그/Git 분석 + LLM path 초안 + 사람 승인 + 결정론적 노동량 계산

라벨과 실측 데이터가 쌓인 뒤 자동화 비율을 높인다.

---

# 42. 최종 판정

이 방법은 합리적이다. 다만 산정 대상을 `최종 결과를 이미 알고 바로 만드는 이론적 최단 인간 경로`로 정의하면 과소평가가 발생한다.

반드시 다음으로 정의해야 한다.

> 초기 시점의 정보와 통상적 도구만 가진 기준 숙련자가 동일한 최종 수용 상태를 만들기 위해 합리적으로 선택할 수 있었던 최소 충분 경로.

그리고 AI의 반복을 전부 제거하는 것이 아니라 다음 세 가지를 분리해야 한다.

- AI 고유의 낭비: 제거
- 사람에게도 필요한 문제해결 탐색: 포함
- 목업을 통한 요구 발견: 별도 계상 또는 목적에 따라 포함

이 세 구분과 `hindsight leakage` 검증이 이 방법론의 성패를 결정한다.
