# Session Translator 설계 — Codex·OpenCode 세션을 record-actions 측정기로 재기 (§96)

작성일: 2026-10-15
대상 버전: Codex CLI 0.162.1 (rollout jsonl), OpenCode 2.0.29 (v2 세션 저장소·`session export`)
고친 날: 2026-10-16 — 번역기와 측정기 분리(측정기 무변경), Codex 압축 기록(`.jsonl.zst`) 읽기

## 1. 목적

`session-api/record_actions_code_api.py`(LLM 0회 측정기)는 Claude Code 세션 기록만 읽는다.
이 문서는 Codex·OpenCode 세션도 **같은 측정기, 같은 규칙, 같은 요율**로 재는 방법을 정한다.

## 2. 방식 — 번역기와 측정기를 나눈다

번역기(이 폴더)는 Codex·OpenCode 기록을 **Claude Code 세션 모양의 jsonl 파일**로 바꿔 폴더에 써 낸다.
측정기(`session-api` 등)는 **한 줄도 바꾸지 않는다**. 번역기가 쓴 파일을 Claude 세션처럼 그대로 잰다.

```
Codex·OpenCode 세션 ──번역기(session-translator)──▶ Claude 모양 jsonl 폴더 ──기존 측정기(무변경)──▶ 효율
```

- 측정 규칙은 한 곳(기존 측정기)에만 있다. 에이전트별로 규칙이 갈라지지 않는다.
- 번역기는 "이 에이전트의 이 기록은 Claude 기록의 무엇에 해당하는가"만 정한다. 측정기를 불러 쓰지도 않는다.
- 서브에이전트 기록은 Claude와 같은 자리(`<세션>/subagents/agent-<id>.jsonl`)에 둔다.
  그래서 측정기의 자동 탐색(`find_subagent_files`·`measure_agent_actual`)이 그대로 동작한다.
- 번역한 파일의 수정 시각은 그 기록의 마지막 사건 시각으로 맞춘다. 측정기는 최근 10분 안에 바뀐
  파일을 진행 중 세션으로 빼기 때문이다(§44). 원본이 실제로 진행 중일 때만 그 규칙에 걸린다.
- 기록이 하나도 없는 세션은 쓰지 않고 요약에 "빈 세션"으로 센다(빈 파일을 남기면 수정 시각이 지금이 된다).
- 번역 중 생긴 주석(암호화 본문 환산)과 제외 사유는 번역 결과(`t.notes`·`t.excluded`)로 돌려준다.
  측정기 결과에는 섞지 않는다.

## 3. "100% 변환"의 정의

측정기가 Claude 기록에서 읽는 모든 입력(아래 4장의 계약)에 대해, 다음 중 하나가 성립해야 한다.

1. Codex·OpenCode 기록에 같은 뜻의 값이 있어 그대로 옮긴다.
2. 그 에이전트에 해당 기능이 아예 없어서, 옮길 값이 0이다. (예: 해당 기능을 쓰지 않은 세션)

이 정의를 벗어나는 항목은 한 가지뿐이다. Codex 다중 에이전트 v2가 **암호화해서 저장하는
에이전트 사이 메시지 본문**이다. 본문은 어디에도 평문으로 남지 않는다. 대신 그 메시지를 만든
응답의 출력 토큰 수는 정확히 남는다. 그래서 단어 수를 "토큰 수 × 같은 세션의 평문 응답에서 잰
단어/토큰 비율"로 환산한다(6.4절). 이 환산은 번역 결과의 `notes`(`t.notes`)에 건수와 함께 드러낸다.

## 4. 측정기가 읽는 Claude 기록 계약

조사 대상: `record_actions_code_api.py`, `requirement_actions.collect_record_stats`,
`transcript_actual.parse_actions`·`BackgroundExecTracker`·`WaitEvidence`, `session_api.measure_agent_actual`.

| 구분 | 필드 |
|---|---|
| 레코드 공통 | `type`(user·assistant·system·queue-operation), `timestamp`, `uuid`, `sessionId`, `isSidechain`, `isMeta`, `isCompactSummary`, `isVisibleInTranscriptOnly`, `isApiErrorMessage`, `permissionMode`, `entrypoint` |
| 메시지 | `message.id`, `message.model`, `message.content`(문자열 또는 블록), `message.usage.output_tokens_details.thinking_tokens` |
| 블록 | `text`, `thinking`, `tool_use{id,name,input}`, `tool_result{tool_use_id,content,is_error}`, `image` |
| 도구 결과 부가 | `toolUseResult{backgroundTaskId, taskId, agentId, isAsync, totalDurationMs}` |
| 시스템 | `system/turn_duration{durationMs}`, `queue-operation{content: <task-notification>}` |
| 사용자 텍스트 표식 | `<task-notification>`(`<task-id>`, `<tool-use-id>`, `<status>`, `<duration_ms>`), `[Request interrupted`, `<system-reminder` 등 시스템 접두 |
| 도구 이름·입력 | `Read{file_path,offset,limit}`, `Write{file_path,content}`, `Edit{file_path,old_string,new_string}`, `MultiEdit{edits}`, `Bash{command,run_in_background}`, `Grep`·`Glob`·`LS`·`WebSearch`·`WebFetch`(검색), `Agent{prompt,name}`, `TaskOutput`·`BashOutput`(배경 결과 폴링, 결과에 `<task_id>`·`<status>`), `SendMessage{to}`, `TodoWrite`, `AskUserQuestion`, `Skill`, MCP 도구 |
| 서브에이전트 | `<세션>/subagents/*.jsonl`, 전 레코드 `isSidechain`, 첫 user 텍스트 = 부모가 준 지시, assistant 텍스트 = 보고 |

## 5. 공통 변환 규칙

- 시각은 원본의 실제 시각을 ISO 8601(UTC, 밀리초)로 쓴다. 출력은 시각 순으로 정렬한다
  (`parse_actions`는 파일 순서대로 읽는다).
- 한 모델 응답의 블록은 같은 `message.id`를 공유한다. 응답의 생각 토큰 수는
  `usage.output_tokens_details.thinking_tokens`에 넣고, 그 응답의 모든 레코드에 반복한다
  (Claude의 스트리밍 기록과 같은 모양).
- 도구 호출은 "모델이 호출을 낸 시각"에 `tool_use`, "결과가 나온 시각"에 `tool_result`를 쓴다.
  권한 승인 대기는 이 둘 사이에 들어간다(Claude와 같다).
- 사람이 친 지시만 일반 user 텍스트로 쓴다. 하네스가 넣은 글(AGENTS.md, 환경 정보 등)은
  `isMeta: true`로 쓴다. 개발자(시스템) 메시지는 쓰지 않는다(Claude 기록에도 없다).
- 턴이 끝날 때 `system/turn_duration`을 쓴다.
- 파일 경로 입력 이름은 `file_path`로 통일한다. 줄 끝 `\r`은 지운다.

## 6. Codex (rollout jsonl, 0.162.1)

### 6.1 레코드 대응

| Codex 기록 | Claude 기록 |
|---|---|
| `session_meta` | `sessionId`. `source`가 `exec`이면 `entrypoint: "sdk-cli"`(헤드리스 실행 — 전 세션 집계 제외 규칙 §54와 같은 뜻) |
| `turn_context.approval_policy` | `permissionMode`: `never` → `bypassPermissions`, 그 외 → `default` |
| user `message` + `item_completed: UserMessage`(또는 `event_msg: user_message`) | 사람 지시(user 텍스트) |
| 위 확인이 없는 user `message` | `isMeta: true` (단, `<task-notification`·`[Request interrupted`로 시작하면 그대로 둔다) |
| developer `message` | 쓰지 않음 |
| `reasoning` | `thinking` 블록 (요약 평문이 있으면 그 글, 없으면 빈 글) |
| assistant `message` | `text` 블록 |
| `token_usage_record`(응답 단위) | 응답 경계와 `message.id`·생각 토큰 수. 없으면(구 기록) `token_count.last_token_usage` |
| `task_complete{duration_ms}` | `system/turn_duration` |
| `turn_aborted` | user 텍스트 `[Request interrupted by user]` + `turn_duration` |
| `compacted` | user `isCompactSummary` |

### 6.2 도구 대응

Codex 0.162는 도구를 대부분 **코드 모드 셀**(`custom_tool_call` 이름 `exec`, 자바스크립트) 안에서
부른다. 셀 안의 개별 호출은 `item_completed` 항목으로 따로 기록된다(시작·끝 시각 포함).
변환은 이 개별 항목을 기준으로 한다.

| Codex 항목·호출 | Claude 도구 |
|---|---|
| `CommandExecution`(명령 문자열은 `command`의 마지막 인자) | `Bash{command}`. 종료코드≠0이면 `is_error` |
| `FileChange` `update` | `MultiEdit{file_path, edits}` — diff 덩어리마다 old=문맥+지운 줄, new=문맥+더한 줄 |
| `FileChange` `add` | `Write{file_path, content}` |
| `FileChange` `delete` / `move_path` | `Bash{command: "rm <경로>"}` / `Bash{command: "mv <원경로> <새경로>"}` |
| `Extension` `web.search` | `WebSearch{query}` (그 외 웹 동작은 `WebFetch`) |
| `McpToolCall` | `mcp__<server>__<tool>` |
| `ImageView` | `Read{file_path}` + 결과 `image` 블록 |
| `DynamicToolCall` | 그 도구 이름 그대로 |
| 셀 속 `tools.write_stdin(...)` (항목 기록 없음) | 입력이 비면 `BashOutput`(배경 결과 폴링), 입력이 있으면 `Bash{command: 입력}` |
| 코드 모드 밖 `function_call` `shell`·`shell_command`·`exec_command` | `Bash{command}` |
| `apply_patch`(셀 밖) | 패치 본문을 파싱해 위 `FileChange`와 같게 |
| `update_plan` | `TodoWrite` |
| `request_user_input` | `AskUserQuestion` |
| `spawn_agent` | `Agent{prompt, name}` + 결과 `toolUseResult{agentId, isAsync: true}` |
| `wait_agent` | `TaskOutput` (기다리는 동안 끝난 에이전트의 `<task_id>`·`<status>`와 최종 답) |
| `send_message`·`followup_task` | `SendMessage{to, message}` |
| `interrupt_agent`·`close_agent` / `list_agents` | `TaskStop` / `TaskList` |

**셀 결과 규칙.** 결과 글은 AI가 실제로 본 글, 곧 셀이 찍은 출력이다.

- 셀 출력을 조각으로 나눈다. JSON으로 찍힌 조각은 문자열 값으로 풀어 이스케이프를 지운다
  (`chunk_id`·`session_id`·`exit_code` 같은 상태 값은 뺀다).
- 개별 호출마다 자기 항목 출력과 같은 조각을 찾는다. 출력 앞 120자가 조각 안에 있거나,
  조각 앞 120자가 출력 안에 있으면 같다. 웹 검색은 셀이 다른 꼴로 찍으므로 결과의 제목·주소가
  조각 안에 있으면 같다. 찾은 조각이 그 호출의 결과 글이다. 못 찾으면 AI가 보지 않은 것이므로
  결과 글을 비운다.
- 어느 호출에도 속하지 않는 조각(계획 기록, 도구 목록 조회 등 자바스크립트 자체 출력)은
  이름 `js_output`인 조회형 호출 1건의 결과로 둔다. 호출과 결과를 같은 시각에 써서 대기 시간은
  0이다. 측정기는 이것을 다른 미등록 조회 도구와 같게 다룬다(50단어 이상이면 읽기).
- 셀의 자바스크립트 접착 코드는 사람 작업으로 세지 않는다. 사람은 명령을 직접 실행하지 접착
  코드를 쓰지 않기 때문이다(`TodoWrite`가 0인 것과 같다).
- 셀 안의 개별 호출은 그 항목의 시작 시각에 `tool_use`, 끝 시각에 `tool_result`를 쓴다.
  항목은 "시작 시각을 품은 가장 늦은 호출"의 것으로 본다.

### 6.3 배경 실행

`exec_command`가 정한 시간 안에 끝나지 않으면 셀 결과에 `session_id`가 나오고, 실제 종료는 나중에
`CommandExecution` 항목(`completed_at_ms`)으로 기록된다.

- 셀 결과 시각에 `tool_result` "Command running in background with ID: <process_id>"와
  `toolUseResult.backgroundTaskId`를 쓴다(Claude `run_in_background`와 같은 모양).
- 실제 종료 시각에 `queue-operation` 완료 알림(`<task-id>`, `<status>completed|failed</status>`)을 쓴다.
- 이후 `write_stdin` 폴링은 `BashOutput`이고, 결과에 `<task_id>`·`<status>`를 붙인다.

### 6.4 서브에이전트

- 자식 rollout은 `session_meta.source.subagent.thread_spawn.parent_thread_id`로 찾는다(손자까지 재귀).
  `<세션>/subagents/agent-<thread_id>.jsonl`로 쓰고 전 레코드에 `isSidechain: true`를 붙인다.
- 자식 기록 앞부분에는 부모 대화 사본이 붙을 수 있다(`fork_turns`). `session_meta`의
  `subagent_history_start_ordinal` 앞 줄은 사본이므로 버린다.
- `source.subagent.other == "guardian"`(자동 승인 검토기)은 위임한 일이 아니므로 넣지 않는다.
  Claude의 자동 모드 판정기도 기록에 남지 않는다.
- 부모가 지시한 시각은 `spawn_agent`, 자식이 끝난 시각은 `SubAgentActivity completed` 항목이다.
  끝난 시각에 `queue-operation` 완료 알림을 써서 대기 증거(§94 E5)가 생기게 한다.
- **암호화 본문의 단어 수.** 다중 에이전트 v2는 지시문(`spawn_agent.message`, 자식의 `NEW_TASK`)과
  중간 메시지(`send_message`)를 암호화해 저장한다. 최종 답(`FINAL_ANSWER`)과 자식 자신의 답은 평문이다.
  암호화 본문의 단어 수 = (그 응답의 출력 토큰 − 생각 토큰) × r − 그 응답의 평문 단어 수.
  r = 같은 세션(부모+자식)에서 암호화가 없는 응답들의 평문 단어 합 ÷ (출력 토큰 − 생각 토큰) 합.
  본문 자리에는 서로 겹치지 않는 자리표시 단어를 그 수만큼 넣는다(복붙 판정에 안 걸리게).
  자식이 부모에게 보낸 `send_message`는 자식의 보고문(assistant 텍스트, §68)으로 쓴다.
  부모가 자식에게 보낸 메시지는 자식이 받은 순서대로 짝짓는다.
  암호화가 있었으면 번역 결과의 `notes`에 건수와 비율 r을 적는다.

### 6.5 다른 에이전트에서 가져온 세션 사본 (구현 중 발견)

Codex는 Claude Code 세션을 가져와(`~/.codex/external_agent_session_imports.json`) 자기 rollout으로
다시 쓴다. 이 PC에서 확인한 사실:

- 메인 rollout 297개 중 261개(sessions)와 보관함 23개, 합계 284개가 가져온 사본이다.
- 그중 182개는 모든 줄의 시각이 가져온 순간 하나로 다시 찍혀 있다. 원래 시각은 턴 시작
  시각(`task_started.started_at`)에만 남는다.
- 가져온 뒤 Codex에서 새 지시를 이어 한 세션은 0개였다.

규칙: 등록부의 `imported_at`(+2초) 안에 쓰인 줄은 사본으로 보고 버린다. 남는 사람 지시가
없으면 측정에서 뺀다(`excluded`, 사유: 다른 에이전트 세션 사본). 그 일은 원래 에이전트 쪽에서
이미 잰다. 따라서 Codex 쪽에 넣으면 같은 일을 두 번 센다. 가져온 뒤 이어 한 부분이 있으면
그 부분만 잰다.

### 6.6 보관함

Codex 보관함(`~/.codex/archived_sessions/`)의 rollout도 측정 대상이고, 자식 찾기도 두 폴더를 함께 본다.

### 6.7 압축된 옛 기록 (2026-10-16 발견)

Codex 앱은 2026-10-15 21:45 ~ 10-16 00:55에 기록 이전(`legacy_to_paginated_v1`)을 돌렸다. 이때 옛 rollout
249개를 zstd로 압축했다(`rollout-*.jsonl.zst`). 압축하지 않은 123개와 합치면 372개이고, 스레드 목록
(`state_5.sqlite`의 `threads`) 372개와 같다. 잃어버린 기록은 없다.
번역기는 두 꼴을 다 읽는다. 푸는 수단은 설치하지 않고 있는 것만 쓴다:
`zstandard` 패키지 → Python 3.14 `compression.zstd` → Node 22.15+ `zlib.zstdDecompressSync`.

## 7. OpenCode (v2 세션, 2.0.29)

입력은 공식 내보내기(`opencode session export <id>`의 JSON) 또는 `opencode:<세션ID>`이다.
후자는 `~/.local/share/opencode/opencode.db`를 읽기 전용으로 열어 같은 내용을 읽는다.
2.x는 옛 세션도 v2 표(`session_v2`·`session_message`)로 옮겨 두었다. 옮겨지지 않은 1.x 세션
(옛 표 `session`·`message`·`part`)은 같은 모양으로 맞춘 뒤 같은 규칙을 쓴다.

### 7.1 레코드 대응

| OpenCode 기록 | Claude 기록 |
|---|---|
| `user` | 사람 지시 |
| `assistant` | 응답 1건(`message.id`), `tokens.reasoning` → 생각 토큰 |
| `assistant.content`의 `reasoning` / `text` | `thinking` / `text` 블록 |
| `assistant.content`의 `tool` | `time.created`에 `tool_use`, `time.completed`에 `tool_result` (`status: error`면 `is_error`) |
| `assistant.error.type == "aborted"` | user 텍스트 `[Request interrupted by user]` |
| `assistant.error`(그 외) | `isApiErrorMessage` (측정 제외) |
| `synthetic` + `metadata.source == "shell"` | user 텍스트 `<task-notification>`(배경 셸 종료 알림) |
| `synthetic`(그 외), `system` | `isMeta: true` |
| `compaction` | user `isCompactSummary` |
| `idle` | `system/turn_duration` (턴 시작 지시 → idle) |
| `model-switched` | 쓰지 않음 |

### 7.2 도구 대응

| OpenCode 도구 | Claude 도구 |
|---|---|
| `read`(파일) | `Read{file_path, offset, limit}` |
| `read`(폴더, 결과가 "Read directory"로 시작) / `list` | `LS` |
| `write` / `edit` / `multiedit` | `Write` / `Edit` / `MultiEdit` |
| `apply_patch`·`patch` | 패치 본문을 파싱해 Codex `FileChange`와 같게 |
| `shell`·`bash` | `Bash{command, run_in_background}`. 배경이면 결과 "Command running in background with ID: <shellID>" |
| `grep` / `glob` / `webfetch` / `websearch` | `Grep` / `Glob` / `WebFetch` / `WebSearch` |
| `todowrite`·`todoread` | `TodoWrite` |
| `task`·`subagent` | `Agent{prompt, description}` + `toolUseResult{agentId: 자식 세션ID, totalDurationMs}` |
| `question` / `skill` | `AskUserQuestion` / `Skill` |
| 그 밖(MCP 등) | 이름 그대로 |

자식 세션(`parent_id`)은 재귀로 찾아 `subagents/`에 쓴다. 지시문은 평문이다.
export 파일로 넣을 때는 같은 폴더의 `<자식 세션ID>.json`을 먼저 보고, 없으면 DB를 본다.
둘 다 없으면 번역 결과의 `notes`에 "자식 세션을 찾지 못함"을 적는다.

### 7.3 구현 중 정한 세부 규칙

- **배경 셸의 실제 종료 시각.** OpenCode는 배경 셸 종료 알림(`synthetic`)을 AI가 바쁘면 늦게 배달한다.
  Claude는 종료 순간을 대기열 기록(`queue-operation`)으로 남긴다. OpenCode 셸 출력 파일
  (`~/.local/share/opencode/shell/<프로젝트>/<shellID>.out`)의 마지막 기록 시각이 띄운 시각과 알림
  시각 사이에 있으면, 그 시각에 대기열 완료 알림을 쓴다. 파일이 없으면 배달 시각만 쓴다.
  시험 세션: 25초짜리 명령이 배달 시각 기준 56.4초로 잡히던 것이 25.6초로 맞았다.
- **끝나지 않은 도구 호출**(`status`가 pending·running이고 완료 시각 없음)은 `tool_result`를 쓰지 않는다.
  Claude 기록과 같다.
- 1.x에서 2.x로 옮겨진 옛 세션의 도구에는 `ran` 시각이 없다. 호출은 `created`, 결과는 `completed` 시각을 쓴다.
- 대화 텍스트 조각에는 시각이 없다. 뒤에 오는 조각 중 가장 이른 시각, 없으면 응답 완료 시각을 쓴다.
- 이 PC의 OpenCode 세션에는 시각이 한 순간으로 다시 찍힌 사본이 없다(메시지 5개 이상 세션 192개 중 0개).

## 8. 검증

1. 최신 버전으로 같은 시험 과제(읽기 전체·범위, 검색, 편집, 새 파일, 삭제, 실행 성공·실패,
   배경 실행, 서브에이전트, 웹 검색, 계획 도구, 2턴)를 Codex·OpenCode에서 각각 실행해 실제 기록을 만든다.
2. 변환 결과를 기존 측정기에 넣어 항목별 값이 기대와 맞는지 본다:
   읽기 등급 분해, 쓰기 순계, 검색 건수, 실행 4토막(실패 판정 포함), 배경 대기, 서브에이전트 몫,
   전략 생각 지점, 지시 턴 수, 분모의 AI 시간·턴 시간.
3. 채널 결산(§59)의 미계상 채널과 §38 미등록 쓰기 경보가 0인지 본다.
4. 이 PC의 실제 Codex·OpenCode 세션 전체를 일괄 변환·측정해 오류 0건을 확인한다.
5. 형식 판별·대응 규칙은 개인 정보를 뺀 작은 손 작성 기록으로 단위 시험(`test_session_translator.py`)을 둔다.

### 8.1 결과 (2026-10-15)

**시험 세션.** 같은 11단계 과제를 Codex 0.162.1·OpenCode 2.0.29로 2턴씩 실행했다. 변환 뒤 측정기에서 확인한 값:

| 항목 | Codex | OpenCode |
|---|---|---|
| 사람 지시 | 2 | 2 |
| 범위 읽기 | 셸 명령(`Get-Content … \| Select-Object -Skip 39`) → 셸 읽기 경로 | `Read{offset: 40, limit: 21}` |
| 편집·새 파일·삭제 | `MultiEdit`·`Write`·`Remove-Item` 실행 | `Edit`·`Write`·`rm` 실행 |
| 실행 실패 판정 | `foobarcmd` 오류 결과(`is_error`) | `del`·`foobarcmd` 실패(명령 없음) |
| 배경 실행 | 1건, 25.1초(실제 종료 항목 시각) | 1건, 25.6초(셸 출력 파일 시각) |
| 서브에이전트 | 1개(지시문 암호화 → 35단어로 환산) | 1개(평문 지시) |
| 전략 생각 지점 | 1(서브) — 메인 첫 응답의 생각 토큰이 0 | 4 |
| 턴 시간 | 128.7초·13.9초 | 132.9초·13.4초 |
| 미계상 채널 경보·§38 경보 | 없음 | 없음 |

**이 PC 전 세션.** Codex 297개(sessions)와 OpenCode 402개(v2 371 + 옮겨지지 않은 1.x 31)를 변환·측정했다.

- 측정 오류: 0건.
- 미계상 채널 경보: 0건. §38 경보: 0건.
- 변환 누락: 원본 도구 호출보다 변환된 호출이 적은 세션 0개. 어느 호출에도 붙지 않은 Codex 항목 0개.

### 8.2 번역기·측정기 분리 뒤 재검증 (2026-10-16)

측정기 코드는 2026-10-15 이전 커밋(`5c2f069`)과 차이가 없다. 번역기로 전 세션을 폴더에 쓰고, 그 폴더를
기존 전 세션 리포트(`record_actions_code_api_all_sessions.py <폴더>`)에 그대로 넣었다.

- Codex: 번역 64세션, 다른 에이전트 세션 사본 제외 287, 실패 0. 측정 14세션, 초소형 제외 47,
  `codex exec` 헤드리스 제외 3. 사람 시간 합 10,360분, 에이전트 시간 합 810분.
  10-15의 통합 방식 결과와 측정 세션 수·합계가 같다.
  달라진 두 수의 이유: 헤드리스 제외 5 → 3은 시험 세션을 지웠기 때문이다. 사본 284 → 287은
  Codex가 10-16에 Claude 세션 3개를 더 가져왔기 때문이다.
- OpenCode: 번역 389세션, 빈 세션 제외 12, 실패 0. 측정 158세션, 초소형 제외 231. 10-15의 159세션과의
  차이 1은 지운 시험 세션이다.

**측정기 쪽에서 발견한 것(이 변환과 별개).** 실행 실패 정규식(`_EXEC_HARD_FAIL_RE`)은 영어 오류문만 안다.
Windows PowerShell의 한국어 오류("… 용어가 cmdlet, 함수, 스크립트 파일 또는 실행할 수 있는 프로그램
이름으로 인식되지 않습니다")는 실패로 보지 않는다. 이 PC의 Claude 세션에도 똑같이 적용되는 규칙이라
여기서는 고치지 않았다.

### 8.3 리뷰 반영 뒤 재검증 — 워커 방식 (2026-10-16)

워커가 부르는 방식 그대로 돌렸다: `list_sessions` → 세션마다 `translate_session`(작업 폴더 지정) →
그 폴더를 기존 전 세션 리포트의 `collect()`에 넣기 → 블록 끝에서 삭제.

- 결과는 8.2와 같다. Codex는 측정 14세션, 사람 10,360분, 에이전트 810분이다. OpenCode는 측정 158세션, 사람 20,800분, 에이전트 4,810분이다.
- 디스크에 동시에 있던 번역 파일은 한 세션 몫뿐이었다. 가장 큰 세션도 Codex 4.73MB, OpenCode 1.66MB였다.
  끝난 뒤 작업 폴더는 비어 있었다.
- "최근 30일" 걸러내기:
  - Codex 250 / 351. 파일 수정 시각을 쓰던 때는 321이었다. 압축·가져오기로 파일만 다시 쓰인 세션이 빠졌다.
  - OpenCode 33 / 401.

## 9. 파일

- `session-translator/codex_translator.py` — Codex rollout → Claude 기록
- `session-translator/opencode_translator.py` — OpenCode v2·1.x → Claude 기록
- `session-translator/session_translator.py` — 형식 판별, 압축 기록 읽기, 공통 기록 작성기, 위치 찾기,
  `list_sessions()`·`translate_session()`(워커용), `convert()`(아래 단계), 점검용 CLI
- `session-translator/test_session_translator.py` — 단위 시험
- `session-translator/README.md` — 사용법

측정기 쪽 파일은 하나도 바꾸지 않는다.

## 10. 사용법

워커 코드 안에서 함수로 부른다. 자세한 것은 [README.md](README.md).

```python
for s in list_sessions("opencode", since=time.time() - 30 * 86400, seen=ledger):
    with translate_session(s["src"], work_dir=state_dir / "translate") as t:
        if t.main:
            r = measure(t.main, subagent_paths=t.subagents)
    ledger[s["src"]] = s["updated_at"]
```

## 11. 안전 규칙 (2026-10-16 리뷰 반영)

리뷰 지적: 알고리즘은 그대로 써도 되지만, 바깥 껍데기가 안전 규칙을 어겼다. 경로 찾기, 한꺼번에 변환, 임시 폴더,
매번 전체 재처리, 결과 모양이 문제였다. 예전에 세션 전체를 복사했다가 240GB가 쌓여 시스템 임시 폴더가 찼고,
opencode가 켜지지 않은 사고가 있었다. 그 사고가 다시 나지 않게 다음을 코드로 강제한다.
(리뷰가 말한 워커 설계 문서는 이 PC에 없어서 리뷰에 적힌 규칙대로 구현했다.)

| 번호 | 지적 | 고친 것 |
|---|---|---|
| 1 | DB 주소를 `"file:" + 경로`로 이어 붙여 `?`·`#`에서 잘리고 Windows에서 슬래시가 모자람 | `ro_uri()` = `Path.resolve().as_uri() + "?mode=ro"`. `?`→`%3F`, `#`→`%23`, `file:///C:/...` |
| 2 | OpenCode DB 위치가 고정됨 | `find_opencode_db()`: 인자 → `OPENCODE_DB` → `XDG_DATA_HOME` → 기본. `find_codex_home()`: 인자 → `CODEX_HOME` → `~/.codex`. 사람이 정한 위치(인자·환경변수)가 없으면 바로 오류. 링크는 실제 위치로 따라감 |
| 3 | 전 세션을 폴더에 쌓음 | `convert_all()`·`--all` 삭제. `translate_session()`이 한 세션만 번역하고 `with` 블록 끝에서 지움(예외가 나도) |
| 4 | 작업 폴더를 안 주면 시스템 tmp에 씀 | `tempfile` 사용 삭제. 작업 폴더가 필수 인자(없으면 `ValueError`). 워커의 `state_dir` 아래를 넘긴다 |
| 5 | 매번 전 세션을 다시 봄 | `list_sessions(since=, seen=)`. `updated_at`은 실제 변경 시각이다. Codex는 스레드 목록 → 마지막 사건 시각, OpenCode는 세션 갱신 시각. 파일 수정 시각은 쓰지 않는다 |
| 6 | 결과가 파일 1개 + 경로 목록이라 계산기가 원하는 폴더 모양과 다름 | `translate_session()`이 세션 전용 폴더(`t.folder`)를 내줌. 그 안에는 이 세션의 메인·서브 기록만 계산기 자리대로 있다. `collect(t.folder)`나 `measure(t.main, subagent_paths=t.subagents)`로 바로 잰다 |

`OPENCODE_DB`는 이 번역기가 정한 이름이다. OpenCode 자체가 읽는 환경변수는 아니다.
