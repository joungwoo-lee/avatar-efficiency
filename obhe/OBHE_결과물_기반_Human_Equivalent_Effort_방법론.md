# OBHE (Outcome-Based Human Effort): Claude Code 트레젝토리 기반 결과물 복원 및 인간 작업량 측정 설계

## 1. 목적

**OBHE(Outcome-Based Human Effort)**는 AI Agent가 실제로 남긴 최종 유효 결과를 기준으로, 동일한 결과를 숙련된 사람이 AI 없이 만들었다면 필요한 작업량과 시간을 추정하는 방법론이다.

본 설계는 과거 Claude Code 세션의 trajectory(JSONL) 파일 1개 이상을 입력받아 **사용자 PC에서 로컬 코드를 실행하여 해당 세션이 생성·수정한 산출물을 복원·확정**하고, 그 결과물을 사람 기준 작업량으로 환산하는 것을 목표로 한다.

전체 흐름은 다음과 같다.

**trajectory → 같은 작업끼리 세션 묶기 → 로컬 산출물 복원/확정 → 완료 결과 단위 분할 → 결과별 인간 행동량 추정 → 행동량 × 인간 시간요율 → OBHE**

이후 모든 단계는 묶인 작업(job) 단위로 수행한다. 세션을 묶는 기준은 같은 파일을 건드렸는가이다 (§13).

핵심 원칙은 다음과 같다.

- **GitHub/GitLab 등 원격 저장소 업로드는 필요하지 않다.** 모든 artifact 탐색은 사용자 PC에서 로컬로 수행한다.
- **로컬 Git도 필수는 아니다.** 있으면 before/after 상태를 검증하는 강한 증거로 사용한다.
- 산출물 탐색, snapshot 비교, hash 비교, diff 생성은 LLM을 사용하지 않는다.
- LLM은 **최종 산출물을 완료 결과로 분해하고 인간 행동량으로 변환하는 의미론 단계**에만 사용한다.
- 최종 시간은 LLM이 직접 추측하지 않고 **행동량 × 실측 Human Rate**로 계산한다.
- AI가 만들었다가 폐기한 목업·중간안·시행착오는 최종 산출물에서 제거한다.
- 여러 세션이 하나의 작업을 이어서 수행한 경우 세션별 변경량을 합산하지 않고 **전체 작업의 최종 net result**를 측정한다.
---

## 2. 전체 구조

```text
[Claude Code trajectory 1..N]
              |
              v
+---------------------------------------+
| Local Artifact Reconstruction Engine  |
| 사용자 PC에서만 실행                  |
+---------------------------------------+
              |
              | 1. 세션/프로젝트 식별
              | 2. Write/Edit/Bash 변경 경로 추출
              | 3. checkpoint/snapshot/filesystem 탐색
              | 4. 로컬 Git이 있으면 추가 검증
              | 5. before/after 및 final net artifact 확정
              v
       [Artifact Manifest]
       - 작업 요구사항
       - 생성/수정/삭제 파일
       - final content / net diff
       - 변경 증거(source)
       - transient/excluded artifact
       - reconstruction confidence
              |
              v
+---------------------------------------+
| LLM Outcome & Workload Estimator      |
+---------------------------------------+
              |
              | 1. 완료 결과 단위 분할
              | 2. 각 결과별 최소 인간 행동
              | 3. 행동별 workload 계산
              v
       [Human Action Ledger]
              |
              v
+---------------------------------------+
| Empirical Human Rate Engine           |
+---------------------------------------+
              |
              v
       [OBHE / Human Equivalent Effort]
```

### 산출물 복원의 기본 철학

OBHE는 **Snapshot-first, Git-assisted** 구조를 사용한다.

- snapshot/checkpoint가 있으면 그것으로 before/after를 복원한다.
- Git이 로컬에 있으면 commit/diff/status를 추가 증거로 사용한다.
- Git이 없어도 trajectory의 직접 편집 기록, checkpoint, 현재 filesystem, file hash/timestamp를 조합해 산출물을 복원한다.
- 원격 Git 서버로 push하는 과정은 어떤 경우에도 필요하지 않다.
---

## 3. 입력과 증거 우선순위

### 3.1 필수 입력

- Claude Code trajectory JSONL 파일 1개 이상
- trajectory가 실행되었던 사용자 PC 또는 해당 프로젝트 파일에 접근 가능한 로컬 환경

trajectory에 working directory가 남아 있고 해당 경로가 현재도 존재한다면 사용자가 별도 repository 경로를 입력하지 않아도 자동 탐색할 수 있다.

### 3.2 선택 입력

다음은 필수가 아니며, 존재할수록 historical artifact 복원 정확도가 높아진다.

- Claude Code checkpoint / rewind snapshot
- OBHE가 사전에 저장한 before/after local snapshot
- 작업 직후의 project directory backup
- 로컬 Git repository (commit/push 여부와 무관)
- 작업 시작/종료 commit 또는 branch (있으면 사용)
- 별도 filesystem snapshot / backup

**GitHub/GitLab에 push되었는지는 관계없다.** 로컬 `.git`만 존재해도 Git 정보는 사용할 수 있다.

### 3.3 trajectory에서 deterministic하게 추출할 정보

가능한 경우 JSONL에서 다음을 직접 추출한다.

- session ID
- working directory / project
- timestamp
- user message
- tool call / tool result
- Write 대상과 작성 내용
- Edit 대상과 변경 내용
- NotebookEdit 대상
- Bash command
- Read/Grep/Glob으로 접근한 파일
- Git command가 있다면 commit/branch 정보
- 명시적으로 생성·삭제·이동한 경로

Claude Code session은 대화와 tool 사용 기록을 보존하지만 filesystem 자체와 동일하지 않다. 따라서 trajectory는 **변경을 찾기 위한 증거**이며, 최종 artifact는 가능한 로컬 상태 증거를 조합해 별도로 확정한다.

### 3.4 Artifact Evidence 우선순위

동일 작업에 여러 증거가 존재하면 다음 순서로 신뢰한다.

1. **OBHE before/after snapshot**: 측정 시스템이 사전에 저장한 완전한 로컬 snapshot
2. **Claude checkpoint**: 직접 file-edit tool 변경의 before-state 복원
3. **로컬 Git before/after**: commit, diff, status, reflog 등
4. **trajectory의 Write/Edit/NotebookEdit 기록 + 현재 파일**
5. **Bash command에서 추출한 변경 후보 + 현재 filesystem/hash/timestamp**
6. 증거가 부족하면 `PARTIAL` 또는 `UNRECOVERABLE`

중요한 점은 특정 수단 하나를 필수화하지 않고 **여러 독립 증거를 합쳐 final artifact를 결정**하는 것이다.
---

## 4. 로컬 산출물 탐색 방법

### 4.1 trajectory에서 직접 수정 경로 추출

LLM 없이 JSON parser로 다음 tool call을 찾는다.

- Write
- Edit
- NotebookEdit

각 세션의 경로를 합친다.

```text
DirectTouchedPaths =
    Write paths
  ∪ Edit paths
  ∪ NotebookEdit paths
```

이 단계는 가장 높은 신뢰도의 **직접 변경 후보**를 제공한다.

가능하면 tool input에서 Write content, Edit old/new string 또는 patch도 함께 보존한다. 이것은 Git이 없어도 변경 결과를 재구성하는 증거가 된다.

### 4.2 Bash에 의한 변경 후보 추출

Bash는 다음과 같이 file-edit tool을 거치지 않고 파일을 바꿀 수 있다.

```text
echo ... > file
sed -i ...
cp / mv / rm
python generate.py
npm run build
make
code generator
```

Bash command를 parser/heuristic으로 분석하여 다음을 `BashCandidatePaths`로 기록한다.

- redirect 대상
- cp/mv/rm source 및 destination
- output option
- build/generated directory
- 실행한 script가 명시적으로 가리키는 output

Bash command만으로 실제 변경 여부를 확정하지 않고 snapshot/filesystem/Git evidence와 교차검증한다.

### 4.3 checkpoint / snapshot을 통한 before-after 복원

사용 가능한 경우 가장 먼저 파일 snapshot을 이용한다.

- Claude checkpoint가 있으면 직접 Write/Edit/NotebookEdit로 변경된 파일의 이전 내용을 복원한다.
- OBHE collector가 저장한 before/after snapshot이 있으면 Git 없이도 정확한 net diff를 계산한다.
- directory snapshot이라면 path, hash, size를 먼저 비교하고 변경된 파일만 content diff한다.

### 4.4 현재 filesystem과 대조

과거 세션 이후 해당 파일이 더 이상 수정되지 않았다면 현재 파일은 최종 artifact의 strong evidence가 될 수 있다.

다음 정보를 비교한다.

- trajectory timestamp
- file modification time
- current hash
- checkpoint hash
- trajectory의 마지막 Write/Edit 결과

세션 이후 다른 수정 가능성이 있으면 confidence를 낮춘다.

### 4.5 로컬 Git은 보조 검증으로 사용

로컬 `.git`이 있으면 다음을 추가로 사용한다.

```bash
git status --porcelain
git diff --name-status
git diff
git ls-files --others --exclude-standard
```

base/end commit을 아는 경우에는 commit 간 diff를 사용한다.

```bash
git diff --name-status <BASE> <END>
git diff <BASE> <END>
```

**원격 저장소로 push하거나 commit할 필요는 없다.** 현재 작업 tree의 uncommitted change도 Git으로 확인할 수 있다.
---

## 5. 실제 최종 산출물 확정

### 5.1 핵심 원칙

**trajectory가 변경 후보를 알려주고, 로컬 상태 증거가 결국 무엇이 남았는지를 확인한다.**

세션별 수정량을 더하지 않는다. 여러 세션이 하나의 일을 이어 수행했다면 시작 상태와 종료 상태 사이의 **최종 net artifact**만 측정한다.

따라서 다음은 최종 artifact에 남지 않으면 자동 제외한다.

- 만들었다가 삭제한 파일
- 구현 후 원복한 코드
- 실패한 prototype
- 중간 리팩터링
- 동일 결과의 반복 생성

### 5.2 Before State 결정 우선순위

1. OBHE가 저장한 작업 시작 snapshot
2. Claude checkpoint의 최초 file snapshot
3. 로컬 Git의 작업 시작 commit/HEAD
4. trajectory의 Read 결과 + Edit old-value 등으로 재구성 가능한 이전 상태
5. local backup / filesystem snapshot
6. 판단 불가

### 5.3 End State 결정 우선순위

1. OBHE가 저장한 작업 종료 snapshot
2. trajectory 종료 직후 checkpoint / filesystem snapshot
3. 로컬 Git의 종료 commit 또는 작업 tree
4. trajectory의 마지막 Write/Edit 결과와 현재 파일이 일치하는 경우 현재 filesystem
5. 판단 불가

과거 trajectory 이후 파일이 계속 변경됐고 before/end를 복원할 snapshot, checkpoint, local Git 이력이 모두 없다면 당시 final artifact를 완전히 복원할 수 없을 수 있다. 이 경우 억지로 확정하지 않고 confidence를 낮추거나 측정에서 제외한다.

### 5.4 파일 산출물이 없는 세션 — 답변형 산출물

코드 리뷰, 분석, 질의응답처럼 세션이 파일을 만들지 않는 경우, 산출물이 없는 것이
아니라 **산출물이 대화 속 최종 답변**이다. 이때는 다음처럼 처리한다.

- **산출물 = 최종 assistant 답변** (지적 사항, 판정, 권고). transcript에 원문이
  그대로 남아 있으므로 복원 불확실성이 없다.
- **읽기 workload는 실측**: trajectory의 Read/Grep/Glob 기록에서 읽은 파일 수,
  읽은 분량(LOC), 검색 횟수를 결정론적으로 센다. LLM은 이 수치를 그대로 쓰고
  읽기량을 새로 추정하지 않는다.
- **발동 조건**: job에 파일 편집 기록(Write/Edit)이 **0건일 때만 자동 발동**한다.
  편집이 있는 일반 세션에는 어떤 변화도 없다 — 코딩 세션의 최종 답변은 대부분
  작업 보고이고, 그 노동은 이미 diff에서 계산되므로 답변까지 세면 이중계산이다.
- **혼합 세션(리뷰+일부 수정)**: 기본은 파일 산출물만 계산한다(답변 몫은 누락 —
  과대평가보다 과소평가를 택한다). 리뷰 비중이 큰 job은 명시적 opt-in
  (`--include-answers`)으로 답변을 추가하되, LLM 규칙으로 "파일 artifact의 작업
  보고에 해당하는 서술은 제외하고 diff에 대응물이 없는 독립 결과만 세라"를 강제해
  이중계산을 막는다.

---

## 6. Artifact Reconstruction과 분류

각 변경 파일에 대해 여러 증거를 결합한다.

```text
DirectTouchedPaths
BashCandidatePaths
CheckpointChangedPaths
SnapshotChangedPaths
LocalGitChangedPaths
CurrentFilesystemEvidence
```

권장 classification:

| 분류 | 조건 | 신뢰도 |
|---|---|---|
| SNAPSHOT_NET | before/after snapshot으로 net change 확정 | 매우 높음 |
| CHECKPOINT_NET | checkpoint + final file로 직접 편집 변경 확정 | 높음 |
| LOCAL_GIT_NET | 로컬 Git diff로 net change 확정 | 매우 높음 |
| DIRECT_NET | trajectory 직접 수정 + 최종 content 일치 | 높음 |
| BASH_NET | Bash 후보 + filesystem/snapshot에서 실제 변경 확인 | 중간~높음 |
| TRANSIENT | trajectory에서 변경했으나 final state에서 사라짐 | 최종 산출물 제외 |
| UNRESOLVED | 변경 증거는 있으나 final state 복원 불가 | 낮음/자동 측정 제외 |

여러 증거가 같은 변경을 지지하면 confidence를 높인다.

---

## 7. Git이 전혀 없는 프로젝트

Git이 없어도 OBHE는 동작한다.

### 과거 작업

가능한 증거를 다음처럼 조합한다.

```text
trajectory Write/Edit patch
        +
Claude checkpoint
        +
현재 파일 / backup
        +
file hash / timestamp
        +
Bash path heuristic
        ↓
Artifact Reconstruction
```

### 앞으로 측정할 작업

OBHE local collector가 세션 시작/종료 시점에 프로젝트 변경 파일의 snapshot 또는 content-addressed backup을 자동 저장한다.

권장 최소 저장 항목:

```text
session/job ID
project root
path
before hash
after hash
before content 또는 binary backup
after content 또는 binary backup
change type(created/modified/deleted/renamed)
timestamp
trajectory file reference
```

이 구조를 사용하면 Git이 전혀 없는 프로젝트에서도 정확한 net artifact를 계산할 수 있다.

즉 OBHE에서 Git은 **필수 저장 계층이 아니라 선택적 검증 계층**이다.
---

## 8. Artifact Manifest

로컬 단계의 출력은 LLM에 trajectory 전체를 그대로 넘기는 것이 아니라 **여러 로컬 증거를 통합한 정규화된 Artifact Manifest**로 만든다.

예:

```json
{
  "job_id": "job-001",
  "sessions": ["s1", "s2", "s3"],
  "project_root": "/workspace/project",
  "before_state": {"source": "checkpoint", "id": "cp-001"},
  "end_state": {"source": "local_filesystem", "captured_at": "..."},
  "task_requests": [
    "OAuth 로그인과 token refresh를 구현해줘"
  ],
  "artifacts": [
    {
      "path": "src/auth.ts",
      "status": "modified",
      "attribution": "DIRECT_NET",
      "evidence_sources": ["trajectory_edit", "checkpoint", "current_hash"],
      "diff": "...",
      "confidence": 0.99
    },
    {
      "path": "src/token.ts",
      "status": "created",
      "attribution": "DIRECT_NET",
      "evidence_sources": ["trajectory_edit", "checkpoint", "current_hash"],
      "content": "...",
      "confidence": 0.99
    },
    {
      "path": "tests/auth.test.ts",
      "status": "created",
      "attribution": "DIRECT_NET",
      "evidence_sources": ["trajectory_edit", "checkpoint", "current_hash"],
      "content": "...",
      "confidence": 0.99
    }
  ],
  "excluded_transient_paths": [
    "src/oauth-prototype.ts"
  ],
  "unresolved": []
}
```

`task_requests`는 trajectory의 user message에서 deterministic하게 추출한다.

LLM이 산출물의 필요 여부를 판단할 때 최종 artifact만 보는 것보다 **원래 작업 요청을 같이 제공하는 것이 중요하다.**

---

## 9. LLM 단계의 목적

LLM은 trajectory를 따라가며 AI가 얼마나 많은 일을 했는지 세지 않는다.

LLM이 받는 핵심 입력은:

1. 원래 작업 요청
2. 최종 Artifact Manifest
3. 최종 파일/diff
4. 작업 시작 시 이미 존재했던 입력 또는 before-state

이다.

LLM의 역할은 두 단계지만 실용적으로는 한 번의 호출로 수행한다.

```text
최종 산출물
   ↓
완료 결과 단위 분할
   ↓
각 결과의 Human Work Path와 Workload 계산
```

---

## 10. 통합 LLM 프롬프트

```text
너의 목적은 AI가 만든 최종 산출물을 기준으로,
AI 없이 숙련된 사람이 동일한 유효 결과를 만들었다면
필요했을 인간 작업량을 산출하는 것이다.

[원래 작업 요청]
{task_requests}

[작업 시작 상태 / 기존 입력]
{before_state_or_inputs}

[최종 Artifact Manifest]
{artifact_manifest}

[최종 파일 및 net diff]
{artifact_contents_and_diffs}


반드시 다음 순서로 분석하라.


STEP 1. 완료 결과 단위 분할

최종 산출물에서 원래 작업 요청을 충족하는 결과를,
각각 독립적으로 완료/미완료를 판정할 수 있는 최소 단위로 분할하라.

규칙:

1. 파일 수, LOC, 페이지 수, 표 수 같은 외형으로 나누지 않는다.
2. '이 결과만 실패하고 다른 결과는 성공할 수 있는가?'가 YES이면 별도 결과로 분리한다.
3. 원래 작업 요청에 필요하지 않은 추가 산출물은 제외한다.
4. 최종 net artifact에 남지 않은 목업, 초안, 폐기안, 시행착오는 세지 않는다.
5. 다른 결과를 만들기 위한 중간재만으로 존재하는 것은 독립 결과로 세지 않는다.
6. 중복 표현은 하나의 결과로 합친다.
7. 각 결과가 최종 artifact의 어느 부분에서 확인되는지 근거를 명시한다.


STEP 2. 인간 행동 및 작업량 환산

STEP 1의 각 완료 결과에 대해,
AI 없이 해당 업무에 숙련된 사람이 처음부터 수행했을
정상적인 최소 작업경로를 계산하라.

사용 가능한 기본 인간 행동:

- 입력 및 맥락 이해
- 정보 검색
- 자료 읽기
- 정보 추출
- 변환/정규화
- 분석/비교
- 계산/실행
- 설계/판단
- 작성/구현
- 검증
- 최종 정리

규칙:

1. AI가 실제 수행한 시행착오 경로를 재현하지 않는다.
2. 최종 결과를 만드는 데 반드시 필요한 최소 인간 행동만 포함한다.
3. before-state에 이미 존재하는 것은 새로 만드는 비용으로 세지 않는다.
4. 작업 시작 시 이미 제공된 정보는 다시 검색하는 비용으로 세지 않는다.
5. 각 행동에는 결과물에서 근거를 찾을 수 있는 workload 단위를 붙인다.
6. workload는 가능한 한 수량화한다.
   예: 읽어야 하는 코드/문서 범위, 변경 기능 수, interface 수,
   비교 항목 수, 데이터 항목 수, testcase 수, 검증 항목 수.
7. 여러 결과가 같은 선행 행동을 공유하면 중복 계산하지 않는다.
8. 결과물만으로 workload를 판단할 수 없는 항목은 임의로 숫자를 만들지 말고
   MEASUREMENT_REQUIRED로 표시한다.
9. 시간은 직접 추정하지 않는다.


출력 형식:

[A. Completed Outcomes]

| Outcome ID | 완료 결과 | 완료 판정 기준 | Artifact 근거 |
|---|---|---|---|


[B. Human Action Ledger]

| Action ID | Outcome ID | 인간 행동 | Workload 단위 | Workload | 근거 | Shared |
|---|---|---|---|---:|---|---|


[C. Excluded Outputs]

최종 인간 작업량에 포함하지 않은 중간안, 목업, 불필요한 추가 결과와 이유.


[D. Measurement Required]

산출물만으로 작업량을 수량화할 수 없는 항목과 추가로 필요한 정보.


중요:
최종 시간이나 '사람이면 몇 시간' 같은 숫자를 직접 추측하지 마라.
이 단계는 사람의 행동 종류와 행동량을 산출하는 단계다.
```

---

## 11. Human Rate Engine

LLM 결과의 `Human Action Ledger`에 조직의 Human Rate Table을 적용한다.

예:

| Action Type | Workload Unit | P50 Rate | P80 Rate |
|---|---|---:|---:|
| 코드 읽기 | 100 logical LOC | 8분 | 14분 |
| interface 분석 | interface 1개 | 12분 | 20분 |
| 기능 구현 | function point 1개 | 35분 | 60분 |
| testcase 작성 | case 1개 | 8분 | 15분 |
| 검증 | assertion 1개 | 2분 | 4분 |

실제 값은 조직의 **human-only 작업 기록**으로 보정해야 한다.

계산:

```text
Action Effort =
    Workload
    × Human Rate
    × Complexity Adjustment
```

전체:

```text
Reference Human Effort =
    모든 unique action의 effort 합
    + 정상적인 Human Rework
```

공통 행동은 한 번만 계산한다.

---

## 12. 요율 적용 예시

LLM 결과:

```text
O1: OAuth 로그인 구현
- 기존 인증 구조 이해: 4 module
- OAuth interface 분석: 3 interface
- 구현: 2 functional unit
- testcase: 8 case
- 검증: 12 assertion
```

Rate Table이 다음이라면:

```text
module 이해      10분/module
interface 분석   15분/interface
functional unit  40분/unit
testcase 작성     8분/case
assertion 검증    2분/assertion
```

계산기는 단순히 각 workload에 해당 rate를 곱한다.

LLM에게:

> "이 일은 사람이 4시간 걸린다"

라고 묻지 않는다.

---

## 13. 다중 세션 처리

여러 trajectory가 입력되면 **어느 세션끼리 하나의 작업(job)으로 이어지는지**를
LLM 없이 결정론적으로 판정한 뒤, job 단위로 net artifact와 OBHE를 계산한다.

### 13.1 산출물 겹침 기반 세션 grouping

grouping의 1차 기준은 metadata가 아니라 **산출물이 공통인가**다.

```text
trajectory_1..N
      ↓
세션별 산출물 서명 추출
  = 그 세션이 건드린 경로 집합 (Write/Edit/NotebookEdit + Bash 후보)
  → working directory 기준 절대경로로 정규화
      ↓
겹침 판정: 두 세션의 서명에 공통 경로가 min_common(기본 1)개 이상이면 연결
      ↓
union-find로 연결요소 계산 → 연결요소 1개 = job 1개
      ↓
job마다 before/end evidence 결정 → 한 번의 final net artifact 계산 → OBHE
```

규칙:

1. **전이 연결**: s1∩s2, s2∩s3이 겹치면 s1과 s3이 직접 겹치지 않아도 같은 job이다
   — 파일을 옮겨가며 이어서 수행한 작업.
2. **절대경로 정규화**: 서로 다른 프로젝트의 같은 상대경로(README.md 등)가
   허위 병합되지 않도록 경로는 cwd 기준 절대경로로 비교한다.
3. **독립 세션**: 어떤 세션과도 산출물이 겹치지 않으면 독립 job으로 처리한다.
4. **근거 기록**: 어느 세션 쌍이 어떤 공통 경로 때문에 묶였는지를
   `grouping_evidence`로 Artifact Manifest에 남겨 grouping 자체를 감사 가능하게 한다.
5. **임계값**: 범용 설정 파일 하나 겹친 것만으로 무관한 작업이 묶이는 것을 막아야
   하면 min_common을 올린다.
6. **경로만 사용 (확정)**: grouping 판정에는 파일 경로만 쓴다. 파일 내용(Write
   content, Edit old/new)은 grouping에 사용하지 않는다 — 내용 대조는 산출물
   확정 단계에서만 쓴다.

### 13.2 job 간 이중계산 방지

여러 job이 같은 저장소의 같은 기간을 공유하면, 한 job의 diff에 다른 job의
변경이 섞여 들어와 사람 작업량이 이중계산될 수 있다. 따라서:

- 다른 job의 세션이 직접 건드린 경로는 이 job의 net diff에서 제거한다.
- 어느 job의 trajectory에도 증거가 없는 변경은 특정 job에 귀속하지 않고
  unresolved로 분리한다 — 사용자의 수동 변경이나 다른 작업일 수 있기 때문이다.

### 13.3 원칙

세션별 결과를 각각 사람시간으로 계산한 뒤 합산하지 않는다.

동일 파일이 여러 세션에서 반복 수정되어도 최종 상태에 남은 변경만 계산한다. Git이 있으면 local history를 보조 증거로 쓰고, Git이 없으면 checkpoint/snapshot/trajectory evidence를 세션 간 연결한다.
---

## 14. 과거 trajectory 처리의 한계와 신뢰도

Claude Code session은 conversation/tool history이지 filesystem 전체 snapshot은 아니다. 따라서 historical artifact의 정확도는 **당시 상태 증거가 얼마나 남아 있는가**에 의해 결정된다.

다음 상황에서는 정확한 복원이 어려울 수 있다.

- 당시 checkpoint/snapshot이 없음
- trajectory의 직접 Write/Edit 외에 Bash/외부 프로그램이 많은 파일을 변경함
- 세션 이후 동일 파일이 계속 수정됨
- backup이나 local Git history가 없음
- 다른 사용자/세션이 같은 파일을 동시에 수정함

권장 reconstruction status:

```text
EXACT
  before/end snapshot 또는 명확한 local Git/checkpoint 조합으로 net artifact 확정

HIGH_CONFIDENCE
  직접 tool 기록과 최종 파일이 일치하며 일부 보조 증거가 존재

PARTIAL
  변경 파일 일부는 확정했지만 전체 historical state는 불완전

UNRECOVERABLE
  당시 최종 산출물을 특정할 충분한 증거가 없음
```

Human Equivalent Effort 자동 계산은 기본적으로 `EXACT`와 `HIGH_CONFIDENCE`에 적용한다. `PARTIAL`은 부분값임을 명시하고, `UNRECOVERABLE`은 산정하지 않는다.
---

## 15. 왜 trajectory 자체의 작업량을 세지 않는가

trajectory는 AI의 실제 작업경로를 담고 있다.

그러나 AI는:

- 같은 것을 여러 번 생성
- 시행착오 반복
- 불필요한 목업 생성
- 오류 수정 반복

을 매우 싸게 할 수 있다.

따라서 trajectory의 tool call 수나 생성량을 그대로 사람 작업량으로 환산하면 AI 효율이 크게 과대평가될 수 있다.

trajectory의 역할은:

- 작업 요청 확보
- 프로젝트와 세션 범위 확인
- 변경 경로 후보 확보
- artifact attribution 보조

까지다.

**사람 작업량은 최종 net artifact에서 다시 계산한다.**

---

## 16. 책임 분리

| 단계 | 방법 | LLM 사용 |
|---|---|---|
| trajectory 읽기 | JSON/parser | X |
| 세션 grouping | 규칙/metadata | X |
| 수정 경로 탐색 | tool-call parser | X |
| Bash 후보 분석 | parser/heuristic | X |
| checkpoint/snapshot 탐색 | local filesystem | X |
| hash/content 비교 | deterministic diff | X |
| 로컬 Git 검증(있는 경우) | Git command | X |
| final artifact reconstruction | evidence resolver | X |
| artifact manifest | local code | X |
| 완료 결과 단위 분할 | semantic reasoning | O |
| 인간 행동 선택 | semantic reasoning | O |
| 행동 workload 산정 | artifact reasoning | O |
| 시간요율 적용 | deterministic calculator | X |
| 최종 OBHE | deterministic calculator | X |

즉 **LLM은 semantic decomposition에만 사용하고 artifact 복원과 시간계산에는 사용하지 않는다.**
---

## 17. 권장 구현 모듈

```text
trajectory_ingestor
  - JSONL 읽기
  - schema adapter
  - session metadata

session_grouper
  - 산출물 서명(수정 경로 집합) 겹침 기반 union-find grouping (§13.1)
  - grouping evidence 기록
  - timestamp / project 보조

path_extractor
  - Write/Edit/NotebookEdit
  - Bash candidate
  - optional Git commands

checkpoint_resolver
  - Claude checkpoint 탐색
  - before-state 복원

snapshot_manager
  - OBHE local before/after snapshot
  - content hash / binary backup

filesystem_evidence_resolver
  - current file
  - mtime/hash
  - backup/snapshot

local_git_adapter (optional)
  - status/diff
  - commit/reflog
  - untracked files

artifact_resolver
  - evidence fusion
  - final net artifact
  - attribution confidence

artifact_manifest_builder
  - normalized manifest
  - task requests
  - before/after evidence

human_workload_estimator
  - LLM prompt
  - outcome split
  - action ledger

human_rate_engine
  - empirical rate table
  - complexity adjustment
  - P50/P80 계산

reporter
  - OBHE
  - reconstruction confidence
  - excluded artifacts
  - unresolved items
```
---

## 18. MVP 권장 범위

### 지원

- Claude Code JSONL trajectory
- 1개 또는 여러 세션
- 사용자 PC 로컬 실행
- Write/Edit/NotebookEdit path 및 patch 추출
- Claude checkpoint 탐색
- 현재 filesystem hash/content 비교
- 기본 Bash path heuristic
- text source code 및 일반 파일
- 신규/수정/삭제 파일
- **Git 없는 프로젝트 지원**
- 로컬 Git이 있으면 optional diff 검증

### 후순위

- 오래된 과거 작업에서 snapshot/checkpoint/Git이 모두 없는 경우의 고급 복원
- 동시 작업자 attribution
- 복잡한 Bash generator의 output provenance
- binary 내부 semantic diff
- remote/network filesystem

MVP의 목표는 Git 사용 여부와 무관하게 **확정 가능한 artifact만 높은 신뢰도로 측정**하는 것이다.
---

## 19. 최종 방법론 요약

OBHE를 한 문장으로 정리하면 다음과 같다.

> **Claude Code trajectory는 AI의 시행착오량을 사람시간으로 세는 데 사용하지 않고, 사용자 PC에서 실제 최종 산출물을 복원하기 위한 증거로 사용한다. 최종 산출물을 독립 완료 결과로 분해하고, 각 결과를 사람이 만드는 데 필요한 최소 행동과 행동량으로 환산한 뒤 실제 인간 시간요율을 적용하여 Outcome-Based Human Effort를 계산한다.**

전체 흐름:

```text
Trajectory 1..N
    ↓
Local evidence extraction
    ↓
checkpoint / snapshot / filesystem
    + optional local Git
    ↓
Final net artifact
    ↓
LLM: 완료 결과 분할
    ↓
LLM: 결과별 인간 행동 + workload
    ↓
Empirical Human Rate Table
    ↓
OBHE
```

핵심은 다음 네 가지다.

1. **Git/GitHub는 필수가 아니다.** 로컬 snapshot과 trajectory가 기본이며 Git은 있으면 검증에 쓴다.
2. **AI의 긴 실행경로가 아니라 최종 net result를 측정한다.**
3. **LLM은 시간을 직접 추측하지 않고 결과와 행동량까지만 추론한다.**
4. **시간은 human-only 실측 rate로 계산한다.**
---

## 20. 논문화 시 핵심 선행연구와 OBHE의 차용점

이 방법론을 논문화할 경우 관련 연구를 넓게 나열하기보다, **현재 설계의 실제 구성요소와 직접 연결되는 연구만 인용하는 것이 적절하다.** 핵심 선행연구는 아래 4개이며, AI가 만든 과잉 산출물의 해석을 위해 METR의 Task Substitution 연구를 보조적으로 사용한다.

### 20.1 METR: coding-agent transcript에서 net successful output을 기준으로 인간시간 추정

**Reference**

Amy Deng. *Analyzing coding agent transcripts to upper bound productivity gains from AI agents*. METR Research Note, 2026.  
https://metr.org/notes/2026-02-17-exploratory-transcript-analysis-for-estimating-time-savings-from-coding-agents/

**이 연구가 한 일**

- 5,305개의 Claude Code transcript를 분석했다.
- 긴 transcript를 압축하되 code diff를 보존했다.
- LLM judge가 transcript에서 성공한 작업과 실패한 작업을 구분하고, 숙련 개발자가 AI 없이 **net successful output**을 만드는 시간을 추정했다.
- failed task, abandoned work, agent setup, agent-induced error correction, 불필요한 verbose planning 등을 인간 counterfactual 시간에서 제외했다.
- 저자는 개별 transcript를 따로 평가하면 **다른 세션에서 작업이 되돌려졌거나 이전 세션이 실패한 retry인 경우를 놓칠 수 있다**고 명시했다.
- human estimate 34건과 비교했을 때 LLM time judge에는 대략 2~3배 수준의 오차가 관찰되었다.

**OBHE에서 가져오는 아이디어**

1. **AI trajectory 전체 작업량을 세지 않고 net successful output만 측정한다.**
2. 실패, 폐기, agent-only overhead, agent가 만든 불필요한 오류수정은 Human Equivalent Effort에서 제거한다.
3. trajectory는 실제 업무를 관찰할 수 있는 유용한 데이터 소스다.

**OBHE에서 바꾸는 부분**

METR는 compressed transcript와 diff를 LLM에 넣어 **곧바로 인간시간을 추정**한다.

OBHE는 이 부분을 다음처럼 분리한다.

```text
METR:
trajectory + diff
    -> LLM
    -> human hours

OBHE:
trajectory
    -> local deterministic artifact reconstruction
    -> final cross-session net artifact
    -> LLM outcome/action workload decomposition
    -> empirical human rate
    -> human hours
```

즉 METR 연구가 지적한 **cross-session undo/retry 문제와 LLM 직접 시간추정 오차**를 줄이기 위해, 최종 artifact 확정과 시간 계산을 LLM 바깥으로 이동한다.

이 연구는 현재 방법론과 가장 가까운 직접 선행연구이므로 **필수 인용 대상**이다.

---

### 20.2 Epoch AI: 최종 PR/diff를 보고 비-AI 인간 effort를 counterfactual 추정

**Reference**

Jaeho Lee and Thomas Kwa. *Contributions to OpenAI's Codex codebase show signs of AI uplift*. Epoch AI, 2026.  
https://epoch.ai/data-insights/codex-engineer-effort

**이 연구가 한 일**

- OpenAI Codex repository의 merged PR을 대상으로 숙련 개발자가 AI 없이 동일한 변경을 만드는 데 필요한 시간을 LLM judge로 추정했다.
- PR title, description, commit message, 변경 파일 및 diff를 effort 판단의 근거로 사용했다.
- LOC 자체가 아니라 변경의 의미와 복잡도를 함께 판단했다.
- 저자들은 이 값을 실제 productivity의 확정치가 아니라 **upper bound에 가까운 값**으로 해석한다. AI가 없었다면 개발자는 똑같은 output을 만들지 않고 더 적게 만들거나 다르게 만들 수도 있기 때문이다.

**OBHE에서 가져오는 아이디어**

1. **최종 코드 변경물 자체를 human counterfactual effort 산정의 핵심 근거로 사용한다.**
2. LOC 같은 단순 물량보다 최종 diff의 의미와 구조를 봐야 한다.
3. 여러 중간 시도보다 **최종적으로 남은 변경**이 사람 작업량 측정의 기준이 되어야 한다.

**OBHE에서 바꾸는 부분**

Epoch는 최종 PR에서 LLM이 직접 holistic hour estimate를 만든다.

OBHE는:

```text
final artifact
    -> 독립 완료 결과
    -> 결과별 필요한 인간 행동
    -> 행동별 workload
    -> 실측 rate
```

로 분해한다.

따라서 최종 8시간이라는 숫자가 나왔을 때도 어떤 결과와 행동이 얼마를 차지했는지 추적할 수 있다.

이 연구는 **artifact-based human counterfactual effort**라는 문제 정의의 직접 선행연구이므로 필수 인용 대상이다.

---

### 20.3 Wright & Ziegler: 실제 Version Control 데이터로 '표준 개발자 effort'를 학습

**Reference**

Ian Wright and Albert Ziegler. *The standard coder: a machine learning approach to measuring the effort required to produce source code change*. arXiv:1903.02436, 2019.  
https://arxiv.org/abs/1903.02436

**이 연구가 한 일**

- 실제 개발자들의 Version Control code change와 그들이 투입한 coding time을 사용한다.
- 다양한 형태의 code change를 단순 LOC가 아니라 실제 개발자 행동 데이터에서 학습한 **Standard Coding Hours**라는 effort 척도로 환산한다.
- 핵심 개념은 특정 개인의 속도가 아니라, 실제 개발자 집단의 경험적 데이터로 구성된 **standard coder**가 해당 변경을 만드는 데 필요한 시간이다.

**OBHE에서 가져오는 아이디어**

1. 사람 effort의 최종 scale은 LLM의 상식 추정이 아니라 **실제 human-only 작업 데이터로 calibration**해야 한다.
2. 개인 한 명의 속도가 아니라 일정한 기준 숙련도를 대표하는 **Reference Human**을 정의해야 한다.
3. 단순 LOC보다 실제 변경의 구조와 실제 인간 노동시간의 관계가 더 적절한 effort 근거다.

**OBHE에서 바꾸는 부분**

Standard Coder는 code change 전체를 입력으로 effort를 직접 학습한다.

OBHE는 code change를 먼저 semantic outcome과 human action workload로 분해하고, 조직의 human-only 데이터를 **행동별 rate calibration**에 사용한다.

즉 이 연구의 특정 ML 모델을 가져오는 것이 아니라:

> **"artifact effort의 시간축은 실제 인간 작업 데이터로 교정해야 한다"**

는 측정 원칙을 가져온다.

이 연구는 Human Rate Engine의 경험적 calibration 근거로 필수 인용 가치가 있다.

---

### 20.4 Kaplan & Anderson: 행동량 × 단위시간의 계산 구조

**Reference**

Robert S. Kaplan and Steven R. Anderson. *Time-Driven Activity-Based Costing*. Harvard Business School Working Paper No. 04-045, 2003.  
https://www.hbs.edu/faculty/Pages/item.aspx?num=15805

**이 연구가 한 일**

Time-Driven Activity-Based Costing(TDABC)은 업무에 소요되는 자원을 계산할 때:

- 어떤 activity가 얼마나 발생했는지
- 그 activity 한 단위에 표준적으로 얼마의 시간이 필요한지

를 사용한다.

또한 모든 activity를 동일한 고정시간으로 처리하지 않고, 작업 특성에 따라 시간이 달라지는 경우 **time equation**으로 추가시간을 반영한다.

**OBHE에서 가져오는 아이디어**

Human Rate Engine의 계산 구조를 그대로 이 원리로 둔다.

```text
Human Action Effort
    = Workload Quantity
    x Standard Human Time Rate
    x Complexity Adjustment
```

예:

```text
검증시간
    = 기본시간
    + 검증 항목 수 x 항목별 시간
    + 고위험 항목 수 x 추가 검증시간
```

**OBHE에서 바꾸는 부분**

TDABC는 원래 조직 원가계산 방법론이다.

본 연구에서는 금전원가가 아니라 **counterfactual human labor time**을 계산하기 위한 rate engine으로만 그 계산 원리를 차용한다.

즉 AI 평가 연구의 직접 선행연구라기보다, OBHE의 **행동량→시간 환산식에 대한 방법론적 근거**다.

---

### 20.5 보조 근거: METR Task Substitution — AI가 만든 산출량과 실제 가치 증가를 동일시하면 안 됨

**Reference**

Tom Cunningham and Parker Whitfill. *Task Substitution and Uplift*. METR, 2026.  
https://metr.org/blog/2026-05-08-task-substitution-and-uplift/

**이 연구가 한 일**

AI가 특정 업무를 싸게 만들면 사람은 과거에는 하지 않았을 작업까지 새로 수행하게 된다. 이 때문에 AI 도입 후 수행된 업무 전체를 예전 인간 시간으로 환산한 `uplift on new tasks`가 실제 가치 증가보다 훨씬 크게 보일 수 있음을 설명한다. METR은 이런 경우를 “Cadillac task” 문제로 설명한다.

**OBHE에서 가져오는 아이디어**

최종 artifact에 존재한다는 이유만으로 모든 추가 산출물을 Reference Human Effort의 분모에 넣으면 안 된다.

따라서 결과를 두 범주로 구분한다.

```text
Required / Accepted Outcome
    -> Reference Human Effort에 포함

AI-enabled Optional Expansion
    -> 별도 Output Expansion으로 기록
    -> 기본 productivity 배수에는 자동 포함하지 않음
```

단, optional output이 실제 사용자 가치로 채택되었다면 이를 무조건 폐기해서도 안 된다. 이 경우 `core task efficiency`와 `additional value/output`을 별도로 보고하는 것이 맞다.

이 연구는 Human Rate 계산 자체의 근거가 아니라 **산출물 과장 방지 및 지표 해석의 근거**로만 사용한다.

---

## 21. 선행연구 대비 OBHE의 위치

핵심 차이는 다음과 같다.

| 방법 | 관측 입력 | Human effort 산정 | 주요 한계 / 본 연구의 개선 |
|---|---|---|---|
| METR transcript analysis | agent transcript + diff | LLM이 net successful output의 시간을 직접 추정 | cross-session undo/retry와 직접 time-judge 오차 → 로컬 artifact 재구성 + rate engine |
| Epoch Codex effort | merged PR + diff | LLM이 비-AI engineer 시간을 직접 추정 | output replication upper-bound → outcome 분해 + action workload |
| Standard Coder | VCS code change + human labor data | ML로 standard coder hours 추정 | 코드 전용 직접 모델 → 실제 인간 데이터 calibration 원칙을 action rate로 확장 |
| TDABC | activity quantity + unit time | time equation | AI 연구 아님 → human action rate 계산 엔진으로 사용 |
| OBHE | trajectory + local artifact evidence + final artifact | outcome → human action workload → empirical rate | 최종 산출물과 인간시간 사이의 중간 계산 근거를 명시적으로 남김 |

본 연구의 방법론적 novelty를 과장해서는 안 된다. 각각의 구성 아이디어는 기존에 존재한다.

본 연구가 새롭게 결합하는 부분은 다음과 같다.

1. **agent trajectory를 인간 effort 자체로 세지 않고 historical artifact attribution에 사용**
2. **여러 agent session에 걸친 실제 최종 net artifact를 snapshot/checkpoint/filesystem과 선택적 local Git을 이용해 로컬에서 deterministic하게 복원**
3. **최종 artifact를 독립 완료 결과로 semantic decomposition**
4. **각 결과를 human action workload로 변환**
5. **LLM direct hour estimate 대신 empirical Human Rate Engine으로 시간 환산**
6. **AI의 transient work와 optional output expansion을 core human-equivalent effort에서 분리**

즉 논문의 주장은 “새로운 effort estimation 이론을 처음 만들었다”가 아니라:

> **trajectory-based AI productivity estimation에서 local final-artifact reconstruction, semantic workload decomposition, empirical human-rate calibration을 결합하여 직접 LLM 시간추정보다 감사 가능하고 보정 가능한 OBHE를 만든다**

로 잡는 것이 안전하다.

---

## 22. 이번 논문의 핵심 레퍼런스에서 굳이 제외하는 연구

관련 있어 보이더라도 현재 설계에서 실제 방법을 가져오지 않는 연구는 핵심 reference로 억지로 넣지 않는다.

- **COSMIC / Function Point**
  - 기능 크기 측정 규칙을 실제 알고리즘에 적용하지 않으므로 현재 설계의 직접 근거가 아니다.
  - 향후 Outcome decomposition을 COSMIC functional process로 구현한다면 그때 포함한다.

- **Process Mining**
  - 현재 방법은 human event log에서 reference process를 자동 발견하지 않는다.
  - 향후 human-only 로그에서 실제 행동경로를 학습할 경우 포함한다.

- **HIE / Human-in-the-loop effort 연구**
  - AI 사용 중의 validation/oversight 비용을 계산하는 데는 관련되지만, 본 문서의 핵심인 **final artifact 기반 비-AI human effort** 산정에는 직접 사용하지 않는다.
  - 향후 AI Actual Effort까지 하나의 종합 효율식으로 합칠 때 별도 관련연구로 넣는다.

- **CodeBERT 기반 effort estimation**
  - artifact에서 effort를 예측한다는 점은 관련되지만, 현재 목적에는 실제 VCS와 human labor time을 사용한 Standard Coder가 더 직접적인 선행연구다.

- **Anthropic의 Claude conversation productivity estimation**
  - LLM으로 인간시간을 직접 추정하는 비교 baseline으로는 의미가 있다.
  - 다만 현재 방법의 핵심 구성요소를 직접 차용하지 않으므로, 실험에서 `Direct LLM Time Estimate` baseline을 둘 경우에만 관련연구로 추가하는 것이 적절하다.

---

## 23. 구현 참고: Claude Code 공식 문서

Claude Code 공식 문서:

- Sessions: https://code.claude.com/docs/en/sessions
- Agent SDK Sessions: https://code.claude.com/docs/en/agent-sdk/sessions
- Checkpointing: https://code.claude.com/docs/en/checkpointing
- Agent SDK File Checkpointing: https://code.claude.com/docs/en/agent-sdk/file-checkpointing

설계상 특히 반영한 제약:

- session transcript는 대화와 tool 사용 기록을 보존하지만 filesystem 자체를 보존하지 않는다.
- transcript JSONL 내부 형식은 버전에 따라 바뀔 수 있다.
- Claude의 직접 편집 도구로 발생한 변경과 Bash/외부 도구에 의한 변경은 추적 특성이 다르다.
- checkpoint는 filesystem 전체 또는 version control의 대체물이 아니다. OBHE는 checkpoint, local snapshot, filesystem evidence를 기본으로 결합하고, local Git이 존재하면 추가 검증 수단으로 사용한다. 원격 push는 필요하지 않다.
