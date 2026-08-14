# -*- coding: utf-8 -*-
"""로컬 결정론 층 2b — Git 없는 프로젝트의 filesystem 증거 복원 (LLM 미사용).

방법론 §4.3~§4.4, §5.2~§5.3, §7:
  - trajectory의 Write content / Edit old·new 기록이 before/after 증거다.
  - 현재 파일과 대조해 "trajectory의 마지막 기록과 현재 파일이 일치"하면
    최종 artifact로 확정한다 (§5.3 우선순위 4).
  - 검증 안 되는 변경은 지어내지 않고 confidence를 낮추거나 unresolved.
  - 복원 상태: 전부 검증 → HIGH_CONFIDENCE, 일부 → PARTIAL, 없음 → UNRECOVERABLE.
"""
import os
from pathlib import Path

_MAX_TEXT = 4000

FILESYSTEM_END = "FILESYSTEM"


def _norm(path, cwd):
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    return os.path.normcase(os.path.normpath(path))


def _display(path, project_root):
    try:
        return Path(path).resolve().relative_to(Path(project_root).resolve()).as_posix()
    except (ValueError, OSError):
        return path


def _verify(ops, current):
    """마지막 기록이 현재 파일에 반영되어 있는가."""
    last = ops[-1]
    if last["tool"] == "Write" and last.get("content") is not None:
        return current == last["content"]
    if last["tool"] == "Edit" and last.get("new"):
        ok = last["new"] in current
        if ok and last.get("old"):
            ok = last["old"] not in current  # 원복되지 않았는지
        return ok
    if last["tool"] == "MultiEdit" and last.get("edits"):
        return all(e["new"] in current for e in last["edits"] if e.get("new"))
    if last["tool"] == "NotebookEdit" and last.get("new"):
        return last["new"] in current
    return False


def _pseudo_diff(ops):
    """Edit old/new 기록으로 사람이 읽을 수 있는 근사 diff를 만든다."""
    out = []
    for op in ops:
        pairs = ([{"old": op.get("old"), "new": op.get("new")}] if op["tool"] == "Edit"
                 else op.get("edits") or [])
        for e in pairs:
            if e.get("old"):
                out.append("- " + e["old"])
            if e.get("new"):
                out.append("+ " + e["new"])
    return "\n".join(out)[:_MAX_TEXT]


def resolve_without_git(sessions, project_root):
    """trajectory file_ops + 현재 filesystem 대조 → (states, artifacts, transient, unresolved)."""
    ops_by_path = {}
    for s in sessions:
        for op in s["file_ops"]:
            ops_by_path.setdefault(_norm(op["path"], s["cwd"]), []).append(op)

    artifacts, transient, unresolved = [], [], []
    verified_n = 0
    for path, ops in sorted(ops_by_path.items()):
        rel = _display(path, project_root)
        p = Path(path)
        if not p.exists():
            transient.append(rel)  # 건드렸지만 현재 없음 — 최종 산출물 제외
            continue
        try:
            current = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            unresolved.append(f"{rel} (읽기 실패: {e})")
            continue
        verified = _verify(ops, current)
        if verified:
            verified_n += 1
        created = ops[0]["tool"] == "Write"
        art = {
            "path": rel,
            "status": "A" if created else "M",
            "attribution": "DIRECT_NET",
            "evidence_sources": ["trajectory_" + ops[-1]["tool"].lower(),
                                 "current_file_match" if verified else "current_file_mismatch"],
            "confidence": 0.95 if verified else 0.5,
        }
        if created:
            art["content"] = current[:_MAX_TEXT]
        else:
            art["diff"] = _pseudo_diff(ops) or "(변경 내용 기록 없음)"
        if not verified:
            art["note"] = "세션 이후 파일이 다시 수정되었을 수 있음 — trajectory 마지막 기록과 현재 파일 불일치"
        artifacts.append(art)

    # Bash 후보는 before hash 없이는 실제 변경을 확정할 수 없다 (§4.2 교차검증 원칙)
    for s in sessions:
        for p in sorted(s["bash_candidate_paths"]):
            n = _norm(p, s["cwd"])
            if n not in ops_by_path and Path(n).exists():
                unresolved.append(f"{_display(n, project_root)} (BASH 후보: before 증거 없어 변경 확정 불가)")

    if not artifacts:
        recovery, note = "UNRECOVERABLE", "trajectory 편집 기록으로 확정 가능한 최종 산출물이 없음"
    elif verified_n == len(artifacts):
        recovery, note = "HIGH_CONFIDENCE", "직접 tool 기록과 최종 파일 일치 (§14)"
    else:
        recovery, note = "PARTIAL", f"artifact {len(artifacts)}개 중 {verified_n}개만 현재 파일과 일치 — 부분값"

    states = {"base": "TRAJECTORY_EVIDENCE", "end": FILESYSTEM_END,
              "recovery": recovery, "note": note}
    return states, artifacts, transient, unresolved


def resolve_answer_artifact(sessions, project_root):
    """답변형 산출물 복원 (§5.4) — 리뷰·분석·답변 세션용.

    산출물 = job 내 마지막 유효 assistant 답변 (transcript 원본이라 복원 불확실성 없음).
    Read/Grep 기록에서 읽기 workload 실측치를 함께 뽑는다 — LLM이 읽기량을
    지어내지 않고 이 수치를 쓰게 한다.
    반환: (states, artifact) — 답변이 없으면 (None, None).
    """
    answer = ""
    for s in sessions:  # 시간순 — 마지막 세션의 최종 답변이 남는다
        if s.get("final_answer"):
            answer = s["final_answer"]
    if not answer:
        return None, None

    read_paths = set()
    search_count = 0
    for s in sessions:
        read_paths |= {_norm(p, s["cwd"]) for p in s.get("read_paths", set())}
        search_count += s.get("search_count", 0)
    read_loc = 0
    for p in sorted(read_paths):
        try:
            f = Path(p)
            if f.is_file() and f.stat().st_size < 2_000_000:
                read_loc += sum(1 for ln in f.read_text(encoding="utf-8", errors="replace")
                                .splitlines() if ln.strip())
        except OSError:
            continue

    artifact = {
        "path": "(대화 답변)",
        "type": "answer",
        "status": "A",
        "attribution": "TRANSCRIPT",
        "evidence_sources": ["trajectory_final_assistant_message"],
        "confidence": 0.95,
        "content": answer[:_MAX_TEXT],
        "review_evidence": {
            "files_read": len(read_paths),
            "read_loc_total": read_loc,
            "search_count": search_count,
        },
    }
    states = {"base": "TRAJECTORY_EVIDENCE", "end": "TRANSCRIPT",
              "recovery": "HIGH_CONFIDENCE",
              "note": "산출물 = 대화 최종 답변 (파일 편집 없음, transcript 원본)"}
    return states, artifact
