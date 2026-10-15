# -*- coding: utf-8 -*-
"""Codex·OpenCode 세션 → Claude Code 기록 모양 jsonl 변환 (§96, DESIGN.md).

측정 규칙은 기존 측정기(record_actions_code_api) 한 곳에만 둔다. 이 모듈은
"다른 에이전트의 이 기록이 Claude 기록의 무엇에 해당하는가"만 정한다.

사용:
    from session_adapters import detect_format, convert
    fmt = detect_format("rollout-....jsonl")      # "claude" | "codex" | "opencode"
    out = convert("rollout-....jsonl")            # 임시 폴더에 변환
    out["main"], out["subagents"], out["notes"]   # 측정기에 넣을 경로·주석
    shutil.rmtree(out["tmpdir"])                  # 호출자가 지운다

CLI:
    python session_adapters.py <입력> [--out 폴더]
    입력 = Codex rollout jsonl | OpenCode export JSON | opencode:<세션ID>
"""
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

OPENCODE_PREFIX = "opencode:"


# ---------------------------------------------------------------- 형식 판별

def detect_format(src):
    """입력 → "claude" | "codex" | "opencode". 판별 못 하면 "claude"(종전 동작)."""
    s = str(src)
    if s.startswith(OPENCODE_PREFIX):
        return "opencode"
    try:
        with open(s, encoding="utf-8", errors="replace") as fh:
            line = fh.readline()
            while line and not line.strip():
                line = fh.readline()
    except OSError:
        return "claude"
    first = line.lstrip()
    if first.startswith("{"):
        try:
            rec = json.loads(first)
        except ValueError:
            rec = None
        if isinstance(rec, dict):
            if rec.get("type") == "session_meta" and "payload" in rec:
                return "codex"
            if "info" in rec and "messages" in rec:
                return "opencode"      # 한 줄로 저장된 OpenCode export
            return "claude"
        # 한 줄 JSON이 아님 — OpenCode export(들여쓴 JSON 문서)인지 본다
        try:
            with open(s, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            return "claude"
        if isinstance(doc, dict) and "info" in doc and "messages" in doc:
            return "opencode"
    return "claude"


# ---------------------------------------------------------------- 공통 도구

def iso(t):
    """epoch(초 또는 밀리초) 또는 ISO 문자열 → ISO 8601 UTC 밀리초."""
    if t is None:
        return None
    if isinstance(t, str):
        try:
            t = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    t = float(t)
    if t > 1e11:          # 밀리초
        t /= 1000.0
    return (datetime.fromtimestamp(t, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")


def epoch(t):
    """ISO 문자열·epoch(초/밀리초) → epoch 초."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return t / 1000.0 if t > 1e11 else float(t)
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def words(text):
    return len(str(text or "").split())


def json_text_words(v):
    """JSON 값 속 문자열 잎의 단어 합 (키 이름 제외)."""
    if isinstance(v, str):
        return words(v)
    if isinstance(v, dict):
        return sum(json_text_words(x) for x in v.values())
    if isinstance(v, list):
        return sum(json_text_words(x) for x in v)
    return 0


class Placeholder:
    """암호화 본문 자리표시 단어 — 세션 안에서 서로 겹치지 않는다(복붙 판정 방지)."""

    def __init__(self):
        self.n = 0

    def make(self, count):
        out = []
        for _ in range(max(0, int(round(count)))):
            self.n += 1
            out.append(f"enc{self.n:06d}")
        return " ".join(out)


# ---------------------------------------------------------------- 패치 해석

def _clean(s):
    return str(s or "").replace("\r\n", "\n").replace("\r", "")


def hunks_from_unified_diff(diff):
    """unified diff 본문 → [(old, new)] 덩어리별 (문맥+지운 줄, 문맥+더한 줄)."""
    out = []
    old, new = [], []
    started = False
    for line in _clean(diff).rstrip("\n").split("\n"):
        if line.startswith("@@"):
            if started and (old or new):
                out.append(("\n".join(old), "\n".join(new)))
            old, new = [], []
            started = True
            continue
        if line.startswith(("--- ", "+++ ", "Index:", "====", "diff --git",
                            "index ", "new file mode", "deleted file mode")):
            continue
        if not started:
            continue
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
        elif line.startswith("\\"):
            continue
        else:
            ctx = line[1:] if line.startswith(" ") else line
            old.append(ctx)
            new.append(ctx)
    if started and (old or new):
        out.append(("\n".join(old), "\n".join(new)))
    return out


def parse_apply_patch(text):
    """`*** Begin Patch` 형식 → [{"op": add|update|delete, "path", "content"|"hunks", "move_to"}]."""
    ops = []
    cur = None
    old, new = [], []

    def flush_hunk():
        nonlocal old, new
        if cur is not None and cur["op"] == "update" and (old or new):
            cur["hunks"].append(("\n".join(old), "\n".join(new)))
        old, new = [], []

    for line in _clean(text).rstrip("\n").split("\n"):
        m = re.match(r"\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if m:
            flush_hunk()
            kind = m.group(1).lower()
            cur = {"op": kind, "path": m.group(2).strip()}
            if kind == "add":
                cur["lines"] = []
            elif kind == "update":
                cur["hunks"] = []
            ops.append(cur)
            continue
        if line.startswith("*** Move to:") and cur is not None:
            cur["move_to"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith(("*** Begin Patch", "*** End Patch",
                            "*** End of File")):
            continue
        if cur is None:
            continue
        if cur["op"] == "add":
            if line.startswith("+"):
                cur["lines"].append(line[1:])
            continue
        if cur["op"] != "update":
            continue
        if line.startswith("@@"):
            flush_hunk()
            continue
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
        else:
            ctx = line[1:] if line.startswith(" ") else line
            old.append(ctx)
            new.append(ctx)
    flush_hunk()
    for op in ops:
        if op["op"] == "add":
            op["content"] = "\n".join(op.pop("lines"))
    return ops


def file_ops_to_tools(ops):
    """파일 변경 목록 → [(Claude 도구명, 입력)] (DESIGN 6.2: update=MultiEdit,
    add=Write, delete=rm, move=mv)."""
    tools = []
    for op in ops:
        path = op["path"]
        if op["op"] == "add":
            tools.append(("Write", {"file_path": path,
                                    "content": _clean(op.get("content"))}))
        elif op["op"] == "delete":
            tools.append(("Bash", {"command": f'rm "{path}"'}))
        else:
            dest = op.get("move_to")
            if dest:
                tools.append(("Bash", {"command": f'mv "{path}" "{dest}"'}))
            hunks = op.get("hunks") or []
            if hunks:
                tools.append(("MultiEdit", {
                    "file_path": dest or path,
                    "edits": [{"old_string": o, "new_string": n}
                              for o, n in hunks]}))
    return tools


# ---------------------------------------------------------------- 기록 작성기

class ClaudeWriter:
    """Claude Code 기록 모양 레코드를 모았다가 시각 순으로 쓴다."""

    def __init__(self, session_id, sidechain=False, entrypoint=None):
        self.session_id = session_id
        self.sidechain = sidechain
        self.entrypoint = entrypoint
        self.permission = None
        self.recs = []
        self._ns = uuid.uuid5(uuid.NAMESPACE_URL, f"adapter:{session_id}")

    def _base(self, t, rtype):
        rec = {"type": rtype, "timestamp": iso(t),
               "uuid": str(uuid.uuid5(self._ns, str(len(self.recs)))),
               "sessionId": self.session_id}
        if self.sidechain:
            rec["isSidechain"] = True
        return rec

    # 같은 시각이면 AI 호출 → 결과·알림 → 턴 시간 순 (도구 결과가 호출보다 앞서지 않게)
    _RANK = {"assistant": 0, "user": 1, "queue-operation": 1, "system": 2}

    def _add(self, t, rec):
        self.recs.append((epoch(t) or 0.0, self._RANK.get(rec["type"], 1),
                          len(self.recs), rec))
        return rec

    def user_text(self, t, text, meta=False, compact=False):
        rec = self._base(t, "user")
        rec["message"] = {"role": "user",
                          "content": [{"type": "text", "text": text}]}
        if meta:
            rec["isMeta"] = True
        if compact:
            rec["isCompactSummary"] = True
        if self.permission:
            rec["permissionMode"] = self.permission
        if self.entrypoint and not self.sidechain:
            rec["entrypoint"] = self.entrypoint
        return self._add(t, rec)

    def assistant(self, t, msg_id, blocks, thinking_tokens=0, model=None,
                  api_error=False):
        rec = self._base(t, "assistant")
        msg = {"id": msg_id, "role": "assistant", "content": blocks}
        if model:
            msg["model"] = model
        if thinking_tokens:
            msg["usage"] = {"output_tokens_details":
                            {"thinking_tokens": int(thinking_tokens)}}
        rec["message"] = msg
        if api_error:
            rec["isApiErrorMessage"] = True
        return self._add(t, rec)

    def tool_result(self, t, tool_use_id, text, is_error=False,
                    tool_use_result=None, images=0):
        rec = self._base(t, "user")
        content = str(text or "")
        if images:
            content = ([{"type": "text", "text": content}]
                       + [{"type": "image", "source": {"type": "omitted"}}
                          for _ in range(images)])
        block = {"type": "tool_result", "tool_use_id": tool_use_id,
                 "content": content}
        if is_error:
            block["is_error"] = True
        rec["message"] = {"role": "user", "content": [block]}
        if tool_use_result is not None:
            rec["toolUseResult"] = tool_use_result
        if self.permission:
            rec["permissionMode"] = self.permission
        return self._add(t, rec)

    def turn_duration(self, t, duration_ms):
        if not duration_ms or duration_ms <= 0:
            return None
        rec = self._base(t, "system")
        rec["subtype"] = "turn_duration"
        rec["durationMs"] = int(duration_ms)
        return self._add(t, rec)

    def queue_notification(self, t, text):
        rec = self._base(t, "queue-operation")
        rec["operation"] = "enqueue"
        rec["content"] = text
        return self._add(t, rec)

    def write(self, path):
        self.recs.sort(key=lambda x: (x[0], x[1], x[2]))
        with open(path, "w", encoding="utf-8") as fh:
            for _t, _r, _i, rec in self.recs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return path


def task_notification(task_id, status, extra=""):
    """Claude 배경 작업 완료 알림 본문 (BackgroundExecTracker·WaitEvidence가 읽는 꼴)."""
    body = (f"<task-notification>\n<task-id>{task_id}</task-id>\n"
            f"<status>{status}</status>\n")
    if extra:
        body += f"<result>{extra}</result>\n"
    return body + "</task-notification>"


# ---------------------------------------------------------------- 변환 입구

def convert(src, out_dir=None, opencode_db=None, codex_root=None):
    """입력 → {"format", "main", "subagents", "notes", "tmpdir", "name"}.

    out_dir를 안 주면 임시 폴더를 만든다(호출자가 지운다). Claude 기록이면
    변환하지 않고 그대로 돌려준다(tmpdir=None)."""
    fmt = detect_format(src)
    if fmt == "claude":
        return {"format": "claude", "main": str(src), "subagents": None,
                "notes": [], "tmpdir": None, "name": Path(str(src)).name}
    tmpdir = None
    if out_dir is None:
        out_dir = tmpdir = tempfile.mkdtemp(prefix=f"{fmt}_adapt_")
    os.makedirs(out_dir, exist_ok=True)
    if fmt == "codex":
        from codex_adapter import convert_codex
        res = convert_codex(str(src), out_dir, sessions_root=codex_root)
    else:
        from opencode_adapter import convert_opencode
        res = convert_opencode(str(src), out_dir, db_path=opencode_db)
    res["format"] = fmt
    res["tmpdir"] = tmpdir
    return res


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = list(argv)
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    if not args:
        print("usage: python session_adapters.py <입력> [--out 폴더]",
              file=sys.stderr)
        return 2
    for src in args:
        res = convert(src, out_dir=out)
        print(json.dumps({k: v for k, v in res.items()},
                         ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
