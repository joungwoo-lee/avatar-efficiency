# -*- coding: utf-8 -*-
"""Codex rollout(jsonl) → Claude Code 기록 모양 (§96, DESIGN.md 6장).

기준 버전: Codex CLI 0.162.1. 코드 모드 셀(`custom_tool_call` exec) 안의 개별
도구 호출은 `item_completed` 항목(시작·끝 밀리초)으로 기록된다 — 변환은 이 항목을
기준으로 한다. 다중 에이전트 v2의 암호화 본문은 토큰 수로 단어 수를 환산한다(6.4).
"""
import glob
import json
import os
import re
from pathlib import Path

from session_translator import (ClaudeWriter, Placeholder, epoch,
                              file_ops_to_tools, hunks_from_unified_diff,
                              json_text_words, parse_apply_patch,
                              task_notification, words, _clean, read_text,
                              first_line, session_stem)

DEFAULT_ROOT = os.path.join(os.environ.get("CODEX_HOME")
                            or os.path.join(str(Path.home()), ".codex"),
                            "sessions")

_ENC_RE = re.compile(r"^gAAAAA[\w\-=]{20,}$")
_HEADER_RE = re.compile(r"^Script \w+[^\n]*\nWall time [^\n]*\n(?:Output:\n)?")
_TRUNC_RE = re.compile(r"^Warning: truncated output[^\n]*\n(?:Total output lines:[^\n]*\n)?\n?")
_NOISE_KEYS = {"chunk_id", "session_id", "status", "wall_time_seconds",
               "exit_code", "original_token_count", "i", "timed_out"}
_TOOL_ITEMS = {"CommandExecution", "FileChange", "Extension", "McpToolCall",
               "ImageView", "DynamicToolCall"}
_AGENT_SEND = ("send_message", "followup_task")
_PROSE_FALLBACK = 0.75      # 토큰→단어 (record_actions_code_api.THINK_TOK2WORD와 같은 값)


def is_encrypted(v):
    return isinstance(v, str) and bool(_ENC_RE.match(v.strip()))


def _read(path):
    recs = []
    for line in read_text(path).splitlines():   # 압축(.jsonl.zst) 기록도
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            recs.append(rec)
    return recs


def _pl(rec):
    p = rec.get("payload")
    return p if isinstance(p, dict) else {}


def _meta(recs):
    for r in recs:
        if r.get("type") == "session_meta":
            return _pl(r)
    return {}


def _ms(t):
    return epoch(t)


def _args(p):
    a = p.get("arguments")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            a = {"raw": a}
    return a if isinstance(a, dict) else {}


def _out_text(out):
    """도구 출력 → (헤더 뗀 부분 글 목록)."""
    if isinstance(out, list):
        parts = [x.get("text", "") for x in out
                 if isinstance(x, dict) and isinstance(x.get("text"), str)]
    elif isinstance(out, str):
        parts = [out]
    else:
        parts = []
    clean = []
    for i, p in enumerate(parts):
        p = _HEADER_RE.sub("", p, count=1) if i == 0 else p
        p = _TRUNC_RE.sub("", p, count=1)
        if p.strip():
            clean.append(p)
    return clean


def _leaves(v, key=None):
    if isinstance(v, str):
        return [] if key in _NOISE_KEYS else [v]
    if isinstance(v, dict):
        out = []
        for k, x in v.items():
            out.extend(_leaves(x, k))
        return out
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(_leaves(x, key))
        return out
    return []


def _segments(parts):
    """셀 출력 → 글 조각 목록. JSON이면 문자열 잎으로 푼다(이스케이프 해제)."""
    segs = []
    for p in parts:
        s = p.strip()
        try:
            v = json.loads(s)
        except ValueError:
            v = None
        if isinstance(v, (dict, list)):
            segs.extend(x for x in _leaves(v) if x.strip())
        else:
            segs.append(p)
    return segs


def _norm(s):
    return re.sub(r"\s+", "", _clean(s))


def _match(segs, used, text, keys=()):
    """item 출력과 같은 조각 → 조각 번호 또는 None.

    출력 앞 120자가 조각 안에 있거나 조각 앞 120자가 출력 안에 있으면 같다.
    keys(웹 검색 결과 제목·주소 등)가 주어지면 그중 하나가 조각 안에 있어도 같다
    — 셀이 결과를 다른 꼴로 찍기 때문이다."""
    n = _norm(text)[:120]
    nk = [_norm(k)[:120] for k in keys if _norm(k)]
    if not n and not nk:
        return None
    for i, s in enumerate(segs):
        if i in used:
            continue
        ns = _norm(s)
        if n and (n in ns or (ns and ns[:120] in _norm(text))):
            return i
        if any(k in ns for k in nk):
            return i
    return None


def _item_keys(it):
    if it.get("type") == "Extension":
        keys = []
        for r in it.get("results") or []:
            if isinstance(r, dict):
                keys += [str(r.get(k)) for k in ("title", "url") if r.get(k)]
        return keys
    return []


def _cmd_string(command):
    if isinstance(command, list):
        if len(command) >= 3 and command[-2] in ("-Command", "-c", "-lc"):
            return str(command[-1])
        return " ".join(str(x) for x in command)
    return str(command or "")


def _item_output(it):
    t = it.get("type")
    if t == "CommandExecution":
        return it.get("aggregated_output") or it.get("formatted_output") \
            or (it.get("stdout") or "") + (it.get("stderr") or "")
    if t == "Extension":
        return "\n".join(_leaves(it.get("results") or []))
    if t == "McpToolCall":
        return "\n".join(_leaves(it.get("result") or []))
    if t == "DynamicToolCall":
        return "\n".join(_leaves(it.get("content_items") or []))
    return ""


def _item_tools(it):
    """item → [(Claude 도구명, 입력, 이미지 수)]."""
    t = it.get("type")
    if t == "CommandExecution":
        return [("Bash", {"command": _cmd_string(it.get("command"))}, 0)]
    if t == "FileChange":
        ops = []
        for path, ch in (it.get("changes") or {}).items():
            kind = (ch or {}).get("type")
            if kind == "add":
                ops.append({"op": "add", "path": path,
                            "content": ch.get("content") or ""})
            elif kind == "delete":
                ops.append({"op": "delete", "path": path})
            else:
                ops.append({"op": "update", "path": path,
                            "move_to": ch.get("move_path"),
                            "hunks": hunks_from_unified_diff(
                                ch.get("unified_diff") or "")})
        return [(n, i, 0) for n, i in file_ops_to_tools(ops)]
    if t == "Extension":
        if it.get("kind") == "web.search" and (
                (it.get("action") or {}).get("type") in (None, "search")):
            return [("WebSearch", {"query": it.get("query") or ""}, 0)]
        act = it.get("action") or {}
        return [("WebFetch", {"url": act.get("url") or act.get("ref_id")
                              or it.get("query") or ""}, 0)]
    if t == "McpToolCall":
        tool = str(it.get("tool") or "").replace(".", "_")
        return [(f"mcp__{it.get('server')}__{tool}",
                 it.get("arguments") or {}, 0)]
    if t == "ImageView":
        p = re.sub(r"^file:///?", "", str(it.get("path") or ""))
        return [("Read", {"file_path": p}, 1)]
    if t == "DynamicToolCall":
        return [(str(it.get("tool") or "dynamic"), it.get("arguments") or {}, 0)]
    return []


def _item_failed(it):
    if it.get("type") == "CommandExecution":
        ec = it.get("exit_code")
        return (ec not in (None, 0)) or it.get("status") == "failed"
    return it.get("status") in ("failed", "declined") or it.get("success") is False


# ---------------------------------------------------------------- 응답 묶음·추정

_OUT_TYPES = ("message", "reasoning", "function_call", "custom_tool_call",
              "web_search_call", "local_shell_call")


def _groups(recs, start=0):
    """응답 단위 묶음 → [{"items": [payload], "usage": dict|None}]."""
    has_usage = any(r.get("type") == "token_usage_record" for r in recs)
    groups, cur = [], []
    for idx, r in enumerate(recs):
        if idx < start:
            continue
        p = _pl(r)
        t = r.get("type")
        if t == "response_item" and p.get("type") in _OUT_TYPES and (
                p.get("type") != "message" or p.get("role") == "assistant"):
            cur.append(p)
        elif t == "token_usage_record" and has_usage:
            groups.append({"items": cur, "usage": p.get("usage") or {},
                           "rid": p.get("response_id")})
            cur = []
        elif (t == "event_msg" and p.get("type") == "token_count"
              and not has_usage and cur):
            groups.append({"items": cur,
                           "usage": (p.get("info") or {}).get("last_token_usage") or {},
                           "rid": None})
            cur = []
        elif (t == "response_item" and p.get("type") == "message"
              and p.get("role") == "user" and cur):
            groups.append({"items": cur, "usage": None, "rid": None})
            cur = []
    if cur:
        groups.append({"items": cur, "usage": None, "rid": None})
    return groups


def _group_stats(g):
    vis, enc, prose = 0, [], True
    for p in g["items"]:
        t = p.get("type")
        if t == "message":
            vis += sum(words(c.get("text")) for c in p.get("content") or []
                       if isinstance(c, dict))
        elif t == "reasoning":
            continue
        elif t == "function_call":
            prose = False
            a = _args(p)
            for k, v in a.items():
                if is_encrypted(v):
                    enc.append(("call", p.get("call_id")))
                else:
                    vis += json_text_words(v)
        else:
            prose = False
            vis += words(p.get("input") or "") + json_text_words(p.get("action") or {})
    u = g.get("usage") or {}
    out = max(0, int(u.get("output_tokens") or 0)
              - int(u.get("reasoning_output_tokens") or 0))
    return vis, enc, out, prose


def estimate_encrypted(rec_lists):
    """암호화 본문 단어 수 추정 (DESIGN 6.4) → ({key: 단어}, r_prose, r_all)."""
    pw = pt = aw = at = 0
    stats = []
    for recs, start in rec_lists:
        for g in _groups(recs, start):
            vis, enc, out, prose = _group_stats(g)
            stats.append((vis, enc, out))
            if enc or not out or g.get("usage") is None:
                continue
            aw += vis
            at += out
            if prose and vis:
                pw += vis
                pt += out
    r_all = (aw / at) if at else _PROSE_FALLBACK
    r_prose = (pw / pt) if pt else r_all
    est = {}
    for vis, enc, out in stats:
        if not enc:
            continue
        tok = max(0.0, out - (vis / r_all if r_all else 0.0))
        per = tok * r_prose / len(enc)
        for k in enc:
            est[k] = per
    return est, r_prose, r_all


# ---------------------------------------------------------------- 자식 찾기

def rollout_files(home):
    """Codex 홈의 rollout 전부 — sessions/ 와 보관함 archived_sessions/.
    Codex 앱이 압축해 둔 옛 기록(`rollout-*.jsonl.zst`)도 포함한다."""
    out = []
    for sub in ("sessions", "archived_sessions"):
        for pat in ("rollout-*.jsonl", "rollout-*.jsonl.zst"):
            out += glob.glob(os.path.join(home, sub, "**", pat), recursive=True)
    return sorted(out)


def imported_threads(home):
    """다른 에이전트(Claude Code 등)에서 가져온 스레드 → 가져온 시각(초).

    Codex는 가져온 기록을 자기 rollout으로 다시 쓴다. 그 부분은 다른 에이전트가
    한 일이라 Codex 몫이 아니다(원본은 그 에이전트 쪽에서 잰다)."""
    f = os.path.join(home, "external_agent_session_imports.json")
    try:
        with open(f, encoding="utf-8") as fh:
            recs = json.load(fh).get("records") or []
    except (OSError, ValueError, AttributeError):
        return {}
    return {r.get("imported_thread_id"): float(r.get("imported_at") or 0)
            for r in recs if isinstance(r, dict) and r.get("imported_thread_id")}


def import_cut(recs, imported_at):
    """가져온 기록의 끝 다음 줄 번호 — 가져온 시각(+2초) 안에 쓰인 줄은 사본."""
    cut = 0
    for i, r in enumerate(recs):
        t = _ms(r.get("timestamp"))
        if t is not None and t <= imported_at + 2.0:
            cut = i + 1
    return cut


_INDEX_CACHE = {}


def _index(home):
    files = rollout_files(home)
    key = (home, tuple((f, os.path.getmtime(f)) for f in files))
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    idx = {}
    for f in files:
        try:
            first = json.loads(first_line(f))
        except (OSError, ValueError, RuntimeError):
            continue
        p = _pl(first)
        src = p.get("source")
        spawn = (src or {}).get("subagent", {}) if isinstance(src, dict) else {}
        spawn = spawn if isinstance(spawn, dict) else {}
        par = (spawn.get("thread_spawn") or {}).get("parent_thread_id") \
            if isinstance(spawn.get("thread_spawn"), dict) else None
        if par:
            idx.setdefault(par, []).append(f)
    _INDEX_CACHE.clear()
    _INDEX_CACHE[key] = idx
    return idx


def _home_for(path, sessions_root):
    """rollout 경로 → Codex 홈(sessions/·archived_sessions/의 부모)."""
    if sessions_root:
        return str(Path(sessions_root).parent)
    p = Path(path).resolve()
    for anc in p.parents:
        if anc.name in ("sessions", "archived_sessions"):
            return str(anc.parent)
    return str(Path(DEFAULT_ROOT).parent)


# ---------------------------------------------------------------- 변환 본체

class _Conv:
    def __init__(self, recs, writer, est, ph, self_path, start=0,
                 child_new_task=None, notes=None):
        self.recs = recs
        self.w = writer
        self.est = est
        self.ph = ph
        self.self_path = self_path
        self.start = start
        self.child_new_task = child_new_task or {}
        self.notes = notes if notes is not None else []
        self.enc_used = 0
        self.model = None
        self.buf = []          # [(t, block)]
        self.n_resp = 0
        self.bg = {}           # pid → {"end", "status", "out", "start"}
        self.spawn_threads = {}   # spawn call_id → thread_id
        self.waits = []        # [(call_ts, out_ts, tool_use_id)]
        self.final_answers = []   # [(t, sender, text)]
        self.n_tool = 0
        self.child_msgs = []   # 부모가 이 자식에게 보낸 암호화 메시지 키(순서대로)

    # -- 사전 조사
    def prescan(self):
        self.outputs = {}
        self.calls = []
        self.items = []
        self.real_user = {}
        for idx, r in enumerate(self.recs):
            if idx < self.start:
                continue
            p = _pl(r)
            t = r.get("type")
            ts = _ms(r.get("timestamp"))
            st = p.get("type")
            if t == "response_item" and st in ("function_call_output",
                                               "custom_tool_call_output"):
                self.outputs[p.get("call_id")] = (ts, p.get("output"))
            elif t == "response_item" and st in ("function_call",
                                                 "custom_tool_call"):
                self.calls.append((ts, p.get("call_id")))
            elif t == "event_msg" and st == "item_completed":
                it = p.get("item") or {}
                if it.get("type") == "UserMessage":
                    txt = " ".join(c.get("text", "") for c in it.get("content") or []
                                   if isinstance(c, dict)).strip()
                    self.real_user[txt] = self.real_user.get(txt, 0) + 1
                elif it.get("type") == "SubAgentActivity" and it.get("kind") == "started":
                    self.spawn_threads[it.get("id")] = it.get("agent_thread_id")
                elif it.get("type") in _TOOL_ITEMS:
                    s = (p.get("started_at_ms") or 0) / 1000.0 or ts
                    e = (p.get("completed_at_ms") or 0) / 1000.0 or ts
                    self.items.append({"start": s, "end": e, "item": it})
            elif t == "event_msg" and st == "user_message":
                txt = str(p.get("message") or "").strip()
                if txt and txt not in self.real_user:
                    self.real_user[txt] = self.real_user.get(txt, 0) + 1
        # item → 그 item을 띄운 호출(시작 시각을 품은 가장 늦은 호출)
        self.call_items = {}
        self.orphans = []
        wins = []
        for ts, cid in self.calls:
            ots = (self.outputs.get(cid) or (None,))[0]
            wins.append((ts, ots if ots is not None else ts, cid))
        for it in sorted(self.items, key=lambda x: x["start"]):
            best = None
            for cts, ots, cid in wins:
                if cts - 0.05 <= it["start"] <= max(ots, cts) + 0.05:
                    if best is None or cts >= best[0]:
                        best = (cts, cid)
            if best:
                self.call_items.setdefault(best[1], []).append(it)
            else:
                self.orphans.append(it)

    # -- 응답 버퍼
    def flush(self, rid=None, usage=None):
        if not self.buf:
            return
        self.n_resp += 1
        mid = rid or f"resp_{self.w.session_id}_{self.n_resp}"
        tt = int((usage or {}).get("reasoning_output_tokens") or 0)
        for t, block in self.buf:
            self.w.assistant(t, mid, [block], thinking_tokens=tt, model=self.model)
        self.buf = []

    def tool(self, t_use, name, inp, t_res, text, is_error=False, tur=None,
             images=0, tid=None):
        self.n_tool += 1
        tid = tid or f"toolu_{self.w.session_id[-8:]}_{self.n_tool}"
        self.buf.append((t_use, {"type": "tool_use", "id": tid, "name": name,
                                 "input": inp}))
        if t_res is not None:
            self.w.tool_result(t_res, tid, text, is_error=is_error,
                               tool_use_result=tur, images=images)
        return tid

    def enc_text(self, key, fallback_key=None):
        n = self.est.get(key)
        if n is None and fallback_key is not None:
            n = self.est.get(fallback_key)
        if n is None:
            n = 0.0
        self.enc_used += 1
        return self.ph.make(n)

    # -- 도구 호출
    def do_cell(self, p, ts):
        cid = p.get("call_id")
        ots, out = self.outputs.get(cid, (ts, None))
        segs = _segments(_out_text(out))
        used = set()
        code = p.get("input") or ""
        for it in sorted(self.call_items.get(cid, []), key=lambda x: x["start"]):
            self.do_item(it, ots, segs, used)
        # 셀 속 write_stdin (항목 기록 없음) — 배경 실행 폴링 또는 입력
        for m in re.finditer(r"tools\.write_stdin\(\s*\{(.*?)\}\s*\)", code, re.S):
            body = m.group(1)
            cm = re.search(r"chars\s*:\s*(['\"`])(.*?)\1", body, re.S)
            chars = cm.group(2) if cm else ""
            pid, info = self.pick_bg(ts, segs, used)
            if chars:
                self.tool(ts, "Bash", {"command": chars}, ots, "")
                continue
            seen = ""
            if info:
                j = _match(segs, used, info.get("out") or "")
                if j is not None:
                    used.add(j)
                    seen = segs[j]
            status = "running"
            if info and info["end"] <= (ots or ts) + 0.5:
                status = info["status"]
            self.tool(ts, "BashOutput", {"bash_id": pid or ""}, ots,
                      f"<task_id>{pid}</task_id>\n<status>{status}</status>\n{seen}")
        rest = [s for i, s in enumerate(segs) if i not in used]
        if rest:
            self.tool(ots, "js_output", {"call_id": cid}, ots, "\n".join(rest))

    def pick_bg(self, ts, segs, used):
        cands = [(pid, b) for pid, b in self.bg.items() if b["start"] <= ts]
        if not cands:
            return None, None
        if len(cands) > 1:
            for pid, b in cands:
                if _match(segs, used, b.get("out") or "") is not None:
                    return pid, b
            cands.sort(key=lambda x: -x[1]["start"])
        return cands[0]

    def do_item(self, it, ots, segs, used):
        item = it["item"]
        tools = _item_tools(item)
        if not tools:
            return
        out = _item_output(item)
        failed = _item_failed(item)
        if (item.get("type") == "CommandExecution" and ots is not None
                and it["end"] > ots + 0.5):
            pid = str(item.get("process_id") or item.get("id"))
            status = "failed" if failed else "completed"
            self.bg[pid] = {"start": it["start"], "end": it["end"],
                            "status": status, "out": out}
            name, inp, _img = tools[0]
            inp = dict(inp, run_in_background=True)
            self.tool(it["start"], name, inp, ots,
                      f"Command running in background with ID: {pid}",
                      tur={"backgroundTaskId": pid})
            self.w.queue_notification(it["end"], task_notification(pid, status))
            return
        seen = ""
        if out:
            j = _match(segs, used, out, _item_keys(item))
            if j is not None:
                used.add(j)
                seen = segs[j]
        for k, (name, inp, img) in enumerate(tools):
            self.tool(it["start"], name, inp, it["end"],
                      seen if k == len(tools) - 1 else "",
                      is_error=failed, images=img)

    def do_function(self, p, ts):
        name = p.get("name")
        cid = p.get("call_id")
        a = _args(p)
        ots, out = self.outputs.get(cid, (ts, None))
        text = "\n".join(_out_text(out))
        inner = sorted(self.call_items.get(cid, []), key=lambda x: x["start"])
        if name in ("shell", "shell_command", "exec_command", "container.exec",
                    "local_shell"):
            cmd = a.get("command") or a.get("cmd") or ""
            if isinstance(cmd, list):
                cmd = _cmd_string(cmd)
            m = re.search(r"Process running with session ID (\d+)", text)
            j = None
            try:
                j = json.loads(text)
            except ValueError:
                pass
            bg_pid = m.group(1) if m else (
                str(j.get("session_id")) if isinstance(j, dict)
                and j.get("session_id") is not None and j.get("exit_code") is None
                else None)
            it = inner[0] if inner else None
            t0 = it["start"] if it else ts
            if bg_pid:
                end = it["end"] if it else None
                status = "failed" if it and _item_failed(it["item"]) else "completed"
                self.bg[bg_pid] = {"start": t0, "end": end or ots, "status": status,
                                   "out": _item_output(it["item"]) if it else ""}
                self.tool(t0, "Bash", {"command": str(cmd), "run_in_background": True},
                          ots, f"Command running in background with ID: {bg_pid}",
                          tur={"backgroundTaskId": bg_pid})
                if end:
                    self.w.queue_notification(end, task_notification(bg_pid, status))
                return
            ec = re.search(r"Exit code: (-?\d+)", text)
            failed = (it and _item_failed(it["item"])) or (
                ec is not None and ec.group(1) != "0")
            self.tool(t0, "Bash", {"command": str(cmd)},
                      it["end"] if it else ots, text, is_error=bool(failed))
            return
        if name == "write_stdin":
            pid = str(a.get("session_id") or "")
            chars = a.get("chars") or ""
            if chars:
                self.tool(ts, "Bash", {"command": chars}, ots, text)
                return
            b = self.bg.get(pid)
            status = b["status"] if b and b["end"] <= (ots or ts) + 0.5 else "running"
            self.tool(ts, "BashOutput", {"bash_id": pid}, ots,
                      f"<task_id>{pid}</task_id>\n<status>{status}</status>\n{text}")
            return
        if name == "apply_patch":
            self.do_patch(p, ts, a.get("input") or a.get("patch") or "", inner, ots)
            return
        if name == "spawn_agent":
            thread = self.spawn_threads.get(cid) or cid
            msg = a.get("message") or a.get("prompt") or ""
            prompt = self.enc_text(("call", cid)) if is_encrypted(msg) else str(msg)
            tname = str(a.get("task_name") or a.get("agent_type") or "")
            self.tool(ts, "Agent", {"prompt": prompt, "description": tname,
                                    "name": tname, "run_in_background": True},
                      ots, f"Async agent launched successfully.\nagentId: {thread}",
                      tur={"agentId": thread, "isAsync": True,
                           "status": "async_launched"})
            return
        if name == "wait_agent":
            tid = self.tool(ts, "TaskOutput", {"block": True}, None, "")
            self.waits.append((ts, ots, tid, text))
            return
        if name in _AGENT_SEND:
            msg = a.get("message") or ""
            body = self.enc_text(("call", cid)) if is_encrypted(msg) else str(msg)
            target = str(a.get("target") or a.get("to") or "")
            if self.is_report_target(target):
                # 자식이 부모에게 낸 보고 = 자식의 보고문(assistant 텍스트, §68)
                self.buf.append((ts, {"type": "text", "text": body}))
                return
            self.tool(ts, "SendMessage", {"to": target, "message": body}, ots, text)
            return
        if name in ("interrupt_agent", "close_agent"):
            self.tool(ts, "TaskStop", {"task_id": str(a.get("target") or "")}, ots, text)
            return
        if name == "list_agents":
            self.tool(ts, "TaskList", {}, ots, text)
            return
        if name == "update_plan":
            self.tool(ts, "TodoWrite", {"todos": a.get("plan") or []}, ots, text)
            return
        if name == "request_user_input":
            self.tool(ts, "AskUserQuestion", {"questions": a}, ots, text)
            return
        if name == "view_image":
            self.tool(ts, "Read", {"file_path": a.get("path") or ""}, ots, text,
                      images=1)
            return
        if inner:
            segs = _segments(_out_text(out))
            used = set()
            for it in inner:
                self.do_item(it, ots, segs, used)
            return
        self.tool(ts, str(name), a, ots, text,
                  is_error=bool(re.match(r"^(error|failed)", text.strip(), re.I)))

    def do_patch(self, p, ts, patch, inner, ots):
        fcs = [it for it in inner if it["item"].get("type") == "FileChange"]
        if fcs:
            for it in fcs:
                self.do_item(it, ots, [], set())
            return
        failed = bool(re.search(r"verification failed|error", str(
            (self.outputs.get(p.get("call_id")) or (None, ""))[1])[:300], re.I))
        for name, inp in file_ops_to_tools(parse_apply_patch(patch)):
            self.tool(ts, name, inp, ots, "", is_error=failed)

    def is_report_target(self, target):
        if not self.w.sidechain:
            return False
        parent = self.self_path.rsplit("/", 1)[0] if self.self_path else "/root"
        return target in (parent or "/root", "/root", "parent") or \
            (self.self_path and not target.startswith(self.self_path)
             and target.count("/") < self.self_path.count("/"))

    def do_custom(self, p, ts):
        name = p.get("name")
        if name == "exec":
            self.do_cell(p, ts)
            return
        if name == "apply_patch":
            cid = p.get("call_id")
            ots = (self.outputs.get(cid) or (ts,))[0]
            self.do_patch(p, ts, p.get("input") or "",
                          self.call_items.get(cid, []), ots)
            return
        cid = p.get("call_id")
        ots, out = self.outputs.get(cid, (ts, None))
        self.tool(ts, str(name), {"input": p.get("input") or ""}, ots,
                  "\n".join(_out_text(out)))

    def agent_message(self, p, ts):
        content = p.get("content") or []
        head = " ".join(c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "input_text")
        enc = any(isinstance(c, dict) and c.get("type") == "encrypted_content"
                  for c in content)
        payload = head.split("Payload:\n", 1)[1] if "Payload:\n" in head else head
        mtype = (re.search(r"Message Type: (\w+)", head) or [None, ""])[1]
        if p.get("recipient") == self.self_path and self.w.sidechain:
            if enc:
                key = (self.child_new_task.get("NEW_TASK") if mtype == "NEW_TASK"
                       else (self.child_msgs.pop(0) if self.child_msgs else None))
                payload = (payload + " " + self.enc_text(key)).strip()
            self.w.user_text(ts, payload)
            return
        if p.get("recipient") == self.self_path or not self.w.sidechain:
            if mtype == "FINAL_ANSWER":
                self.final_answers.append((ts, p.get("author"), payload))

    # -- 본 흐름
    def run(self):
        self.prescan()
        for idx, r in enumerate(self.recs):
            if idx < self.start:
                continue
            p = _pl(r)
            t = r.get("type")
            st = p.get("type")
            ts = _ms(r.get("timestamp"))
            if t == "turn_context":
                self.model = p.get("model") or self.model
                ap = p.get("approval_policy")
                if ap:
                    self.w.permission = ("bypassPermissions" if ap == "never"
                                         else "default")
            elif t == "token_usage_record":
                self.flush(p.get("response_id"), p.get("usage"))
            elif t == "compacted":
                self.flush()
                self.w.user_text(ts, str(p.get("message") or ""), compact=True)
            elif t == "event_msg":
                if st == "token_count" and not any(
                        x.get("type") == "token_usage_record" for x in self.recs):
                    self.flush(None, (p.get("info") or {}).get("last_token_usage"))
                elif st == "task_complete":
                    self.flush()
                    self.w.turn_duration(ts, p.get("duration_ms"))
                elif st == "turn_aborted":
                    self.flush()
                    if p.get("reason") == "interrupted":
                        self.w.user_text(ts, "[Request interrupted by user]")
                    self.w.turn_duration(ts, p.get("duration_ms"))
                elif st == "item_completed":
                    it = p.get("item") or {}
                    if it.get("type") == "SubAgentActivity" and it.get("kind") == "completed":
                        self.w.queue_notification(ts, task_notification(
                            it.get("agent_thread_id"), "completed"))
            elif t == "response_item":
                if st == "message":
                    role = p.get("role")
                    text = "\n".join(c.get("text", "") for c in p.get("content") or []
                                     if isinstance(c, dict) and isinstance(c.get("text"), str))
                    if role == "assistant":
                        self.buf.append((ts, {"type": "text", "text": text}))
                    elif role == "user":
                        self.flush()
                        key = text.strip()
                        if self.real_user.get(key):
                            self.real_user[key] -= 1
                            self.w.user_text(ts, text)
                        elif key.startswith(("<task-notification", "[Request interrupted")):
                            self.w.user_text(ts, text)
                        else:
                            self.w.user_text(ts, text, meta=True)
                elif st == "reasoning":
                    summ = " ".join(s.get("text", "") for s in p.get("summary") or []
                                    if isinstance(s, dict))
                    self.buf.append((ts, {"type": "thinking", "thinking": summ}))
                elif st == "function_call":
                    self.do_function(p, ts)
                elif st == "custom_tool_call":
                    self.do_custom(p, ts)
                elif st == "web_search_call":
                    act = p.get("action") or {}
                    self.tool(ts, "WebSearch", {"query": act.get("query") or ""}, ts, "")
                elif st == "local_shell_call":
                    act = p.get("action") or {}
                    self.tool(ts, "Bash", {"command": _cmd_string(act.get("command"))},
                              ts, "")
                elif st == "agent_message":
                    self.agent_message(p, ts)
        self.flush()
        for it in self.orphans:
            for name, inp, img in _item_tools(it["item"]):
                self.tool(it["start"], name, inp, it["end"],
                          _item_output(it["item"]),
                          is_error=_item_failed(it["item"]), images=img)
        self.flush()
        self.finish_waits()

    def finish_waits(self):
        """wait_agent 결과: 대기 중·직후 도착한 최종 답을 붙인다 (Claude TaskOutput)."""
        waits = sorted(self.waits)
        pending = list(self.final_answers)
        for cts, ots, tid, text in waits:
            got = []
            for fa in list(pending):
                if cts <= fa[0] <= (ots or cts) + 5.0:
                    got.append(fa)
                    pending.remove(fa)
            body = text
            for _t, author, payload in got:
                body += (f"\n<task_id>{author}</task_id>\n<status>completed</status>\n"
                         f"{payload}")
            self.w.tool_result(ots if ots is not None else cts, tid, body)
        for t, author, payload in pending:
            self.w.queue_notification(t, task_notification(author, "completed", payload))


def convert_codex(path, out_dir, sessions_root=None):
    """Codex rollout 1개(+자식) → out_dir에 Claude 모양 jsonl."""
    recs = _read(path)
    meta = _meta(recs)
    sid = str(meta.get("id") or session_stem(path))
    home = _home_for(path, sessions_root)
    # 다른 에이전트에서 가져온 사본 줄은 버린다. 남는 지시가 없으면 측정 제외.
    imp = imported_threads(home)
    main_start = import_cut(recs, imp[sid]) if sid in imp else 0
    if sid in imp and not any(
            _pl(r).get("type") == "item_completed"
            and (_pl(r).get("item") or {}).get("type") == "UserMessage"
            for r in recs[main_start:]):
        return {"main": None, "subagents": [], "notes": [], "name": Path(path).name,
                "excluded": ("다른 에이전트(Claude Code 등)에서 가져온 세션 사본 — "
                             "Codex가 한 일이 없음(원본은 그 에이전트 쪽에서 잰다, §96)")}
    idx = _index(home)
    # 자식(손자 포함) — guardian(자동 승인 검토기)은 위임한 일이 아니므로 뺀다
    children, queue = [], [sid]
    while queue:
        pid = queue.pop(0)
        for f in sorted(idx.get(pid, [])):
            crecs = _read(f)
            cm = _meta(crecs)
            src = cm.get("source") or {}
            if isinstance(src, dict) and (src.get("subagent") or {}).get("other") == "guardian":
                continue
            start = int(cm.get("subagent_history_start_ordinal") or 0)
            children.append((f, crecs, cm, start))
            queue.append(str(cm.get("id")))
    est, r_prose, r_all = estimate_encrypted(
        [(recs, main_start)] + [(c[1], c[3]) for c in children])
    ph = Placeholder()
    notes = []
    if main_start:
        notes.append("다른 에이전트에서 가져온 앞부분 사본은 빼고 Codex가 이어서 한 "
                     "부분만 쟀다(§96)")
    src = meta.get("source")
    entry = "sdk-cli" if src == "exec" else None
    w = ClaudeWriter(sid, entrypoint=entry)
    conv = _Conv(recs, w, est, ph, meta.get("agent_path") or "/root",
                 start=main_start, notes=notes)
    conv.run()
    stem = session_stem(path)
    main = os.path.join(out_dir, stem + ".jsonl")
    w.write(main)
    enc_total = conv.enc_used
    subs = []
    sub_dir = os.path.join(out_dir, stem, "subagents")
    # 부모 spawn 호출 → 자식 thread (암호화 지시문의 추정 단어를 자식 쪽에도 쓴다)
    spawn_by_thread = {}
    for c in [recs] + [x[1] for x in children]:
        for r in c:
            p = _pl(r)
            if p.get("type") == "item_completed":
                it = p.get("item") or {}
                if it.get("type") == "SubAgentActivity" and it.get("kind") == "started":
                    spawn_by_thread[it.get("agent_thread_id")] = ("call", it.get("id"))
    # 부모(조상)가 자식에게 보낸 send_message·followup_task 키 — 자식이 받은 순서대로
    names = {}
    for f, crecs, cm, start in children:
        cid = str(cm.get("id"))
        ap = str(cm.get("agent_path") or "")
        for n in (ap, ap.rsplit("/", 1)[-1], cm.get("agent_nickname")):
            if n:
                names[str(n)] = cid
    sends_to = {}
    for c, st in [(recs, 0)] + [(x[1], x[3]) for x in children]:
        for i, r in enumerate(c):
            p = _pl(r)
            if i >= st and p.get("type") == "function_call" and p.get("name") in _AGENT_SEND:
                a = _args(p)
                tgt = names.get(str(a.get("target") or ""))
                if tgt and is_encrypted(a.get("message")):
                    sends_to.setdefault(tgt, []).append(("call", p.get("call_id")))
    for f, crecs, cm, start in children:
        os.makedirs(sub_dir, exist_ok=True)
        cid = str(cm.get("id"))
        cw = ClaudeWriter(cid, sidechain=True)
        cc = _Conv(crecs, cw, est, ph, cm.get("agent_path") or "", start=start,
                   child_new_task={"NEW_TASK": spawn_by_thread.get(cid)},
                   notes=notes)
        cc.child_msgs = list(sends_to.get(cid, []))
        cc.run()
        enc_total += cc.enc_used
        subs.append(cw.write(os.path.join(sub_dir, f"agent-{cid}.jsonl")))
    if enc_total:
        notes.append(f"Codex 암호화 에이전트 메시지 {enc_total}건 — 본문 단어 수는 "
                     f"토큰 수 × 같은 세션 실측 비율({r_prose:.3f}단어/토큰)로 "
                     "환산(§96 DESIGN 6.4)")
    return {"main": main, "subagents": subs, "notes": notes,
            "name": Path(path).name}
