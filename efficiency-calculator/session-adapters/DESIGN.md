# 세션 변환기 설계 — Codex·OpenCode 세션을 record-actions 측정기로 재기 (§96)

작성일: 2026-10-15
대상 버전: Codex CLI 0.162.1 (rollout jsonl), OpenCode 2.0.29 (v2 세션 저장소·`session export`)

## 1. 목적

`session-api/record_actions_code_api.py`(LLM 0회 측정기)는 Claude Code 세션 기록만 읽는다.
이 문서는 Codex·OpenCode 세션도 **같은 측정기, 같은 규칙, 같은 요율**로 재는 방법을 정한다.

## 2. 방식 — 측정기를 고치지 않고 기록을 바꾼다

Codex·OpenCode 기록을 **Claude Code 기록 모양의 jsonl**로 변환한 뒤, 기존 측정기에 그대로 넣는다.

- 측정 규칙은 한 곳(기존 측정기)에만 있다. 에이전트별로 규칙이 갈라지지 않는다.
- 변환기는 "이 에이전트의 이 기록은 Claude 기록의 무엇에 해당하는가"만 정한다.
- 서브에이전트 기록은 Claude와 같은 자리(`<세션>/subagents/agent-<id>.jsonl`)에 둔다.
  그래서 `find_subagent_files`·`measure_agent_actual`의 자동 탐색이 그대로 동작한다.

`measure()`는 입력을 보고 형식을 판별한다. Claude 기록이면 종전과 같다. Codex rollout 파일,
OpenCode export JSON, `opencode:<세션ID>` 지정이면 임시 폴더에 변환한 뒤 잰다.

## 3. "100% 변환"의 정의

측정기가 Claude 기록에서 읽는 모든 입력(아래 4장의 계약)에 대해, 다음 중 하나가 성립해야 한다.

1. Codex·OpenCode 기록에 같은 뜻의 값이 있어 그대로 옮긴다.
2. 그 에이전트에 해당 기능이 아예 없어서, 옮길 값이 0이다. (예: 해당 기능을 쓰지 않은 세션)

이 정의를 벗어나는 항목은 한 가지뿐이다. Codex 다중 에이전트 v2가 **암호화해서 저장하는
에이전트 사이 메시지 본문**이다. 본문은 어디에도 평문으로 남지 않는다. 대신 그 메시지를 만든
응답의 출력 토큰 수는 정확히 남는다. 그래서 단어 수를 "토큰 수 × 같은 세션의 평문 응답에서 잰
단어/토큰 비율"로 환산한다(6.4절). 이 환산은 측정 결과 `notes`에 건수와 함께 드러낸다.

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

**셀 결과 규칙.** 각 개별 호출의 결과 글은 그 항목에 기록된 출력이다. 단, 셀이 그 출력을
화면에 내지 않았으면(셀 출력에 그 글이 없으면) AI가 보지 않은 것이므로 결과 글을 비운다.
셀 출력 중 어느 개별 호출에도 속하지 않는 글(계획 기록, 도구 목록 조회 등 자바스크립트 자체
출력)은 이름 `js_output`인 조회형 호출 1건의 결과로 둔다. 측정기는 이것을 다른 미등록 조회
도구와 같게 다룬다(50단어 이상이면 읽기). 셀의 자바스크립트 접착 코드는 사람 작업으로 세지
않는다. 사람은 명령을 직접 실행하지 접착 코드를 쓰지 않기 때문이다(`TodoWrite`가 0인 것과 같다).

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

## 8. 검증

1. 최신 버전으로 같은 시험 과제(읽기 전체·범위, 검색, 편집, 새 파일, 삭제, 실행 성공·실패,
   배경 실행, 서브에이전트, 웹 검색, 계획 도구, 2턴)를 Codex·OpenCode에서 각각 실행해 실제 기록을 만든다.
2. 변환 결과를 기존 측정기에 넣어 항목별 값이 기대와 맞는지 본다:
   읽기 등급 분해, 쓰기 순계, 검색 건수, 실행 4토막(실패 판정 포함), 배경 대기, 서브에이전트 몫,
   전략 생각 지점, 지시 턴 수, 분모의 AI 시간·턴 시간.
3. 채널 결산(§59)의 미계상 채널과 §38 미등록 쓰기 경보가 0인지 본다.
4. 이 PC의 실제 Codex·OpenCode 세션 전체를 일괄 변환·측정해 오류 0건을 확인한다.
5. 형식 판별·대응 규칙은 개인 정보를 뺀 작은 손 작성 기록으로 단위 시험(`test_session_adapters.py`)을 둔다.

## 9. 파일

- `session-adapters/codex_adapter.py` — Codex rollout → Claude 기록
- `session-adapters/opencode_adapter.py` — OpenCode v2·1.x → Claude 기록
- `session-adapters/session_adapters.py` — 형식 판별, 공통 기록 작성기, `convert()`
- `session-adapters/test_session_adapters.py` — 단위 시험
- `session-api/record_actions_code_api.py` — `measure()` 입구에서 변환 호출
