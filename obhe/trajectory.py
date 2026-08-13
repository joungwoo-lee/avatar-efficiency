# -*- coding: utf-8 -*-
"""로컬 결정론 층 1 — trajectory 읽기 + 세션 metadata + 수정 경로 추출 (LLM 미사용).

방법론 §3~§4:
  - tolerant parser: JSONL 형식이 버전마다 달라도 중첩 구조를 걸어 다니며
    tool_use / user message / metadata를 찾는다 (version adapter).
  - DirectTouchedPaths = Write ∪ Edit ∪ NotebookEdit 경로 (신뢰도 높음)
  - BashCandidatePaths = redirect·cp·mv·sed -i 등 heuristic (신뢰도 낮음)
  - task_requests = user message에서 deterministic 추출
"""
import json
import re
from pathlib import Path

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

_REDIRECT = re.compile(r"(?:>>?|\btee\b(?:\s+-a)?)\s+([^\s;|&()<>]+)")
_CP_MV = re.compile(r"\b(?:cp|mv)\b(?:\s+-[\w-]+)*\s+\S+\s+([^\s;|&()<>]+)")
_SED_I = re.compile(r"\bsed\b[^;|&]*?-i\S*\s+(?:'[^']*'|\"[^\"]*\")\s+([^\s;|&()<>]+)")


def _iter_json_lines(path):
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerant: 깨진 줄은 건너뜀


def _walk(obj):
    """중첩 어디에 있든 dict를 전부 방문한다."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _user_texts(rec):
    """type=user 레코드에서 사람이 친 텍스트만 뽑는다 (tool_result 제외)."""
    texts = []
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
    return [t.strip() for t in texts
            if t and not t.lstrip().startswith("<") and len(t.strip()) > 2]


def bash_candidate_paths(command):
    """Bash command 문자열에서 출력 경로 후보를 heuristic으로 뽑는다."""
    out = set()
    for pat in (_REDIRECT, _CP_MV, _SED_I):
        for m in pat.finditer(command):
            p = m.group(1).strip("'\"")
            if p and not p.startswith(("-", "$", "/dev/")) and p not in ("&1", "&2"):
                out.add(p)
    return out


def parse_trajectory(path):
    """trajectory JSONL 1개 → 세션 정보 dict."""
    sess = {
        "file": str(path),
        "session_id": None,
        "cwd": None,
        "timestamps": [],
        "task_requests": [],
        "direct_paths": set(),
        "bash_candidate_paths": set(),
        "git_commands": [],
    }
    for rec in _iter_json_lines(path):
        if rec.get("type") == "user" and not rec.get("isMeta"):
            sess["task_requests"].extend(_user_texts(rec))
        for d in _walk(rec):
            if sess["session_id"] is None and isinstance(d.get("sessionId"), str):
                sess["session_id"] = d["sessionId"]
            if sess["cwd"] is None and isinstance(d.get("cwd"), str):
                sess["cwd"] = d["cwd"]
            ts = d.get("timestamp")
            if isinstance(ts, str):
                sess["timestamps"].append(ts)
            if d.get("type") == "tool_use" and isinstance(d.get("input"), dict):
                name, inp = d.get("name"), d["input"]
                if name in FILE_TOOLS:
                    p = inp.get("file_path") or inp.get("notebook_path")
                    if p:
                        sess["direct_paths"].add(p)
                elif name == "Bash" and isinstance(inp.get("command"), str):
                    cmd = inp["command"]
                    sess["bash_candidate_paths"] |= bash_candidate_paths(cmd)
                    if re.search(r"(?:^|[;&|]\s*)git\s+", " " + cmd):
                        sess["git_commands"].append(cmd)
    sess["timestamps"].sort()
    return sess


def group_sessions(sessions):
    """cwd 기준 grouping (방법론 §13). 시간순 정렬."""
    jobs = {}
    for s in sessions:
        jobs.setdefault(s["cwd"] or "?", []).append(s)
    for group in jobs.values():
        group.sort(key=lambda s: s["timestamps"][0] if s["timestamps"] else "")
    return jobs
