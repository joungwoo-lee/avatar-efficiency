# -*- coding: utf-8 -*-
"""OpenCode 세션 → Claude Code 기록 모양 (§96, DESIGN.md 7장).

기준 버전: OpenCode 2.0.29. 입력은 공식 내보내기 JSON(`opencode session export`)
또는 `opencode:<세션ID>`(opencode.db 읽기 전용). 2.x는 옛 세션도 v2 표
(`session_v2`·`session_message`)로 옮겨 두었다. 옮겨지지 않은 1.x 세션은 옛 표
(`session`·`message`·`part`)를 v2 모양으로 맞춘 뒤 같은 규칙으로 바꾼다.
"""
import json
import os
import sqlite3
from pathlib import Path

from session_translator import (OPENCODE_PREFIX, ClaudeWriter, epoch,
                              file_ops_to_tools, parse_apply_patch,
                              task_notification, _clean, ro_uri,
                              find_opencode_db)


# ---------------------------------------------------------------- 읽기

def _connect(db_path):
    if not db_path or not os.path.exists(db_path):
        return None
    return sqlite3.connect(ro_uri(db_path), uri=True)   # 읽기 전용, 경로는 URI 인코딩


def _has_table(con, name):
    return con.execute("select 1 from sqlite_master where type='table' and name=?",
                       (name,)).fetchone() is not None


def _v1_part_to_v2(part, part_created):
    """1.x part → v2 content 항목 (없으면 None)."""
    t = part.get("type")
    tm = part.get("time") or {}
    if t == "reasoning":
        return {"type": "reasoning", "text": part.get("text") or "",
                "time": {"created": tm.get("start"), "completed": tm.get("end")}}
    if t == "text":
        return {"type": "text", "text": part.get("text") or "",
                "synthetic": part.get("synthetic"),
                "time": {"created": tm.get("start"), "completed": tm.get("end")}}
    if t == "tool":
        st = part.get("state") or {}
        stt = st.get("time") or {}
        out = st.get("output")
        content = ([{"type": "text", "text": out}] if isinstance(out, str) else [])
        err = st.get("error")
        return {"type": "tool", "id": part.get("callID"), "name": part.get("tool"),
                "state": {"status": st.get("status"), "input": st.get("input") or {},
                          "content": content, "metadata": st.get("metadata") or {},
                          "error": {"message": err} if isinstance(err, str) else err},
                "time": {"created": part_created, "ran": stt.get("start"),
                         "completed": stt.get("end")}}
    return None


def _load_v1(con, sid):
    msgs = []
    rows = con.execute("select id, time_created, data from message where session_id=? "
                       "order by time_created, id", (sid,)).fetchall()
    for mid, mtc, data in rows:
        m = json.loads(data)
        parts = con.execute("select time_created, data from part where message_id=? "
                            "order by id", (mid,)).fetchall()
        parts = [(ptc, json.loads(d)) for ptc, d in parts]
        tm = m.get("time") or {}
        if m.get("role") == "user":
            real = [p for _t, p in parts if p.get("type") == "text"
                    and not p.get("synthetic")]
            synth = [p for _t, p in parts if p.get("type") == "text" and p.get("synthetic")]
            if real:
                msgs.append({"type": "user", "id": mid,
                             "time": {"created": tm.get("created") or mtc},
                             "text": "\n".join(p.get("text") or "" for p in real)})
            for p in synth:
                msgs.append({"type": "synthetic", "id": mid,
                             "time": {"created": tm.get("created") or mtc},
                             "text": p.get("text") or ""})
            for _t, p in parts:
                if p.get("type") == "compaction":
                    msgs.append({"type": "compaction", "id": mid,
                                 "time": {"created": tm.get("created") or mtc},
                                 "summary": ""})
            continue
        content = [c for c in (_v1_part_to_v2(p, ptc) for ptc, p in parts) if c]
        msgs.append({"type": "assistant", "id": mid,
                     "time": {"created": tm.get("created") or mtc,
                              "completed": tm.get("completed")},
                     "tokens": m.get("tokens") or {}, "error": m.get("error"),
                     "model": {"id": m.get("modelID")}, "content": content,
                     "summary": m.get("summary") is True})
    return msgs


def load_session(sid, db_path=None):
    """세션 ID → (메시지 목록, 자식 세션 ID 목록, 판형). DB 읽기 전용.
    db_path가 없으면 find_opencode_db()로 찾는다."""
    db_path = db_path or find_opencode_db()
    con = _connect(db_path)
    if con is None:
        raise FileNotFoundError(f"OpenCode DB 없음: {db_path}")
    try:
        if _has_table(con, "session_v2") and con.execute(
                "select 1 from session_v2 where id=?", (sid,)).fetchone():
            rows = con.execute("select id, type, data from session_message "
                               "where session_id=? order by seq", (sid,)).fetchall()
            msgs = []
            for mid, typ, data in rows:
                d = json.loads(data)
                d["id"], d["type"] = mid, typ
                msgs.append(d)
            kids = [r[0] for r in con.execute(
                "select id from session_v2 where parent_id=? order by time_created",
                (sid,))]
            return msgs, kids, "v2"
        if _has_table(con, "session") and con.execute(
                "select 1 from session where id=?", (sid,)).fetchone():
            kids = [r[0] for r in con.execute(
                "select id from session where parent_id=? order by time_created",
                (sid,))]
            return _load_v1(con, sid), kids, "v1"
    finally:
        con.close()
    raise KeyError(f"OpenCode 세션 없음: {sid}")


# ---------------------------------------------------------------- 도구 대응

def _content_text(state):
    c = state.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c
                         if isinstance(x, dict) and isinstance(x.get("text"), str))
    if isinstance(c, str):
        return c
    out = state.get("output")
    return out if isinstance(out, str) else ""


def _images(state):
    c = state.get("content")
    if isinstance(c, list):
        return sum(1 for x in c if isinstance(x, dict)
                   and (x.get("type") in ("image", "file")
                        and str(x.get("mime") or x.get("mediaType") or "image").startswith("image")))
    return 0


def _path(inp):
    return inp.get("path") or inp.get("filePath") or inp.get("file_path") or ""


def map_tool(name, state):
    """OpenCode 도구 → [(Claude 도구명, 입력)] + (결과 글, 오류 여부, toolUseResult)."""
    inp = state.get("input") or {}
    meta = state.get("metadata") or {}
    text = _content_text(state)
    err = state.get("status") == "error"
    if err:
        e = state.get("error")
        text = (e.get("message") if isinstance(e, dict) else str(e or "")) or text
    tur = None
    n = (name or "").lower()
    if n == "read":
        if text.startswith("Read directory"):
            tools = [("LS", {"path": _path(inp)})]
        else:
            r = {"file_path": _path(inp)}
            for k in ("offset", "limit"):
                if inp.get(k) is not None:
                    r[k] = inp[k]
            tools = [("Read", r)]
    elif n == "list":
        tools = [("LS", {"path": _path(inp)})]
    elif n == "write":
        tools = [("Write", {"file_path": _path(inp), "content": _clean(inp.get("content"))})]
    elif n == "edit":
        tools = [("Edit", {"file_path": _path(inp),
                           "old_string": _clean(inp.get("oldString") or inp.get("old_string")),
                           "new_string": _clean(inp.get("newString") or inp.get("new_string")),
                           "replace_all": bool(inp.get("replaceAll"))})]
    elif n == "multiedit":
        tools = [("MultiEdit", {"file_path": _path(inp), "edits": [
            {"old_string": _clean(e.get("oldString")), "new_string": _clean(e.get("newString"))}
            for e in inp.get("edits") or [] if isinstance(e, dict)]})]
    elif n in ("apply_patch", "patch"):
        tools = file_ops_to_tools(parse_apply_patch(
            inp.get("patchText") or inp.get("patch") or inp.get("input") or ""))
    elif n in ("shell", "bash"):
        bg = bool(inp.get("background") or inp.get("run_in_background"))
        tools = [("Bash", {"command": str(inp.get("command") or ""),
                           **({"run_in_background": True} if bg else {})})]
        ec = meta.get("exit")
        err = err or (ec not in (None, 0))
        sh = meta.get("shellID") or meta.get("jobID")
        if bg and sh and meta.get("status") == "running":
            text = f"Command running in background with ID: {sh}"
            tur = {"backgroundTaskId": sh}
            err = False
    elif n == "grep":
        tools = [("Grep", {"pattern": inp.get("pattern") or "", "path": _path(inp),
                           **({"glob": inp["include"]} if inp.get("include") else {})})]
    elif n == "glob":
        tools = [("Glob", {"pattern": inp.get("pattern") or "", "path": _path(inp)})]
    elif n == "webfetch":
        tools = [("WebFetch", {"url": inp.get("url") or ""})]
    elif n in ("websearch", "codesearch"):
        tools = [("WebSearch", {"query": inp.get("query") or ""})]
    elif n in ("todowrite", "todoread"):
        tools = [("TodoWrite", {"todos": inp.get("todos") or []})]
    elif n in ("task", "subagent"):
        tools = [("Agent", {"prompt": str(inp.get("prompt") or ""),
                            "description": str(inp.get("description") or ""),
                            "subagent_type": str(inp.get("agent") or inp.get("subagent_type") or "")})]
        tur = {"agentId": meta.get("sessionID") or meta.get("sessionId")}
    elif n == "question":
        tools = [("AskUserQuestion", {"questions": inp.get("questions") or inp})]
    elif n == "skill":
        tools = [("Skill", {"skill": inp.get("name") or inp.get("id") or ""})]
    else:
        tools = [(name or "unknown", inp)]
    return tools, text, err, tur


# ---------------------------------------------------------------- 변환 본체

SHELL_DIR = None   # 시험용 덮어쓰기. 평소에는 DB 옆의 shell/ 폴더를 쓴다


def shell_end_time(shell_id, launched, notified, shell_dir=None):
    """배경 셸의 실제 종료 시각 — OpenCode 셸 출력 파일(<shellID>.out)의 마지막
    기록 시각. 띄운 시각과 알림 시각 사이에 있을 때만 쓴다. 없으면 None."""
    if not shell_id or launched is None:
        return None
    root = SHELL_DIR or shell_dir
    if not root:
        return None
    try:
        for proj in os.listdir(root):
            f = os.path.join(root, proj, f"{shell_id}.out")
            if os.path.exists(f):
                t = os.path.getmtime(f)
                if launched <= t <= (notified or t):
                    return t
    except OSError:
        return None
    return None


def _t(d, *keys):
    for k in keys:
        v = (d or {}).get(k)
        if v:
            return v
    return None


def convert_messages(msgs, writer, children_seen=None, shell_dir=None):
    """v2 메시지 목록 → writer. 반환: Agent 호출로 만난 자식 세션 ID 목록."""
    kids = []
    turn_start = None
    last_t = None
    had_idle = any(m.get("type") == "idle" for m in msgs)
    n_tool = 0
    bg_launch = {}     # shellID → 띄운 시각

    def end_turn(t):
        if turn_start is not None and t and t > turn_start:
            writer.turn_duration(t, (t - turn_start) * 1000.0)

    for i, m in enumerate(msgs):
        typ = m.get("type")
        tm = m.get("time") or {}
        created = epoch(_t(tm, "created"))
        if typ == "user":
            if not had_idle and turn_start is not None:
                end_turn(last_t)
            writer.user_text(created, str(m.get("text") or ""))
            turn_start = created
            last_t = created
        elif typ == "synthetic":
            md = m.get("metadata") or {}
            if md.get("source") == "shell":
                sh = md.get("shellID") or md.get("jobID")
                state = md.get("state") or "completed"
                # 실제 종료 시각 = 셸 출력 파일의 마지막 기록 시각(띄운 시각~알림 사이일 때만).
                # AI가 바쁠 때 끝나면 알림은 늦게 배달된다 — Claude의 대기열 기록에 해당.
                end = shell_end_time(sh, bg_launch.get(sh), created, shell_dir)
                if end is not None and end < created:
                    writer.queue_notification(end, task_notification(sh, state))
                writer.user_text(created, task_notification(
                    sh, state, str(m.get("text") or "")))
            elif md.get("source") in ("subagent", "task"):
                writer.user_text(created, task_notification(
                    md.get("sessionID") or md.get("jobID"),
                    md.get("state") or "completed", str(m.get("text") or "")))
            else:
                writer.user_text(created, str(m.get("text") or ""), meta=True)
        elif typ == "system":
            writer.user_text(created, str(m.get("text") or ""), meta=True)
        elif typ == "compaction":
            writer.user_text(created, str(m.get("summary") or ""), compact=True)
        elif typ == "idle":
            end_turn(created)
            turn_start = None
        elif typ == "assistant":
            mid = m.get("id") or f"msg_{i}"
            tokens = m.get("tokens") or {}
            tt = int(tokens.get("reasoning") or 0)
            model = (m.get("model") or {}).get("id") if isinstance(m.get("model"), dict) \
                else m.get("model")
            err = m.get("error") or {}
            aborted = isinstance(err, dict) and err.get("type") in ("aborted",
                                                                    "MessageAbortedError")
            api_err = bool(err) and not aborted
            parts = m.get("content") or []
            a_start = epoch(_t(tm, "created")) or last_t
            a_end = epoch(_t(tm, "completed", "streamed")) or a_start
            cursor = a_start
            emitted = False
            for k, part in enumerate(parts):
                pt = part.get("type")
                ptm = part.get("time") or {}
                if pt == "reasoning":
                    t0 = epoch(_t(ptm, "created")) or cursor
                    writer.assistant(t0, mid, [{"type": "thinking",
                                                "thinking": part.get("text") or ""}],
                                     thinking_tokens=tt, model=model, api_error=api_err)
                    cursor = max(cursor or t0, epoch(_t(ptm, "completed")) or t0)
                    emitted = True
                elif pt == "text":
                    t0 = epoch(_t(ptm, "created"))
                    if t0 is None:
                        later = [epoch(_t(p.get("time") or {}, "created"))
                                 for p in parts[k + 1:]]
                        later = [x for x in later if x]
                        t0 = min(later) if later else a_end
                    t0 = max(t0, cursor or t0)
                    writer.assistant(t0, mid, [{"type": "text",
                                                "text": part.get("text") or ""}],
                                     thinking_tokens=tt, model=model, api_error=api_err)
                    cursor = t0
                    emitted = True
                elif pt == "tool":
                    st = part.get("state") or {}
                    tools, text, is_err, tur = map_tool(part.get("name") or part.get("tool"), st)
                    t_use = epoch(_t(ptm, "created", "ran")) or cursor
                    t_res = epoch(_t(ptm, "completed"))
                    unfinished = t_res is None and st.get("status") in ("pending", "running")
                    t_res = t_res or t_use
                    if tur and tur.get("backgroundTaskId"):
                        bg_launch[tur["backgroundTaskId"]] = t_use
                    if tur and tur.get("agentId"):
                        kids.append(tur["agentId"])
                        ran = epoch(_t(ptm, "ran")) or t_use
                        if t_res and ran and t_res > ran and st.get("status") == "completed":
                            tur["totalDurationMs"] = int(round((t_res - ran) * 1000))
                    for j, (name, inp) in enumerate(tools):
                        n_tool += 1
                        tid = f"{part.get('id') or 'tool'}_{n_tool}"
                        writer.assistant(t_use, mid, [{"type": "tool_use", "id": tid,
                                                       "name": name, "input": inp}],
                                         thinking_tokens=tt, model=model, api_error=api_err)
                        last = j == len(tools) - 1
                        if unfinished:   # 끝나지 않은 호출 — 결과 기록 없음(Claude와 같다)
                            continue
                        writer.tool_result(t_res, tid, text if last else "",
                                           is_error=is_err,
                                           tool_use_result=tur if last else None,
                                           images=_images(st) if last else 0)
                    cursor = max(cursor or t_use, t_use)
                    emitted = True
            if not emitted and (api_err or tt):
                writer.assistant(a_start, mid, [{"type": "text", "text": ""}],
                                 thinking_tokens=tt, model=model, api_error=api_err)
            if aborted:
                writer.user_text(a_end, "[Request interrupted by user]")
            last_t = a_end or last_t
    if not had_idle and turn_start is not None:
        end_turn(last_t)
    return kids


def _load_export(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc.get("messages") or [], (doc.get("info") or {}).get("id")


def convert_opencode(src, out_dir, db_path=None):
    """OpenCode 세션 1개(+자식) → out_dir에 Claude 모양 jsonl.

    db_path: 실제 DB 경로(session_translator.find_opencode_db로 찾은 것).
    export 파일 입력이면 None이어도 된다 — 그때는 자식 세션을 같은 폴더의
    <세션ID>.json에서만 찾는다. 셸 출력 파일은 DB 옆 shell/ 폴더에서 찾는다."""
    s = str(src)
    shell_dir = os.path.join(os.path.dirname(db_path), "shell") if db_path else None
    if s.startswith(OPENCODE_PREFIX):
        sid = s[len(OPENCODE_PREFIX):]
        msgs, kids, form = load_session(sid, db_path)
        name = sid
    else:
        msgs, sid = _load_export(s)
        sid = sid or Path(s).stem
        kids, form = [], "export"
        name = Path(s).name
        if db_path:
            try:
                _m, kids, _f = load_session(sid, db_path)
            except (KeyError, FileNotFoundError, sqlite3.Error):
                kids = []
    w = ClaudeWriter(sid)
    found = convert_messages(msgs, w, shell_dir=shell_dir)
    main = os.path.join(out_dir, sid + ".jsonl")
    w.write(main)
    notes = []
    subs = []
    sub_dir = os.path.join(out_dir, sid, "subagents")
    queue = list(dict.fromkeys([k for k in kids + found if k]))
    done = set()
    missing = []
    while queue:
        cid = queue.pop(0)
        if cid in done:
            continue
        done.add(cid)
        cmsgs = None
        sib = os.path.join(os.path.dirname(s), cid + ".json") \
            if not s.startswith(OPENCODE_PREFIX) else None
        if sib and os.path.exists(sib):
            cmsgs, _ = _load_export(sib)
            gk = []
        elif db_path:
            try:
                cmsgs, gk, _f = load_session(cid, db_path)
            except (KeyError, FileNotFoundError, sqlite3.Error):
                missing.append(cid)
                continue
        else:
            missing.append(cid)
            continue
        os.makedirs(sub_dir, exist_ok=True)
        cw = ClaudeWriter(cid, sidechain=True)
        more = convert_messages(cmsgs, cw, shell_dir=shell_dir)
        subs.append(cw.write(os.path.join(sub_dir, f"agent-{cid}.jsonl")))
        queue.extend(k for k in gk + more if k and k not in done)
    if missing:
        notes.append(f"OpenCode 자식 세션 {len(missing)}개를 찾지 못함 — 서브에이전트 몫 "
                     "누락(내보내기 파일을 같은 폴더에 <세션ID>.json으로 두거나 DB 경로 지정)")
    return {"main": main, "subagents": subs, "notes": notes, "name": name,
            "opencode_form": form}
