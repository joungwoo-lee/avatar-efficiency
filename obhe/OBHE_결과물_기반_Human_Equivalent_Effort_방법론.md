# Claude Code 트레젝토리 기반 결과물 산정 및 Human Equivalent Effort 측정 설계

## 1. 목적

과거 Claude Code 세션의 트레젝토리 파일 1개 이상을 입력받아 사용자 PC에서 로컬 코드를 실행하고, 해당 세션들이 실제로 생성·수정한 최종 산출물을 최대한 deterministic하게 확인한다.

확정된 산출물은 LLM에 입력하여 다음 순서로 사람 기준 작업량으로 환산한다.

**트레젝토리 → 로컬 산출물 복원/확정 → 완료 결과 단위 분할 → 결과별 인간 행동량 추정 → 행동량 × 인간 시간요율 → Human Equivalent Effort**

핵심 원칙은 다음과 같다.

- **산출물 탐색과 Git diff는 LLM을 사용하지 않는다.**
- LLM은 **최종 산출물의 의미를 해석하고 인간 작업량으로 변환하는 단계**에만 사용한다.
- 최종 시간은 LLM이 직접 추측하지 않고 **행동량 × 실측 Human Rate**로 계산한다.
- AI가 만들었다가 폐기한 목업·중간안·시행착오는 최종 산출물에서 제거한다.
- 여러 세션이 하나의 작업을 이어서 수행한 경우 세션별 변경량의 합이 아니라 **전체 작업의 최종 net result**를 측정한다.

---

## 2. 전체 구조

```text
[Claude Code trajectory 1..N]
              |
              v
+-----------------------------------+
| Local Trajectory / Artifact Engine|
| 사용자 PC에서 실행                |
+-----------------------------------+
              |
              | 1. 세션/프로젝트 식별
              | 2. 수정 경로 추출
              | 3. Git 상태/이력 조사
              | 4. before/after 복원
              | 5. net diff 계산
              v
       [Artifact Manifest]
       - 작업 요구사항
       - 최종 변경 파일
       - 생성/수정/삭제
       - net diff
       - binary artifact
       - 추출 근거
       - confidence
              |
              v
+-----------------------------------+
| LLM Human Workload Estimator      |
+-----------------------------------+
              |
              | 1. 완료 결과 단위 분할
              | 2. 각 결과별 최소 인간 행동
              | 3. 행동별 workload 계산
              v
       [Human Action Ledger]
              |
              v
+-----------------------------------+
| Human Rate Engine                 |
+-----------------------------------+
              |
              v
     [Human Equivalent Effort]
```

---

## 3. 입력

### 3.1 필수 입력

- Claude Code trajectory JSONL 파일 1개 이상
- trajectory가 수행되었던 사용자 PC의 프로젝트/저장소

### 3.2 있으면 정확도가 크게 올라가는 입력

- 작업 시작 commit
- 작업 종료 commit
- 작업 당시 branch
- Git repository
- Claude Code checkpoint
- 작업 직후의 working tree snapshot

### 3.3 trajectory에서 deterministic하게 추출할 정보

가능한 경우 다음을 JSONL에서 직접 추출한다.

- session ID
- working directory / project
- timestamp
- user message
- tool call / tool result
- Write 대상
- Edit 대상
- NotebookEdit 대상
- Bash command
- Read/Grep/Glob으로 접근한 파일
- Git 관련 command
- 명시적으로 생성·삭제·이동한 경로

Claude Code 세션은 프롬프트, tool call, tool result, 응답을 포함하는 대화 기록을 저장하지만 파일시스템 자체를 저장하는 것은 아니다. 따라서 trajectory는 **변경의 증거와 작업 의도**이고, 파일의 최종 상태는 가능하면 Git이나 당시 filesystem에서 별도로 복원해야 한다.

또한 Claude Code의 transcript JSONL 내부 형식은 버전에 따라 변경될 수 있으므로 parser는 고정 JSON schema 하나에 강결합하지 않고 **version adapter + tolerant parser** 구조로 만든다.

---

## 4. 로컬 산출물 탐색 방법

### 4.1 1차: trajectory에서 직접 수정 경로 추출

LLM 없이 JSON parser로 다음 tool call을 찾는다.

- Write
- Edit
- NotebookEdit

각 세션에서 얻은 경로를 합친다.

```text
DirectTouchedPaths =
    Write paths
  ∪ Edit paths
  ∪ NotebookEdit paths
```

예:

```text
session_1:
  Edit  src/auth.ts
  Write src/token.ts

session_2:
  Edit  src/auth.ts
  Write tests/auth.test.ts

DirectTouchedPaths:
  src/auth.ts
  src/token.ts
  tests/auth.test.ts
```

이 단계는 높은 신뢰도의 **직접 변경 경로**를 제공한다.

### 4.2 2차: Bash에 의한 변경 후보 추출

Bash는 다음과 같은 방식으로 파일을 변경할 수 있다.

```text
echo ... > file
sed -i ...
cp
mv
rm
python generate.py
npm run build
make
code generator
```

Claude Code checkpoint도 Bash가 만든 파일 변경을 완전히 추적하지 않으므로 trajectory의 Write/Edit 목록만으로 전체 산출물을 판단해서는 안 된다.

Bash command는 LLM 없이 parser/heuristic으로 다음을 추출한다.

- 명시적인 output path
- redirect 대상
- cp/mv/rm 대상
- generator의 output option
- Git command
- build/output directory

이 결과는 `BashCandidatePaths`로 기록하며 직접 Write/Edit보다 낮은 confidence를 부여한다.

---

## 5. Git을 이용한 실제 최종 산출물 확정

### 5.1 핵심 원칙

**trajectory가 “어디를 건드렸는지” 알려주고, Git이 “결국 무엇이 남았는지” 확인한다.**

세션마다 diff를 합산하지 않는다.

여러 세션이 같은 작업을 이어서 수행했다면:

```text
전체 작업 시작 상태
        ↓
 session 1
 session 2
 session 3
        ↓
전체 작업 종료 상태
```

의 **시작 상태와 종료 상태 사이 net diff**만 계산한다.

따라서:

- 만들었다가 삭제한 파일
- 구현했다가 원복한 코드
- 실패한 prototype
- 중간 리팩터링

등은 최종 변경에 남지 않으면 자동으로 제외된다.

### 5.2 Base State 결정 우선순위

정확한 base commit은 다음 우선순위로 결정한다.

1. 사용자가 명시적으로 제공한 base commit
2. trajectory에서 확인되는 작업 시작 HEAD
3. trajectory의 Git command에서 확인되는 commit/branch
4. 작업 시작 timestamp와 Git reflog/history를 이용한 best-effort 추정
5. 판단 불가

Base State를 확정할 수 없으면 결과에 반드시 confidence를 낮춰 표시한다.

### 5.3 End State 결정 우선순위

1. 사용자가 제공한 end commit/snapshot
2. trajectory에서 작업 종료 후 생성된 commit
3. 작업 직후의 working tree가 현재도 유지되는 경우 현재 filesystem
4. checkpoint/snapshot으로 복원 가능한 경우 해당 상태
5. 판단 불가

**과거 세션 이후 저장소가 계속 수정되었고 당시 변경이 commit이나 snapshot으로 남아 있지 않다면 trajectory만으로 당시 최종 filesystem을 완전히 복원하는 것은 불가능할 수 있다.**

이 경우 시스템은 결과를 만들어내지 말고 `historical_state_unavailable`로 표시한다.

---

## 6. Git 기반 Artifact Manifest 생성

Git 저장소라면 기본적으로 다음을 수집한다.

```bash
git diff --name-status <BASE> <END>
git diff <BASE> <END> -- <paths...>
```

작업 종료 상태가 uncommitted working tree라면 추가로:

```bash
git diff <BASE>
git ls-files --others --exclude-standard
```

을 사용한다.

삭제, 신규, 수정, rename을 구분한다.

### 6.1 trajectory와 Git 결과 결합

```text
DirectTouchedPaths
BashCandidatePaths
GitChangedPaths
```

를 비교한다.

| 분류 | 조건 | 신뢰도 |
|---|---|---|
| DIRECT_NET | trajectory 직접 수정 + 최종 diff에 존재 | 매우 높음 |
| BASH_NET | Bash 후보 + 최종 diff에 존재 | 높음 |
| GIT_NET | trajectory에는 없으나 작업구간 최종 diff에 존재 | 중간 |
| TRANSIENT | trajectory에는 있으나 최종 diff에서 사라짐 | 최종 산출물 제외 |
| UNRESOLVED | 변경 증거는 있으나 historical state 복원 불가 | 낮음/측정 제외 |

`GIT_NET`은 사용자의 수동 변경이나 다른 동시 세션 변경일 가능성이 있으므로 자동 포함하지 않고 세션 시간, 경로 연관성, Git command 등의 규칙으로 attribution confidence를 계산한다.

---

## 7. 비 Git 산출물

Git repository가 아니거나 binary artifact가 있는 경우에도 동일한 원리를 적용한다.

가능한 경우:

- 파일 생성/수정 timestamp
- file hash
- trajectory의 Write/Edit/Bash path
- 디렉터리 스냅샷
- backup/checkpoint
- 파일 크기
- before/after hash

를 이용한다.

텍스트 파일은 before/after content diff를 만든다.

PDF, 이미지, PPTX, XLSX 등 binary file은:

- 파일 경로
- 생성/변경 여부
- before hash
- after hash
- 최종 파일 자체

를 Artifact Manifest에 포함한다.

---

## 8. Artifact Manifest

로컬 단계의 출력은 LLM에 바로 trajectory 전체를 넘기는 것이 아니라 **정규화된 Artifact Manifest**로 만든다.

예:

```json
{
  "job_id": "job-001",
  "sessions": ["s1", "s2", "s3"],
  "repository": "/workspace/project",
  "base_state": "abc123",
  "end_state": "def456",
  "task_requests": [
    "OAuth 로그인과 token refresh를 구현해줘"
  ],
  "artifacts": [
    {
      "path": "src/auth.ts",
      "status": "modified",
      "attribution": "DIRECT_NET",
      "diff": "...",
      "confidence": 0.99
    },
    {
      "path": "src/token.ts",
      "status": "created",
      "attribution": "DIRECT_NET",
      "content": "...",
      "confidence": 0.99
    },
    {
      "path": "tests/auth.test.ts",
      "status": "created",
      "attribution": "DIRECT_NET",
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

여러 trajectory가 같은 작업을 이어 수행한 경우:

```text
trajectory_1
trajectory_2
trajectory_3
      ↓
session metadata 추출
      ↓
동일 repo / branch / 시간연속성 기준 grouping
      ↓
전체 job의 base/end state 결정
      ↓
한 번의 net artifact 계산
```

세션별 결과를 각각 사람시간으로 계산한 뒤 합산하지 않는다.

그렇게 하면:

- 같은 파일 반복 수정
- 실패 후 재시도
- 목업 반복 생성
- 세션 간 원복

이 모두 사람 작업량으로 중복 계산되는 문제가 발생하기 때문이다.

---

## 14. 과거 trajectory 처리의 한계

Claude Code session은 대화 기록을 저장하지만 filesystem snapshot 자체는 아니다.

따라서 다음 상황에서는 당시 결과물의 정확한 복원이 어려울 수 있다.

- 당시 변경을 commit하지 않음
- 현재 working tree가 이미 다른 작업으로 변경됨
- checkpoint/snapshot도 없음
- Bash 또는 외부 프로그램이 파일을 만들었지만 그 흔적이 현재 사라짐
- 다른 사용자/세션이 같은 repo를 동시에 수정함

이때 시스템은 추정 결과를 사실처럼 확정하지 않는다.

권장 상태:

```text
EXACT
  base/end가 확정되고 net artifact 복원 가능

HIGH_CONFIDENCE
  대부분 복원되지만 일부 attribution 불확실

PARTIAL
  일부 파일만 복원 가능

UNRECOVERABLE
  당시 최종 산출물 상태를 복원할 근거가 부족
```

Human Equivalent Effort 계산은 기본적으로 `EXACT` 또는 `HIGH_CONFIDENCE`만 자동 승인한다.

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
| Git base/end 탐색 | Git command | X |
| 최종 net diff | Git | X |
| artifact manifest | local code | X |
| 완료 결과 단위 분할 | semantic reasoning | O |
| 인간 행동 선택 | semantic reasoning | O |
| 행동 workload 산정 | artifact reasoning | O |
| 시간요율 적용 | deterministic calculator | X |
| 최종 Human Effort | deterministic calculator | X |

즉 **LLM은 의미론이 필요한 중간 한 구간에만 사용한다.**

---

## 17. 권장 구현 모듈

```text
trajectory_ingestor
  - JSONL 읽기
  - schema adapter
  - session metadata

session_grouper
  - repo/cwd
  - timestamp
  - branch
  - session relation

path_extractor
  - Write/Edit/NotebookEdit
  - Bash candidate
  - Git commands

git_state_resolver
  - base commit
  - end commit
  - reflog/history fallback

artifact_resolver
  - net diff
  - untracked files
  - binary files
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
  - rate table
  - complexity adjustment
  - P50/P80 계산

reporter
  - Human Equivalent Effort
  - confidence
  - excluded artifacts
  - unresolved items
```

---

## 18. MVP 권장 범위

초기 버전에서는 범위를 좁힌다.

### 지원

- Git repository
- Claude Code JSONL trajectory
- 1개 또는 여러 세션
- Write/Edit/NotebookEdit
- 기본 Bash path heuristic
- text source code
- 신규/수정/삭제 파일
- 작업 시작/종료 commit이 존재하는 경우 우선 지원

### 후순위

- commit 없이 오래된 working tree 복원
- 동시 작업자 attribution
- 복잡한 Bash generator 추론
- binary 내부 semantic diff
- remote/network filesystem
- non-Git project

초기 목적은 **정확하게 복원 가능한 작업부터 높은 신뢰도로 측정하는 것**이다.

---

## 19. 최종 방법론 요약

방법론을 한 문장으로 정리하면 다음과 같다.

> **Claude Code trajectory는 AI가 한 일을 사람시간으로 세는 데 사용하지 않고, 사용자 PC에서 실제 최종 산출물을 찾아내는 증거로 사용한다. 최종 산출물이 확정되면 이를 독립적으로 완료 판정 가능한 결과 단위로 나누고, 각 결과를 숙련된 사람이 만들기 위해 필요한 최소 행동과 행동량으로 환산한 뒤, 실제 인간 시간요율을 곱하여 Human Equivalent Effort를 계산한다.**

전체 계산 흐름:

```text
Trajectory 1..N
    ↓
Local deterministic analysis
    ↓
Final net artifact
    ↓
LLM: 완료 결과 분할
    ↓
LLM: 결과별 인간 행동 + workload
    ↓
Human Rate Table
    ↓
Reference Human Effort
```

이 구조의 핵심은 다음 세 가지다.

1. **AI의 긴 시행착오 경로가 아니라 최종 net result를 측정한다.**
2. **LLM이 시간을 직접 추측하지 않고 행동량까지만 추론한다.**
3. **실제 시간은 조직의 human-only 실측 요율로 계산한다.**

---

## 20. 참고

Claude Code 공식 문서:

- Sessions: https://code.claude.com/docs/en/sessions
- Agent SDK Sessions: https://code.claude.com/docs/en/agent-sdk/sessions
- Checkpointing: https://code.claude.com/docs/en/checkpointing
- Agent SDK File Checkpointing: https://code.claude.com/docs/en/agent-sdk/file-checkpointing

설계상 특히 반영한 제약:

- session transcript는 대화와 tool 사용 기록을 보존하지만 filesystem 자체를 보존하지 않는다.
- transcript JSONL 내부 형식은 버전에 따라 바뀔 수 있다.
- Claude의 직접 편집 도구로 발생한 변경과 Bash/외부 도구에 의한 변경은 추적 특성이 다르다.
- checkpoint는 version control의 대체물이 아니므로 historical artifact 복원에는 Git을 우선 사용한다.
