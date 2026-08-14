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
import os
import re
from pathlib import Path

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}  # Windows 세션은 PowerShell 툴 사용 (실측 검증됨)

_REDIRECT = re.compile(r"(?:>>?|\btee\b(?:\s+-a)?)\s+([^\s;|&()<>]+)")
_CP_MV = re.compile(r"\b(?:cp|mv)\b(?:\s+-[\w-]+)*\s+\S+\s+([^\s;|&()<>]+)")
_SED_I = re.compile(r"\bsed\b[^;|&]*?-i\S*\s+(?:'[^']*'|\"[^\"]*\")\s+([^\s;|&()<>]+)")
# PowerShell 파일 출력 cmdlet
_PS_OUTFILE = re.compile(
    r"\b(?:Out-File|Set-Content|Add-Content)\b(?:\s+-\w+(?::\S+)?)*\s+(?:-(?:File)?Path\s+)?"
    r"('[^']+'|\"[^\"]+\"|[^\s;|&()<>]+)", re.IGNORECASE)
_PS_COPY_MOVE = re.compile(
    r"\b(?:Copy-Item|Move-Item)\b\s+\S+\s+(?:-Destination\s+)?"
    r"('[^']+'|\"[^\"]+\"|[^\s;|&()<>]+)", re.IGNORECASE)


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
    """shell command 문자열에서 출력 경로 후보를 heuristic으로 뽑는다 (Bash+PowerShell)."""
    out = set()
    for pat in (_REDIRECT, _CP_MV, _SED_I, _PS_OUTFILE, _PS_COPY_MOVE):
        for m in pat.finditer(command):
            p = m.group(1).strip("'\"")
            if (p and not p.startswith(("-", "$", "/dev/")) and p not in ("&1", "&2")
                    and p.lower() != "nul"):
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
        "file_ops": [],  # Write/Edit 기록 원본 — Git 없는 복원 증거 (§4.1, §7)
        "read_paths": set(),   # Read로 접근한 파일 — 리뷰 workload 실측 (§5.4)
        "search_count": 0,     # Grep/Glob 호출 수
        "final_answer": "",    # 마지막 assistant 텍스트 응답 — 답변형 산출물 (§5.4)
    }
    for rec in _iter_json_lines(path):
        if rec.get("type") == "user" and not rec.get("isMeta"):
            sess["task_requests"].extend(_user_texts(rec))
        if rec.get("type") == "assistant":
            msg = rec.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                texts = [b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text"]
                joined = "\n".join(t for t in texts if t).strip()
                if joined:
                    sess["final_answer"] = joined  # 마지막 텍스트 응답이 남는다
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
                        op = {"tool": name, "path": p}
                        if name == "Write":
                            op["content"] = inp.get("content")
                        elif name == "Edit":
                            op["old"] = inp.get("old_string")
                            op["new"] = inp.get("new_string")
                        elif name == "MultiEdit":
                            op["edits"] = [{"old": e.get("old_string"), "new": e.get("new_string")}
                                           for e in inp.get("edits") or []]
                        elif name == "NotebookEdit":
                            op["new"] = inp.get("new_source")
                        sess["file_ops"].append(op)
                elif name == "Read" and isinstance(inp.get("file_path"), str):
                    sess["read_paths"].add(inp["file_path"])
                elif name in ("Grep", "Glob"):
                    sess["search_count"] += 1
                elif name in SHELL_TOOLS and isinstance(inp.get("command"), str):
                    cmd = inp["command"]
                    sess["bash_candidate_paths"] |= bash_candidate_paths(cmd)
                    if re.search(r"(?:^|[;&|]\s*|&\s+)git\s+", " " + cmd):
                        sess["git_commands"].append(cmd)
    sess["timestamps"].sort()
    return sess


def _artifact_signature(sess):
    """세션의 산출물 서명: 건드린 경로를 절대경로로 정규화한 집합.

    절대경로 정규화로 다른 프로젝트의 같은 상대경로(README.md 등)가
    허위 병합되는 것을 원천 차단한다.
    """
    sig = set()
    for p in sess["direct_paths"] | sess["bash_candidate_paths"]:
        if not os.path.isabs(p) and sess["cwd"]:
            p = os.path.join(sess["cwd"], p)
        sig.add(os.path.normcase(os.path.normpath(p)))
    return sig


def group_by_artifacts(sessions, min_common=1):
    """산출물 겹침 기반 세션 grouping (방법론 §13, LLM 미사용).

    두 세션이 같은 파일을 min_common개 이상 건드렸으면 같은 작업(job)으로
    union-find 연결한다. s1∩s2, s2∩s3이면 s1·s3도 한 그룹(이어달리기 작업).
    겹침이 없는 세션(경로 미추출 포함)은 각자 독립 그룹.
    반환: [{"sessions": [...시간순...], "grouping_evidence": [...]}, ...] 시간순.
    """
    n = len(sessions)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    sigs = [_artifact_signature(s) for s in sessions]
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            common = sigs[i] & sigs[j]
            if len(common) >= max(1, min_common):
                union(i, j)
                edges.append((i, j, sorted(common)))

    def _label(s):
        return s["session_id"] or s["file"]

    def _start(s):
        return s["timestamps"][0] if s["timestamps"] else ""

    by_root = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(i)

    groups = []
    for root, idxs in by_root.items():
        members = sorted((sessions[i] for i in idxs), key=_start)
        evidence = [{"sessions": [_label(sessions[i]), _label(sessions[j])],
                     "common_paths": common}
                    for i, j, common in edges if find(i) == root]
        groups.append({"sessions": members, "grouping_evidence": evidence})
    groups.sort(key=lambda g: _start(g["sessions"][0]))
    return groups
