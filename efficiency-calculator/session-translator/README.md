# Session Translator

Codex·OpenCode 세션 기록을 **Claude Code 세션과 같은 모양의 jsonl 파일**로 바꿔 주는 번역기입니다.
번역한 파일은 기존 효율 계산기(`../session-api`)에 Claude 세션처럼 그대로 넣어 잽니다.
계산기는 이 번역기를 모르며, 계산기 코드는 바꾸지 않았습니다.

```
Codex·OpenCode 세션 → Session Translator → Claude 세션 모양 jsonl 폴더 → 기존 계산기(무변경) → 효율
```

대응 규칙과 검증 결과는 [DESIGN.md](DESIGN.md)에 있습니다.

## 받는 입력

| 입력 | 예 |
|---|---|
| Codex 기록 파일 | `~/.codex/sessions/2026/10/15/rollout-….jsonl` |
| Codex 압축 기록 파일 | `rollout-….jsonl.zst` (Codex 앱이 옛 기록을 압축해 둔 것) |
| OpenCode 내보내기 파일 | `opencode session export <세션ID> > ses_….json`로 만든 파일 |
| OpenCode DB의 세션 | `opencode:<세션ID>` (`~/.local/share/opencode/opencode.db`를 읽기 전용으로 엽니다) |

기준 버전은 Codex CLI 0.162 계열과 OpenCode 2.0.29입니다.

## 명령줄로 쓰기

명령은 `efficiency-calculator` 폴더에서 실행합니다.

### 세션 1개

```bash
python session-translator/session_translator.py <입력> --out conv
python session-api/record_actions_code_api.py conv/<세션>.jsonl
```

첫 명령은 번역 결과(파일 경로, 주석)를 JSON으로 화면에 보여 줍니다.

### 이 PC의 세션 전체

```bash
python session-translator/session_translator.py --all codex    --out conv-codex
python session-translator/session_translator.py --all opencode --out conv-opencode
python session-api/record_actions_code_api_all_sessions.py conv-codex    --out codex.md
python session-api/record_actions_code_api_all_sessions.py conv-opencode --out opencode.md
```

- `--root`로 기본 위치를 바꿀 수 있습니다. Codex는 홈 폴더(기본 `~/.codex`)를 받고, OpenCode는 DB 파일 경로를 받습니다.
- Codex는 `sessions`와 보관함 `archived_sessions`를 함께 읽습니다.
- 번역이 끝나면 "변환 64세션, 제외 다른 에이전트 세션 사본 287, 실패 0" 같은 한 줄 요약이 나옵니다.

## 파이썬에서 불러 쓰기

폴더 이름에 `-`가 있어 패키지로는 불러올 수 없습니다. 폴더 경로를 `sys.path`에 넣고 불러옵니다.

```python
import sys
sys.path.insert(0, r"C:\Users\joung\avatar-efficiency\efficiency-calculator\session-translator")
from session_translator import convert, convert_all, detect_format
```

### `convert(src, out_dir=None)` — 세션 1개 번역

`src`에는 위 표의 입력 하나를 넣습니다. `out_dir`는 번역 파일을 쓸 폴더입니다. 비우면 임시 폴더를
만들어 `tmpdir`로 알려 주며, 다 쓴 뒤 지우는 것은 호출한 쪽이 합니다.

돌려주는 값:

```python
{
  "format":    "codex" | "opencode" | "claude",
  "main":      "<out_dir>/<세션>.jsonl",          # 측정에서 빠지는 세션이면 None
  "subagents": ["<out_dir>/<세션>/subagents/agent-<id>.jsonl", ...],
  "notes":     ["Codex 암호화 에이전트 메시지 2건 — ... 환산", ...],
  "name":      "<원본 파일 이름 또는 세션ID>",
  "tmpdir":    "<임시 폴더>" | None,
  "excluded":  "다른 에이전트(Claude Code 등)에서 가져온 세션 사본 — ..." | "빈 세션(기록 0건)",  # 빠질 때만
}
```

Claude 기록을 넣으면 번역하지 않고 `main`에 원본 경로를 그대로 돌려줍니다. 원본은 건드리지 않습니다.

계산기에 넣을 때는 `main`과 `subagents`를 그대로 넘깁니다.

```python
r = convert(src, out_dir="conv")
if r["main"]:
    from record_actions_code_api import measure      # ../session-api
    result = measure(r["main"], subagent_paths=r["subagents"])
```

선택 인자로 `opencode_db=`(DB 경로)와 `codex_root=`(Codex의 **`sessions` 폴더** 경로)를 줄 수 있습니다.
기본 위치를 쓰면 줄 필요가 없습니다.

### `convert_all(agent, out_dir, root=None)` — 이 PC 세션 전체 번역

`agent`는 `"codex"` 또는 `"opencode"`입니다. 세션마다 `out_dir`에 파일을 쓰고 아래 요약을 돌려줍니다.
같은 내용이 `out_dir/_translator_summary.json`에도 저장됩니다.

```python
{
  "agent": "codex", "root": None,
  "converted": [{"src": "...", "main": "...jsonl", "subagents": 1, "notes": [...]}, ...],
  "excluded":  [{"src": "...", "reason": "..."}, ...],
  "errors":    [{"src": "...", "error": "..."}, ...],
}
```

`out_dir`는 기존 전 세션 리포트(`record_actions_code_api_all_sessions.py <out_dir>`)에 그대로 넣습니다.

### `detect_format(src)` — 형식만 확인

`"codex"`, `"opencode"`, `"claude"` 중 하나를 돌려줍니다. 판별하지 못하면 `"claude"`입니다.

## 알아 둘 점

- **측정에서 빼는 세션.**
  - Codex가 Claude Code 세션을 가져와 다시 저장한 사본은 쓰지 않습니다. 넣으면 Claude 쪽에서 이미 잰 일을 두 번 셉니다.
  - 기록이 하나도 없는 빈 세션도 쓰지 않습니다.
  - 둘 다 요약의 `excluded`에 사유가 남습니다.
- **추정이 들어가는 곳은 한 군데입니다.** Codex 다중 에이전트 v2는 에이전트 사이 메시지를 암호화해 저장합니다.
  그 길이는 토큰 수에 같은 세션에서 잰 단어/토큰 비율을 곱해 단어 수로 바꿉니다.
  그런 세션은 `notes`에 건수와 비율이 적힙니다.
- **파일 수정 시각.** 번역 파일의 수정 시각은 원본 기록의 마지막 시각으로 맞춥니다.
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

손으로 만든 작은 기록으로 대응 규칙을 확인합니다. 번역한 파일을 기존 계산기에 넣는 두 단계 시험도 함께 돌립니다.
