# Session Translator

Codex·OpenCode 세션 기록을 **Claude Code 세션과 같은 모양의 jsonl 파일**로 바꿔 주는 번역기입니다.
번역한 파일은 기존 효율 계산기(`../session-api`)에 Claude 세션처럼 그대로 넣어 잽니다.
계산기는 이 번역기를 모르며, 계산기 코드는 바꾸지 않았습니다.

```
Codex·OpenCode 세션 → Session Translator → Claude 세션 모양 jsonl 폴더 → 기존 계산기(무변경) → 효율
```

대응 규칙과 검증 결과는 [DESIGN.md](DESIGN.md)에 있습니다.

## 안전 규칙 — 반드시 지킬 것

예전에 세션 전체를 한꺼번에 복사했다가 240GB가 쌓여 시스템 임시 폴더가 찼고, opencode가 아예 켜지지 않은 사고가 있었습니다.
그래서 이 번역기는 아래 규칙을 코드로 강제합니다.

1. **한 세션씩.** 번역 → 측정 → 삭제를 한 세션마다 끝냅니다. 전 세션을 한꺼번에 변환하는 기능은 없습니다.
2. **작업 폴더는 반드시 지정합니다.** 시스템 임시 폴더(`tempfile`)에는 쓰지 않습니다.
   워커의 `state_dir` 아래 폴더를 넘기세요. 지정하지 않으면 `ValueError`가 납니다.
3. **바뀐 세션만.** `since`(예: 최근 30일)와 `seen`(지난번에 처리한 세션과 그 시각)으로 다시 볼 세션을 줄입니다.
4. **경로는 찾아서, 바르게 엽니다.**
   - DB 주소는 `Path.as_uri()`로 만듭니다. 그래서 `?`, `#`, 공백이 들어간 경로와 Windows 경로(`file:///C:/...`)도 안전합니다.
   - DB는 읽기 전용으로 엽니다.
   - 위치를 찾는 순서는 아래 표와 같습니다.

| 대상 | 찾는 순서 |
|---|---|
| OpenCode DB | ① 인자 ② 환경변수 `OPENCODE_DB` ③ `XDG_DATA_HOME/opencode/opencode.db` ④ `~/.local/share/opencode/opencode.db` |
| Codex 홈 | ① 인자 ② 환경변수 `CODEX_HOME` ③ `~/.codex` |

①과 ②는 사람이 정한 위치입니다. 그 파일이나 폴더가 없으면 다음 후보로 넘어가지 않고 바로 오류를 냅니다. 엉뚱한 DB를 읽지 않게 하려는 것입니다.
심볼릭 링크는 실제 위치로 따라갑니다.
`OPENCODE_DB`는 이 번역기가 정한 이름입니다. OpenCode 자체가 읽는 환경변수가 아닙니다.

## 워커에서 부르기 (기본 사용법)

폴더 이름에 `-`가 있어 패키지로는 불러올 수 없습니다. 폴더 경로를 `sys.path`에 넣고 불러옵니다.

```python
import sys, time
sys.path.insert(0, r"...\efficiency-calculator\session-translator")
sys.path.insert(0, r"...\efficiency-calculator\session-api")       # 기존 계산기
from session_translator import list_sessions, translate_session
from record_actions_code_api import measure

work_dir = state_dir / "translate"                  # 시스템 임시 폴더가 아니라 워커의 state_dir 아래
seen = load_ledger()                                # {src: updated_at} — 지난번에 처리한 세션

for s in list_sessions("opencode", since=time.time() - 30 * 86400, seen=seen):
    with translate_session(s["src"], work_dir) as t:  # 이 세션만 번역
        if t.main:                                   # 사본·빈 세션이면 None (사유는 t.excluded)
            result = measure(t.main, subagent_paths=t.subagents)
            save(result, t.notes)
    # with 블록이 끝나면 t.folder는 지워져 있다 (블록 안에서 예외가 나도 지운다)
    seen[s["src"]] = s["updated_at"]
save_ledger(seen)
```

### `list_sessions(agent, root=None, since=None, seen=None)` — 대상 목록

번역은 하지 않고 목록만 돌려줍니다. 최신순입니다(가장 최근에 바뀐 세션이 먼저).

- `agent`: `"codex"` 또는 `"opencode"`
- `root`: Codex 홈 또는 OpenCode DB 경로입니다. 없으면 위 순서로 찾습니다.
- `since`: epoch 초입니다. 이 시각 뒤에 바뀐 세션만 남깁니다.
- `seen`: `{src: updated_at}`입니다. 기록된 시각 뒤로 바뀐 세션만 남깁니다.

돌려주는 값은 `[{"src": ..., "agent": ..., "updated_at": epoch 초}, ...]`입니다.

- `src`는 `translate_session()`에 그대로 넣습니다.
  - Codex: rollout 파일 경로(`.jsonl` 또는 `.jsonl.zst`)
  - OpenCode: `"opencode:<세션ID>"`
- `updated_at`은 세션이 실제로 바뀐 시각입니다. 파일 수정 시각이 아닙니다.
  - Codex: Codex 스레드 목록(`state_N.sqlite`의 `threads.updated_at_ms`) 시각입니다. 목록에 없으면 기록의 마지막 사건 시각입니다.
  - OpenCode: 세션 갱신 시각입니다.
  - 파일 수정 시각을 쓰지 않는 이유: Codex 앱은 옛 기록을 압축하거나 다른 에이전트 세션을 가져올 때 파일을 다시 씁니다. 그러면 바뀌지 않은 세션도 바뀐 것처럼 보입니다.
- Codex 서브에이전트 기록은 목록에 따로 나오지 않습니다. 부모 세션을 번역할 때 함께 들어갑니다.

### `translate_session(src, work_dir)` — 한 세션 번역 (with 블록)

`work_dir` 아래에 이 세션 전용 폴더를 만들어 번역합니다. `with` 블록이 끝나면 그 폴더를 지웁니다.

블록 안에서 받는 값 `t`의 내용:

| 속성 | 뜻 |
|---|---|
| `t.folder` | 계산기에 그대로 넣는 폴더입니다. 이 세션 파일만 들어 있습니다(`<세션>.jsonl`, `<세션>/subagents/agent-*.jsonl`). `record_actions_code_api_all_sessions.py <folder>`로도 잴 수 있습니다. |
| `t.main` | 메인 기록 경로입니다. 측정에서 빠지는 세션이면 `None`입니다. |
| `t.subagents` | 서브에이전트 기록 경로 목록입니다. |
| `t.notes` | 번역 주석입니다(예: 암호화 본문의 단어 수 환산). |
| `t.excluded` | 빠지는 사유입니다(다른 에이전트 세션 사본, 빈 세션). 빠지지 않으면 `None`입니다. |
| `t.src`, `t.format`, `t.name` | 원본, 형식(`codex`·`opencode`), 이름 |

선택 인자는 `opencode_db=`, `codex_home=`입니다. 주면 위치 찾기의 ① 인자로 쓰입니다.

### 그 밖의 함수

- `find_opencode_db(explicit=None)`, `find_codex_home(explicit=None)`: 위 순서로 실제 위치를 찾습니다. 못 찾으면 `FileNotFoundError`가 납니다.
- `ro_uri(path)`: SQLite 읽기 전용 URI를 만듭니다.
- `convert(src, out_dir)`: 아래 단계의 함수입니다. 지정한 폴더에 번역만 하고 지우지 않습니다. 보통은 `translate_session()`을 쓰세요.
- `detect_format(src)`: `"codex"`, `"opencode"`, `"claude"` 중 하나를 돌려줍니다.

## 받는 입력

| 입력 | 예 |
|---|---|
| Codex 기록 파일 | `~/.codex/sessions/2026/10/15/rollout-….jsonl` |
| Codex 압축 기록 파일 | `rollout-….jsonl.zst` (Codex 앱이 옛 기록을 압축해 둔 것) |
| OpenCode DB의 세션 | `opencode:<세션ID>` |
| OpenCode 내보내기 파일 | `opencode session export <세션ID>`로 만든 JSON |

Claude 기록을 넣으면 번역하지 않습니다. 원본 경로를 그대로 돌려주고 원본은 건드리지 않습니다.
기준 버전은 Codex CLI 0.162 계열과 OpenCode 2.0.29입니다.

## 명령줄 (점검용, 세션 1개)

```bash
python session-translator/session_translator.py <입력> --out <폴더>
```

세션 하나를 지정한 폴더에 번역하고 결과를 JSON으로 보여 줍니다. 점검용이라 지우지 않으니, 다 본 뒤 폴더를 직접 지우세요.
전 세션 일괄 변환 명령은 일부러 두지 않았습니다.

## 알아 둘 점

- **측정에서 빼는 세션.**
  - Codex가 Claude Code 세션을 가져와 다시 저장한 사본은 쓰지 않습니다. 넣으면 Claude 쪽에서 이미 잰 일을 두 번 셉니다.
  - 기록이 하나도 없는 빈 세션도 쓰지 않습니다.
  - 둘 다 사유가 `t.excluded`에 남습니다.
- **추정이 들어가는 곳은 한 군데입니다.** Codex 다중 에이전트 v2는 에이전트 사이 메시지를 암호화해 저장합니다.
  그 길이는 토큰 수에 같은 세션에서 잰 단어/토큰 비율을 곱해 단어 수로 바꿉니다. 그런 세션은 `t.notes`에 건수와 비율이 적힙니다.
- **파일 수정 시각.** 번역 파일의 수정 시각은 원본 기록의 마지막 사건 시각으로 맞춥니다.
  계산기는 최근 10분 안에 바뀐 파일을 진행 중인 세션으로 보고 빼기 때문입니다.
- **필요한 것.** 파이썬 표준 라이브러리만 씁니다. 압축 기록(`.jsonl.zst`)을 풀 때만 다음 중 하나가 필요합니다.
  - `zstandard` 패키지
  - Python 3.14
  - Node 22.15 이상

  이 PC는 Node 24로 풉니다.

## 시험

```bash
cd session-translator && python test_session_translator.py
```

시험하는 것:
- 대응 규칙
- 한 세션씩 번역 → 계산기 → 삭제(예외가 나도 삭제)
- 작업 폴더 필수
- `since`·`seen` 걸러내기
- 경로 찾기(특수문자 경로, 환경변수, 사람이 정한 위치가 없을 때 바로 오류)
