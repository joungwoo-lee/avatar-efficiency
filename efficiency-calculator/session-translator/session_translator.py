# -*- coding: utf-8 -*-
"""Session Translator — Codex·OpenCode 세션 → Claude Code 세션 모양 jsonl (§96, DESIGN.md).

번역기만 한다 — 측정기(session-api 등)는 이 모듈을 모르고, 바꾸지도 않는다.
이 모듈은 "다른 에이전트의 이 기록이 Claude 기록의 무엇에 해당하는가"만 정해
Claude Code 세션 모양 파일을 써 낸다. 그 파일을 기존 측정기에 그대로 넣는다.

워커에서 부르는 법 (한 세션씩 번역 → 측정 → 삭제):
    from session_translator import list_sessions, translate_session
    for s in list_sessions("opencode", since=time.time() - 30 * 86400, seen=ledger):
        with translate_session(s["src"], work_dir=state_dir / "translate") as t:
            if t.main:
                r = measure(t.main, subagent_paths=t.subagents)
        ledger[s["src"]] = s["updated_at"]

위치 찾기: find_opencode_db() — 인자 → OPENCODE_DB → XDG_DATA_HOME → 기본 위치,
          find_codex_home() — 인자 → CODEX_HOME → ~/.codex.
"""
import json
import os
import re
import sys
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


# ---------------------------------------------------------------- 위치 찾기

def ro_uri(path):
    """SQLite 읽기 전용 URI. 경로를 문자열로 이어 붙이지 않는다.

    `Path.as_uri()`가 `?`·`#`·공백을 퍼센트 인코딩하고 Windows에서
    `file:///C:/...`(슬래시 3개)를 만든다 — 경로 일부가 질의·조각으로 잘려
    엉뚱한 빈 DB를 열거나 못 여는 일을 막는다."""
    return Path(path).resolve().as_uri() + "?mode=ro"


def find_opencode_db(explicit=None):
    """OpenCode DB 경로 → 실제 위치(심볼릭 링크를 따라간 절대 경로).

    찾는 순서: ① 인자 ② 환경변수 OPENCODE_DB ③ XDG_DATA_HOME/opencode/opencode.db
    ④ ~/.local/share/opencode/opencode.db. 처음 있는 것을 쓰고, 없으면 찾아본
    경로를 모두 적어 FileNotFoundError. ①·②는 사람이 정한 위치라 그 파일이
    없으면 다음 후보로 넘어가지 않고 바로 오류를 낸다(엉뚱한 DB를 읽지 않게)."""
    for given, label in ((explicit, "인자"), (os.environ.get("OPENCODE_DB"), "OPENCODE_DB")):
        if given:
            p = Path(given).expanduser()
            if not p.exists():
                raise FileNotFoundError(f"OpenCode DB 없음({label}): {given}")
            return str(p.resolve())
    tried = []
    for cand in (
                 os.path.join(os.environ["XDG_DATA_HOME"], "opencode", "opencode.db")
                 if os.environ.get("XDG_DATA_HOME") else None,
                 os.path.join(str(Path.home()), ".local", "share", "opencode",
                              "opencode.db")):
        if not cand:
            continue
        tried.append(str(cand))
        p = Path(cand).expanduser()
        if p.exists():
            return str(p.resolve())
    raise FileNotFoundError("OpenCode DB를 찾지 못함 — 찾아본 곳: " + ", ".join(tried))


def find_codex_home(explicit=None):
    """Codex 홈(sessions·archived_sessions의 부모) → 실제 위치.

    찾는 순서: ① 인자 ② 환경변수 CODEX_HOME ③ ~/.codex. ①·②가 주어졌는데
    폴더가 없으면 다음 후보로 넘어가지 않고 바로 오류를 낸다."""
    for given, label in ((explicit, "인자"), (os.environ.get("CODEX_HOME"), "CODEX_HOME")):
        if given:
            p = Path(given).expanduser()
            if not p.is_dir():
                raise FileNotFoundError(f"Codex 홈 없음({label}): {given}")
            return str(p.resolve())
    tried = []
    for cand in (os.path.join(str(Path.home()), ".codex"),):
        if not cand:
            continue
        tried.append(str(cand))
        p = Path(cand).expanduser()
        if p.is_dir():
            return str(p.resolve())
    raise FileNotFoundError("Codex 홈을 찾지 못함 — 찾아본 곳: " + ", ".join(tried))


# ---------------------------------------------------------------- 변환 입구

def convert(src, out_dir, opencode_db=None, codex_home=None):
    """세션 1개 → out_dir에 Claude 모양 jsonl. 반환
    {"format", "main", "subagents", "notes", "name"} (+ 빠질 때 "excluded").

    out_dir는 반드시 준다 — 시스템 임시 폴더에는 쓰지 않는다(그 폴더가 차서
    난 사고가 있었다). 보통은 아래 translate_session()을 쓴다. Claude 기록이면
    변환하지 않고 원본 경로를 그대로 돌려준다(원본은 건드리지 않는다)."""
    if not out_dir:
        raise ValueError("out_dir가 필요하다 — 시스템 임시 폴더에는 쓰지 않는다")
    fmt = detect_format(src)
    if fmt == "claude":
        return {"format": "claude", "main": str(src), "subagents": None,
                "notes": [], "name": Path(str(src)).name}
    os.makedirs(out_dir, exist_ok=True)
    if fmt == "codex":
        from codex_translator import convert_codex
        home = find_codex_home(codex_home) if codex_home else None
        res = convert_codex(str(src), out_dir, codex_home=home)
    else:
        from opencode_translator import convert_opencode
        try:
            db = find_opencode_db(opencode_db)
        except FileNotFoundError:
            if str(src).startswith(OPENCODE_PREFIX):
                raise                      # DB 세션 지정인데 DB가 없다
            db = None                      # export 파일은 DB 없이도 번역된다
        res = convert_opencode(str(src), out_dir, db_path=db)
    res["format"] = fmt
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


# ---------------------------------------------------------------- 목록 → 한 세션씩

def list_sessions(agent, root=None, since=None, seen=None):
    """측정 대상 원본 목록 → [{"src", "agent", "updated_at"}] (최신순 — 가장 최근에 바뀐 것부터).

    agent = "codex" | "opencode". root = Codex 홈 또는 OpenCode DB(없으면 찾는다).
    since: epoch 초 — 이 시각 뒤에 바뀐 세션만 (예: 최근 30일 = time.time() - 30*86400).
    seen:  {src: updated_at} — 지난번에 처리한 세션. 그 뒤로 바뀐 것만 남긴다.
    변환은 하지 않는다. 하나씩 translate_session()에 넣는다.

    codex: sessions·archived_sessions의 rollout 중 자식(서브에이전트)이 아닌 것.
           자식은 부모를 번역할 때 함께 들어간다. updated_at = 파일 수정 시각.
    opencode: 최상위 세션(v2 + 옮겨지지 않은 1.x) → "opencode:<ID>".
              updated_at = 세션 갱신 시각."""
    if agent == "codex":
        from codex_translator import rollout_files, _pl
        home = find_codex_home(root)
        thread_updated = _codex_thread_updated(home)
        rows = []
        for f in rollout_files(home):
            try:
                src = _pl(json.loads(first_line(f))).get("source")
            except (OSError, ValueError, RuntimeError):
                src = None
            if not (isinstance(src, dict) and "subagent" in src):
                rows.append((f, thread_updated.get(_thread_id(f)) or _last_event_time(f)
                             or os.path.getmtime(f)))
    elif agent == "opencode":
        import sqlite3
        con = sqlite3.connect(ro_uri(find_opencode_db(root)), uri=True)
        try:
            rows = []
            if con.execute("select 1 from sqlite_master where name='session_v2'").fetchone():
                rows += [(OPENCODE_PREFIX + i, (u or 0) / 1000.0) for i, u in con.execute(
                    "select id, time_updated from session_v2 where parent_id is null")]
            if con.execute("select 1 from sqlite_master where name='session'").fetchone():
                v2 = {r[0][len(OPENCODE_PREFIX):] for r in rows}
                rows += [(OPENCODE_PREFIX + i, (u or 0) / 1000.0) for i, u in con.execute(
                    "select id, time_updated from session where parent_id is null")
                    if i not in v2]
        finally:
            con.close()
    else:
        raise ValueError(f"agent는 codex 또는 opencode: {agent}")
    seen = seen or {}
    out = [{"src": s, "agent": agent, "updated_at": u} for s, u in rows
           if (since is None or u > since) and (s not in seen or u > seen[s])]
    return sorted(out, key=lambda r: r["updated_at"], reverse=True)


_UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
                      r"\.jsonl(?:\.zst)?$")


def _thread_id(path):
    m = _UUID_RE.search(os.path.basename(str(path)))
    return m.group(1) if m else None


def _codex_thread_updated(home):
    """Codex 스레드 목록(state_N.sqlite threads.updated_at_ms) → {스레드ID: 초}.

    세션이 실제로 바뀐 시각이다. 파일 수정 시각은 쓰지 않는다 — Codex 앱이 옛
    기록을 압축하거나 다른 에이전트 세션을 가져올 때 파일을 다시 써서, 바뀌지 않은
    세션도 "방금 바뀐" 것처럼 보이기 때문이다. 목록이 없으면 빈 dict."""
    import glob
    import sqlite3
    dbs = sorted(glob.glob(os.path.join(home, "state_*.sqlite")),
                 key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
    if not dbs:
        return {}
    try:
        con = sqlite3.connect(ro_uri(dbs[-1]), uri=True)
        try:
            return {i: u / 1000.0 for i, u in con.execute(
                "select id, updated_at_ms from threads where updated_at_ms is not null")}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def _last_event_time(path):
    """기록의 마지막 사건 시각(초) — 스레드 목록에 없는 rollout의 대안."""
    last = None
    for line in read_text(path).splitlines():
        try:
            t = epoch(json.loads(line).get("timestamp"))
        except ValueError:
            continue
        if t and (last is None or t > last):
            last = t
    return last


class TranslatedSession:
    """translate_session()이 내주는 한 세션의 번역 결과.

    folder    — 측정기에 그대로 넣는 폴더. 이 세션 파일만 들어 있다:
                <folder>/<세션>.jsonl, <folder>/<세션>/subagents/agent-*.jsonl
                (record_actions_code_api_all_sessions.py <folder> 로도 잴 수 있다)
    main      — 메인 기록 경로 (빠지는 세션이면 None)
    subagents — 서브에이전트 기록 경로 목록
    notes     — 번역 주석(암호화 본문 환산 등)
    excluded  — 빠지는 사유(다른 에이전트 사본·빈 세션) 또는 None
    src, format, name"""

    def __init__(self, src, folder, res):
        self.src = src
        self.folder = folder
        self.main = res.get("main")
        self.subagents = list(res.get("subagents") or [])
        self.notes = list(res.get("notes") or [])
        self.excluded = res.get("excluded")
        self.format = res.get("format")
        self.name = res.get("name")


class translate_session:
    """세션 1개를 work_dir 아래 전용 폴더에 번역하고, with 블록이 끝나면 지운다.

        with translate_session(src, work_dir=state_dir / "translate") as t:
            if t.main:
                measure(t.main, subagent_paths=t.subagents)
        # 여기서 t.folder는 이미 지워졌다

    한 번에 한 세션만 디스크에 둔다 — 전 세션을 쌓아 디스크가 찼던 사고를
    막기 위해서다. work_dir는 반드시 준다(시스템 임시 폴더 금지). 블록 안에서
    예외가 나도 폴더는 지운다."""

    def __init__(self, src, work_dir, opencode_db=None, codex_home=None):
        if not work_dir:
            raise ValueError("work_dir가 필요하다 — 시스템 임시 폴더에는 쓰지 않는다")
        self.src = str(src)
        self.work_dir = str(work_dir)
        self.kw = {"opencode_db": opencode_db, "codex_home": codex_home}
        self.folder = None

    def __enter__(self):
        import hashlib
        os.makedirs(self.work_dir, exist_ok=True)
        tag = hashlib.sha1(self.src.encode("utf-8")).hexdigest()[:12]
        self.folder = os.path.join(self.work_dir, f"session-{tag}-{os.getpid()}")
        if os.path.exists(self.folder):          # 앞서 죽은 실행의 찌꺼기
            _rmtree(self.folder)
        os.makedirs(self.folder)
        try:
            res = convert(self.src, self.folder, **self.kw)
        except BaseException:
            _rmtree(self.folder)
            raise
        return TranslatedSession(self.src, self.folder, res)

    def __exit__(self, *exc):
        if self.folder:
            _rmtree(self.folder)
        return False


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------- CLI (세션 1개만)

def main(argv):
    """세션 1개를 지정 폴더에 번역해 결과를 보여 준다(점검용).

    전 세션 일괄 변환은 일부러 두지 않는다 — 한 세션씩 번역·측정·삭제하는 쪽
    (list_sessions + translate_session)을 쓴다."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = list(argv)
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    if not args or not out:
        print("usage: python session_translator.py <입력> --out 폴더\n"
              "  입력 = Codex rollout(.jsonl|.jsonl.zst) | OpenCode export JSON | "
              "opencode:<세션ID>", file=sys.stderr)
        return 2
    for src in args:
        res = convert(src, out)
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
