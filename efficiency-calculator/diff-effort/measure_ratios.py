# -*- coding: utf-8 -*-
"""저장소에서 보정 계수를 **실측**한다 — `--mix` · `--comment-ratio` ·
`--generated-ratio` 에 넣을 값을 만든다.

csv_report.py 의 보정 계수는 기본이 꺼져 있다. 추정치를 기본값으로
박으면 그게 또 하나의 근거 없는 seed 가 되기 때문이다. 대신 이 도구로
**한 번 재서** 넣는다. 재고 나면 그 계수는 추정이 아니라 실측이다.

세 값을 각각 다른 데서 잰다:

  구성비        git log --numstat 의 diff 라인을 확장자로 코드/문서/데이터
                로 갈라 비중을 낸다 (자동생성물은 빼고 센다).
                **라인 기준**이다 — README §2.5 가 예시로 드는 44/31.5/24.4
                는 Claude Code 세션 트랜스크립트의 Write/Edit 단어를 집계한
                실측이라 **단어 기준**이고 단위가 다르다. 이 도구가 내는
                라인 기준 값을 쓰는 쪽이 맞다.
  자동생성물    같은 diff 라인 중 경로 규칙에 걸린 몫의 비중
  주석·빈 줄    현재 체크아웃의 코드 파일에서 잰다. `cloc` 이 PATH 에
                있으면 cloc 결과를 쓰고, 없으면 내장 계수기로 근사한다

    python measure_ratios.py /path/to/repo
    python measure_ratios.py repo1 repo2 --since 2025-01-01
    python measure_ratios.py /path/to/repo --author someone@corp.com --json

출력 맨 아래에 그대로 복사해 붙일 플래그 한 줄이 나온다.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# ../human-effort/requirement-actions/requirement_actions.py 의 write_kind 와
# 같은 분류다. 그 모듈은 폴더명에 하이픈이 있어 import 가 안 되므로 옮겨 적었다.
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".c", ".h", ".cpp", ".hpp",
            ".cc", ".cs", ".java", ".go", ".rs", ".rb", ".php", ".sql",
            ".pddl", ".vhd", ".v", ".sv", ".scala", ".kt", ".swift", ".lua",
            ".r", ".m", ".sh", ".bash", ".ps1", ".bat", ".mjs", ".cjs"}
DATA_EXT = {".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv", ".toml",
            ".ini", ".cfg", ".conf", ".env", ".xml", ".lock", ".properties"}
DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".adoc", ".html", ".htm",
           ".css", ".scss", ".tex"}

# 자동생성물 — 사람이 치지 않은 줄. 경로 규칙으로만 판정한다.
GENERATED_PAT = re.compile(
    r"(^|/)(node_modules|vendor|third_party|dist|build|out|target|"
    r"__pycache__|\.next|\.venv|coverage|__snapshots__|migrations|"
    r"generated|gen|autogen)/|"
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|"
    r"Cargo\.lock|Gemfile\.lock|composer\.lock|go\.sum)$|"
    r"\.(min|bundle|generated|pb|g)\.[a-z0-9]+$|"
    r"\.(snap|map|lock)$",
    re.IGNORECASE)

# 주석 표기 — 내장 계수기용. 정확한 값이 필요하면 cloc 을 깔면 된다.
HASH = {".py", ".sh", ".bash", ".rb", ".yaml", ".yml", ".toml", ".ini",
        ".cfg", ".conf", ".r", ".ps1"}
SLASH = {".js", ".jsx", ".ts", ".tsx", ".c", ".h", ".cpp", ".hpp", ".cc",
         ".cs", ".java", ".go", ".rs", ".php", ".scala", ".kt", ".swift",
         ".m", ".v", ".sv", ".mjs", ".cjs", ".css", ".scss"}
DASH = {".sql", ".lua", ".vhd", ".adb", ".ads"}


def path_kind(path):
    """경로 -> "code" | "doc" | "data" | "other"."""
    ext = os.path.splitext(path)[1].lower()
    if ext in CODE_EXT:
        return "code"
    if ext in DATA_EXT:
        return "data"
    if ext in DOC_EXT:
        return "doc"
    return "other"


def is_generated(path):
    """자동생성물인가 — 경로 규칙만으로 판정."""
    return bool(GENERATED_PAT.search(path.replace("\\", "/")))


def _resolve_rename(path):
    """numstat 의 rename 표기를 새 경로로 편다.

    "src/{old => new}/a.py" -> "src/new/a.py"
    "old.py => new.py"      -> "new.py"
    """
    if "=>" not in path:
        return path
    m = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", path)
    if m:
        pre, _old, new, post = m.groups()
        return (pre + new + post).replace("//", "/")
    return path.split("=>")[-1].strip()


def _git(repo, args):
    out = subprocess.run(["git", "-C", repo] + args, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError("git %s 실패: %s"
                           % (" ".join(args), (out.stderr or "").strip()))
    return out.stdout


def scan_diff(repo, since=None, until=None, author=None):
    """git log --numstat -> 종류별·생성물 라인 집계."""
    args = ["log", "--numstat", "--no-merges", "--pretty=tformat:"]
    if since:
        args += ["--since", since]
    if until:
        args += ["--until", until]
    if author:
        args += ["--author", author]
    kind = {"code": 0, "doc": 0, "data": 0, "other": 0}
    generated = 0
    total = 0
    for line in _git(repo, args).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        if a == "-" or d == "-":      # 바이너리
            continue
        n = int(a) + int(d)
        if not n:
            continue
        path = _resolve_rename(path.strip())
        total += n
        if is_generated(path):
            generated += n
            continue
        kind[path_kind(path)] += n
    return {"kind": kind, "generated_lines": generated, "total_lines": total}


def _comment_style(ext):
    if ext in HASH:
        return "hash"
    if ext in SLASH:
        return "slash"
    if ext in DASH:
        return "dash"
    return None


def count_comment_blank(text, style):
    """(전체, 주석+빈 줄) — 내장 근사 계수기."""
    total = 0
    noncode = 0
    in_block = False
    in_pydoc = None
    for raw in text.splitlines():
        total += 1
        line = raw.strip()
        if in_block:
            noncode += 1
            if "*/" in line:
                in_block = False
            continue
        if in_pydoc:
            noncode += 1
            if in_pydoc in line:
                in_pydoc = None
            continue
        if not line:
            noncode += 1
            continue
        if style == "hash":
            if line.startswith("#"):
                noncode += 1
                continue
            for q in ('"""', "'''"):
                if line.startswith(q) and line.count(q) == 1:
                    noncode += 1
                    in_pydoc = q
                    break
            else:
                continue
            continue
        if style == "slash":
            if line.startswith("//"):
                noncode += 1
                continue
            if line.startswith("/*"):
                noncode += 1
                if "*/" not in line:
                    in_block = True
                continue
            if line.startswith("*"):
                noncode += 1
                continue
        elif style == "dash" and line.startswith("--"):
            noncode += 1
            continue
    return total, noncode


def scan_comment_builtin(repo):
    """체크아웃된 코드 파일에서 주석·빈 줄 비율을 근사한다."""
    total = 0
    noncode = 0
    files = 0
    for rel in _git(repo, ["ls-files"]).splitlines():
        rel = rel.strip()
        if not rel or is_generated(rel) or path_kind(rel) != "code":
            continue
        style = _comment_style(os.path.splitext(rel)[1].lower())
        if not style:
            continue
        full = os.path.join(repo, rel)
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        t, n = count_comment_blank(text, style)
        total += t
        noncode += n
        files += 1
    return {"lines": total, "comment_blank": noncode, "files": files,
            "source": "builtin"}


def scan_comment_cloc(repo):
    """cloc 이 있으면 그 결과를 쓴다 (내장 계수기보다 정확)."""
    try:
        out = subprocess.run(
            ["cloc", "--json", "--quiet", "--vcs=git", repo],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace")
    except (OSError, ValueError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None
    s = data.get("SUM") or {}
    code = float(s.get("code", 0))
    com = float(s.get("comment", 0))
    blank = float(s.get("blank", 0))
    if code + com + blank <= 0:
        return None
    return {"lines": code + com + blank, "comment_blank": com + blank,
            "files": int(s.get("nFiles", 0)), "source": "cloc"}


def measure(repos, since=None, until=None, author=None, use_cloc=True):
    """저장소들을 훑어 세 계수를 낸다."""
    kind = {"code": 0, "doc": 0, "data": 0, "other": 0}
    generated = 0
    total = 0
    c_lines = 0.0
    c_noncode = 0.0
    c_source = set()
    for repo in repos:
        d = scan_diff(repo, since, until, author)
        for k in kind:
            kind[k] += d["kind"][k]
        generated += d["generated_lines"]
        total += d["total_lines"]

        c = scan_comment_cloc(repo) if use_cloc else None
        if c is None:
            c = scan_comment_builtin(repo)
        c_lines += c["lines"]
        c_noncode += c["comment_blank"]
        c_source.add(c["source"])

    named = kind["code"] + kind["doc"] + kind["data"]
    mix = None
    if named:
        mix = {k: kind[k] / named for k in ("code", "doc", "data")}
    return {
        "repos": list(repos),
        "diff_lines_total": total,
        "diff_lines_by_kind": kind,
        "generated_lines": generated,
        "generated_ratio": (generated / total) if total else 0.0,
        "mix": mix,
        "comment_lines_scanned": int(c_lines),
        "comment_ratio": (c_noncode / c_lines) if c_lines else 0.0,
        "comment_source": "+".join(sorted(c_source)) if c_source else None,
    }


def print_report(m):
    print("[구성비] diff 라인 %d줄 기준 (자동생성물 제외)"
          % (m["diff_lines_by_kind"]["code"] + m["diff_lines_by_kind"]["doc"]
             + m["diff_lines_by_kind"]["data"]))
    if not m["mix"]:
        print("  분류된 라인이 없다 — 기간·저자 조건을 확인할 것")
    else:
        for k, label in (("code", "코드  "), ("doc", "문서  "),
                         ("data", "데이터")):
            print("  %s  %8d줄  %5.1f%%"
                  % (label, m["diff_lines_by_kind"][k], m["mix"][k] * 100))
        if m["diff_lines_by_kind"]["other"]:
            print("  (기타 %d줄은 구성비에서 제외 — 확장자 미분류)"
                  % m["diff_lines_by_kind"]["other"])
    print()
    print("[자동생성물] 전체 diff %d줄 중 %d줄 = %.1f%%"
          % (m["diff_lines_total"], m["generated_lines"],
             m["generated_ratio"] * 100))
    print()
    print("[주석·빈 줄] 코드 %d줄 기준 %.1f%%  (출처: %s)"
          % (m["comment_lines_scanned"], m["comment_ratio"] * 100,
             m["comment_source"]))
    if m["comment_source"] == "builtin":
        print("  내장 근사 계수기다. cloc 을 설치하면 더 정확한 값을 쓴다.")
    print()
    print("[그대로 붙여 쓸 플래그]")
    if m["mix"]:
        print("  --mix %.3f,%.3f,%.3f --comment-ratio %.3f "
              "--generated-ratio %.3f"
              % (m["mix"]["code"], m["mix"]["doc"], m["mix"]["data"],
                 m["comment_ratio"], m["generated_ratio"]))
    else:
        print("  --comment-ratio %.3f --generated-ratio %.3f"
              % (m["comment_ratio"], m["generated_ratio"]))
    print()
    print("주의: 이 값은 잰 저장소·기간의 것이다. 다른 조직·기간에 쓰려면")
    print("      거기서 다시 재라. 리포트에 어떤 조건으로 쟀는지 남길 것.")


def _main():
    p = argparse.ArgumentParser(
        description="저장소에서 diff-effort 보정 계수를 실측한다")
    p.add_argument("repos", nargs="+", help="git 저장소 경로 (여러 개 가능)")
    p.add_argument("--since", default=None, help="git log --since (예: 2025-01-01)")
    p.add_argument("--until", default=None, help="git log --until")
    p.add_argument("--author", default=None, help="git log --author 로 좁히기")
    p.add_argument("--no-cloc", action="store_true",
                   help="cloc 이 있어도 내장 계수기를 쓴다")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    a = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        m = measure(a.repos, a.since, a.until, a.author, not a.no_cloc)
    except (RuntimeError, OSError) as e:
        sys.stderr.write("오류: %s\n" % e)
        return 2

    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print_report(m)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
