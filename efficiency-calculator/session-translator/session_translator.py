# -*- coding: utf-8 -*-
"""Codex·OpenCode 세션 → Claude Code 기록 모양 jsonl 변환 (§96, DESIGN.md).

번역기만 한다 — 측정기(session-api 등)는 이 모듈을 모르고, 바꾸지도 않는다.
이 모듈은 "다른 에이전트의 이 기록이 Claude 기록의 무엇에 해당하는가"만 정해
Claude Code 세션 모양 파일을 써 낸다. 그 파일을 기존 측정기에 그대로 넣는다.

사용:
    from session_translator import detect_format, convert, convert_all
    fmt = detect_format("rollout-....jsonl")      # "claude" | "codex" | "opencode"
    out = convert("rollout-....jsonl", out_dir="conv")
    out["main"], out["subagents"], out["notes"]   # 쓴 파일·주석
    convert_all("codex", "conv-codex")            # 이 PC 세션 전체

CLI:
    python session_translator.py <입력> --out 폴더
    python session_translator.py --all codex|opencode --out 폴더 [--root Codex홈|opencode.db]
    입력 = Codex rollout jsonl | OpenCode export JSON | opencode:<세션ID>

측정 (기존 측정기, 변경 없음):
    python ../session-api/record_actions_code_api.py 폴더/<세션>.jsonl
    python ../session-api/record_actions_code_api_all_sessions.py 폴더
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

_TEXT_CACHE = {}


def read_text(path):
    """기록 파일 → 글. Codex 앱은 옛 rollout을 zstd로 압축해 둔다(`.jsonl.zst`).

    푸는 수단(설치하지 않고 있는 것만 쓴다): zstandard 패키지 → Python 3.14
    compression.zstd → Node 22.15+ zlib.zstdDecompressSync."""
    p = str(path)
    if not p.endswith(".zst"):
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    key = (p, os.path.getmtime(p))
    if key in _TEXT_CACHE:
        return _TEXT_CACHE[key]
    with open(p, "rb") as fh:
        data = fh.read()
    raw = None
    try:
        import zstandard
        raw = zstandard.ZstdDecompressor().decompressobj().decompress(data)
    except ImportError:
        try:
            from compression import zstd
            raw = zstd.decompress(data)
        except ImportError:
            import shutil
            import subprocess
            node = shutil.which("node")
            if not node:
                raise RuntimeError("zstd 압축 기록을 풀 수단 없음 — zstandard 패키지 "
                                   "또는 Node 22.15+ 필요")
            raw = subprocess.run(
                [node, "-e", "process.stdout.write(require('zlib')"
                 ".zstdDecompressSync(require('fs').readFileSync(process.argv[1])))", p],
                capture_output=True, check=True).stdout
    text = raw.decode("utf-8", errors="replace")
    _TEXT_CACHE[key] = text
    return text


def first_line(path):
    """기록의 첫 비어 있지 않은 줄 (압축 기록도)."""
    if str(path).endswith(".zst"):
        for line in read_text(path).splitlines():
            if line.strip():
                return line
        return ""
    with open(str(path), encoding="utf-8", errors="replace") as fh:
        line = fh.readline()
        while line and not line.strip():
            line = fh.readline()
    return line


def session_stem(path):
    """출력 파일 이름의 몸통 — `.jsonl.zst`·`.jsonl`을 뗀다."""
    name = Path(str(path)).name
    for ext in (".jsonl.zst", ".jsonl", ".json"):
        if name.endswith(ext):
            return name[:-len(ext)]
    return Path(name).stem


def detect_format(src):
    """입력 → "claude" | "codex" | "opencode". 판별 못 하면 "claude"(종전 동작)."""
    s = str(src)
    if s.startswith(OPENCODE_PREFIX):
        return "opencode"
    try:
        line = first_line(s)
    except (OSError, RuntimeError):
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
        self._ns = uuid.uuid5(uuid.NAMESPACE_URL, f"translator:{session_id}")

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
        out_dir = tmpdir = tempfile.mkdtemp(prefix=f"{fmt}_translate_")
    os.makedirs(out_dir, exist_ok=True)
    if fmt == "codex":
        from codex_translator import convert_codex
        res = convert_codex(str(src), out_dir, sessions_root=codex_root)
    else:
        from opencode_translator import convert_opencode
        res = convert_opencode(str(src), out_dir, db_path=opencode_db)
    res["format"] = fmt
    res["tmpdir"] = tmpdir
    if res.get("main") and os.path.getsize(res["main"]) == 0:
        # 기록이 하나도 없는 세션 — 잴 것이 없다. 빈 파일을 남기면 수정 시각이
        # "지금"이라 측정기가 진행 중 세션으로 센다.
        os.unlink(res["main"])
        res.update(main=None, subagents=[], excluded="빈 세션(기록 0건)")
    for p in [res.get("main")] + list(res.get("subagents") or []):
        if p:
            _stamp(p)
    return res


def _stamp(path):
    """변환 파일의 수정 시각 = 그 기록의 마지막 사건 시각.

    측정기는 최근 10분 안에 바뀐 파일을 "진행 중"으로 보고 뺀다(§44). 방금
    쓴 변환 파일이 그 규칙에 걸리지 않고, 원본이 진행 중일 때만 걸리게 한다."""
    last = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                t = epoch(json.loads(line).get("timestamp"))
            except ValueError:
                continue
            if t and (last is None or t > last):
                last = t
    if last:
        os.utime(path, (last, last))


# ---------------------------------------------------------------- 전 세션 변환

def list_sources(agent, root=None):
    """이 PC의 측정 대상 원본 목록. agent = "codex" | "opencode".

    codex: Codex 홈(기본 ~/.codex)의 sessions·archived_sessions rollout 중 자식
           (서브에이전트) 아닌 것 — 자식은 부모 변환에 함께 들어간다.
    opencode: opencode.db의 최상위 세션(v2 + 옮겨지지 않은 1.x) → "opencode:<ID>"."""
    if agent == "codex":
        from codex_translator import DEFAULT_ROOT, rollout_files, _pl
        home = root or str(Path(DEFAULT_ROOT).parent)
        out = []
        for f in rollout_files(home):
            try:
                src = _pl(json.loads(first_line(f))).get("source")
            except (OSError, ValueError, RuntimeError):
                src = None
            if not (isinstance(src, dict) and "subagent" in src):
                out.append(f)
        return out
    if agent == "opencode":
        import sqlite3
        from opencode_translator import DEFAULT_DB
        db = root or DEFAULT_DB
        con = sqlite3.connect("file:" + Path(db).resolve().as_posix() + "?mode=ro",
                              uri=True)
        try:
            ids = [r[0] for r in con.execute(
                "select id from session_v2 where parent_id is null")]
            ids += [r[0] for r in con.execute(
                "select id from session s where parent_id is null and not exists"
                "(select 1 from session_v2 v where v.id = s.id)")]
        finally:
            con.close()
        return [OPENCODE_PREFIX + i for i in ids]
    raise ValueError(f"agent는 codex 또는 opencode: {agent}")


def convert_all(agent, out_dir, root=None):
    """이 PC의 Codex 또는 OpenCode 세션 전체 → out_dir에 Claude 모양 jsonl.

    out_dir는 기존 측정기에 그대로 넣는 폴더다:
        python ../session-api/record_actions_code_api_all_sessions.py <out_dir>
    다른 에이전트에서 가져온 사본(Codex의 Claude 세션 가져오기)은 쓰지 않고
    요약에 센다. 요약은 out_dir/_translator_summary.json."""
    os.makedirs(out_dir, exist_ok=True)
    kw = {"codex_root": os.path.join(root, "sessions")} if (agent == "codex" and root) \
        else {"opencode_db": root} if agent == "opencode" else {}
    summary = {"agent": agent, "root": root, "converted": [], "excluded": [],
               "errors": []}
    for src in list_sources(agent, root):
        try:
            res = convert(src, out_dir=out_dir, **kw)
        except Exception as e:  # 한 세션 실패가 전체를 멈추지 않게 — 요약에 남긴다
            summary["errors"].append({"src": src, "error": f"{type(e).__name__}: {e}"})
            continue
        if res.get("excluded"):
            summary["excluded"].append({"src": src, "reason": res["excluded"]})
            continue
        summary["converted"].append({"src": src, "main": res["main"],
                                     "subagents": len(res.get("subagents") or []),
                                     "notes": res.get("notes") or []})
    with open(os.path.join(out_dir, "_translator_summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    return summary


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = list(argv)
    opts = {}
    for k in ("--out", "--all", "--root"):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            del args[i:i + 2]
    out = opts.get("--out")
    if "--all" in opts:
        if not out:
            print("--all에는 --out 폴더가 필요하다", file=sys.stderr)
            return 2
        s = convert_all(opts["--all"], out, root=opts.get("--root"))
        why = {}
        for e in s["excluded"]:
            k = "빈 세션" if e["reason"].startswith("빈 세션") else "다른 에이전트 세션 사본"
            why[k] = why.get(k, 0) + 1
        print(f"변환 {len(s['converted'])}세션, 제외 "
              + (", ".join(f"{k} {v}" for k, v in why.items()) or "0")
              + f", 실패 {len(s['errors'])} → {out}")
        return 1 if s["errors"] else 0
    if not args:
        print("usage: python session_translator.py <입력> [--out 폴더]\n"
              "       python session_translator.py --all codex|opencode --out 폴더 "
              "[--root Codex홈|opencode.db]", file=sys.stderr)
        return 2
    for src in args:
        res = convert(src, out_dir=out)
        print(json.dumps({k: v for k, v in res.items()},
                         ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
