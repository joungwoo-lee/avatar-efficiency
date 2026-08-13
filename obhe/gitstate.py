# -*- coding: utf-8 -*-
"""로컬 결정론 층 2 — Git base/end 확정 + net diff + attribution (LLM 미사용).

방법론 §5~§6:
  - trajectory가 "어디를 건드렸는지", Git이 "결국 무엇이 남았는지".
  - 세션별 diff 합산 금지 — base~end 사이 net diff만 계산.
  - 복원 상태: EXACT / HIGH_CONFIDENCE / PARTIAL / UNRECOVERABLE.
    base를 확정할 수 없으면 결과를 지어내지 않고 UNRECOVERABLE로 멈춘다.
"""
import subprocess
from pathlib import Path, PurePosixPath

WORKTREE = "WORKTREE"

ATTRIBUTION_CONFIDENCE = {"DIRECT_NET": 0.99, "BASH_NET": 0.9, "GIT_NET": 0.6}
_MAX_TEXT = 4000  # manifest에 싣는 diff/content 상한 (문자)


class GitStateError(RuntimeError):
    pass


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise GitStateError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def resolve_states(repo, base=None, end=None):
    """§5.2/§5.3 우선순위의 MVP: 사용자 제공 commit 우선, 없으면 판단불가."""
    if not base:
        return {"base": None, "end": None, "recovery": "UNRECOVERABLE",
                "note": "historical_state_unavailable: base commit 미확정"}
    base_sha = _git(repo, "rev-parse", base).strip()
    if end and end != WORKTREE:
        return {"base": base_sha, "end": _git(repo, "rev-parse", end).strip(),
                "recovery": "EXACT", "note": ""}
    return {"base": base_sha, "end": WORKTREE, "recovery": "HIGH_CONFIDENCE",
            "note": "end = 현재 working tree"}


def net_diff(repo, base, end):
    """base~end net 변경 {repo상대경로: status(A/M/D/R)}. end=WORKTREE면 untracked 포함."""
    changed = {}
    args = ["diff", "--name-status", base] if end == WORKTREE else ["diff", "--name-status", base, end]
    for line in _git(repo, *args).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][0]
            path = parts[-1]  # rename이면 마지막이 새 경로
            changed[path] = status
    if end == WORKTREE:
        for path in _git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
            if path:
                changed[path] = "A"
    return changed


def _to_repo_relative(path, repo):
    """trajectory의 절대/상대 경로를 repo 상대 posix 경로로. repo 밖이면 None."""
    try:
        p = Path(path)
        if not p.is_absolute():
            return str(PurePosixPath(path.replace("\\", "/")))
        return p.resolve().relative_to(Path(repo).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def classify(direct_paths, bash_paths, git_changed, repo):
    """§6.1 attribution 결합. 반환: (artifacts, transient, unresolved)."""
    direct = {_to_repo_relative(p, repo) for p in direct_paths} - {None}
    bash = {_to_repo_relative(p, repo) for p in bash_paths} - {None}
    artifacts, transient = [], []
    for path, status in sorted(git_changed.items()):
        if path in direct:
            attribution = "DIRECT_NET"
        elif path in bash:
            attribution = "BASH_NET"
        else:
            attribution = "GIT_NET"  # 자동 포함하지 않고 confidence만 낮게 (§6.1)
        artifacts.append({"path": path, "status": status, "attribution": attribution,
                          "confidence": ATTRIBUTION_CONFIDENCE[attribution]})
    transient = sorted((direct | bash) - set(git_changed))  # 건드렸지만 최종에 없음
    unresolved = sorted({p for p in (direct_paths | bash_paths)
                         if _to_repo_relative(p, repo) is None})
    return artifacts, transient, unresolved


def attach_contents(artifacts, repo, base, end):
    """artifact마다 diff(수정) 또는 content(신규)를 붙인다. 텍스트 상한 적용."""
    for a in artifacts:
        try:
            if a["status"] == "A":
                if end == WORKTREE:
                    text = (Path(repo) / a["path"]).read_text(encoding="utf-8", errors="replace")
                else:
                    text = _git(repo, "show", f"{end}:{a['path']}")
                a["content"] = text[:_MAX_TEXT]
            elif a["status"] == "D":
                a["diff"] = "(deleted)"
            else:
                args = ["diff", base, "--", a["path"]] if end == WORKTREE \
                    else ["diff", base, end, "--", a["path"]]
                a["diff"] = _git(repo, *args)[:_MAX_TEXT]
        except (GitStateError, OSError) as e:
            a["diff"] = f"(읽기 실패: {e})"
            a["confidence"] = min(a["confidence"], 0.3)
    return artifacts
