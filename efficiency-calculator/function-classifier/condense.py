"""
condense.py — 긴 트랜스크립트(Claude Code jsonl)를 펑션 분류용으로 압축.

원칙 (실측 근거는 README 참조):
  1. 메타 히스토그램: 툴 호출 수·파일 확장자·최상위 디렉터리·대표 경로 (토큰 ≈0)
  2. 사용자 발화 전부 — 노이즈 마커 제거, 발화당 300자 캡 (원본 0.02~0.1%)
  3. 에이전트 발화 전부 — 코드블록 제거, 캡 없음 (원본 0.6~2.4%)
  4. 최종 답변 — 마지막 300자 이상 에이전트 발화 (결론 밀도 최고)
  제외: 툴 결과(파일 읽기·명령 출력, 7~22%), 툴 입력(파일에 쓴 코드, 4~12%), JSON 껍데기(60~70%)

예산 초과 시 3번만 단계적 축소(1000자→500자 캡). 1·2·4는 절대 안 자름.

사용:
  from condense import condense, render
  c = condense("session.jsonl")            # dict
  prompt_text = render(c)                  # LLM 투입용 텍스트
  python condense.py session.jsonl [--budget 60000] [--text]
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_BUDGET_TOKENS = 60000
USER_CAP = 300
ASSISTANT_CAPS = (None, 1000, 500)   # 예산 초과 시 순서대로 시도
MIN_USER_CHARS = 10
FINAL_MIN_CHARS = 300
MAX_PATHS = 30

_NOISE_PREFIX = ("<system-reminder", "<command-", "<local-command", "[Request interrupted", "[Image:")
_RE_SYSREM = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_RE_FENCE = re.compile(r"```.*?```", re.S)
_RE_EXT = re.compile(r"\.([A-Za-z0-9]{1,6})$")
_RE_PATHLIKE = re.compile(r"(?:[A-Za-z]:[\/]|/[a-z]/|~/)[^\s\"'`<>|;,)]+")  # 절대경로만(드라이브·MSYS /c/·~/)


# ---------- 토큰 추정 (라이브러리 없이, 한글 보수 추정) ----------
def estimate_tokens(text):
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    other_n = len(text) - ascii_n
    return int(ascii_n / 4 + other_n / 1.5)


# ---------- jsonl 파싱 ----------
def _iter_records(jsonl_path):
    with open(jsonl_path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _blocks(rec):
    msg = rec.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _clean_user(text):
    text = _RE_SYSREM.sub("", text).strip()
    if not text or text.startswith(_NOISE_PREFIX):
        return None
    if len(text) < MIN_USER_CHARS:
        return None
    return text


def _strip_code(text):
    return _RE_FENCE.sub("[code omitted]", text).strip()


def _path_fields(tool_name, inp):
    if not isinstance(inp, dict):
        return []
    out = []
    for k in ("file_path", "path", "notebook_path"):
        v = inp.get(k)
        if isinstance(v, str):
            out.append(v)
    if tool_name == "Bash" and isinstance(inp.get("command"), str):
        out.extend(_RE_PATHLIKE.findall(inp["command"])[:5])
    return out


def _top_dir(path):
    p = path.replace("\\", "/")
    parts = [x for x in p.split("/") if x]
    if not parts:
        return None
    # 드라이브·홈 루트 건너뛰고 의미 있는 첫 디렉터리
    skip = {"users", "home", "mnt", "tmp"}
    for i, part in enumerate(parts[:-1]):
        if part.lower() in skip or len(part) <= 2:  # 드라이브(c:, /c/)·짧은 토큰
            continue
        if i > 0 and parts[i - 1].lower() == "users":
            continue  # 사용자명
        return part
    return parts[-1]  # 홈 바로 아래 디렉터리 자체가 대상


# ---------- 본체 ----------
def condense(jsonl_path, budget_tokens=DEFAULT_BUDGET_TOKENS):
    jsonl_path = Path(jsonl_path)
    orig_bytes = jsonl_path.stat().st_size

    users, assistants = [], []
    tools, exts, dirs, paths = Counter(), Counter(), Counter(), Counter()
    first_ts = last_ts = None
    n_records = 0

    for rec in _iter_records(jsonl_path):
        n_records += 1
        ts = rec.get("timestamp")
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        rtype = rec.get("type")
        for b in _blocks(rec):
            bt = b.get("type")
            if rtype == "user" and bt == "text":
                t = _clean_user(b.get("text", ""))
                if t:
                    users.append(t)
            elif rtype == "assistant":
                if bt == "text":
                    t = _strip_code(b.get("text", ""))
                    if t:
                        assistants.append(t)
                elif bt == "tool_use":
                    name = b.get("name", "?")
                    tools[name] += 1
                    for p in _path_fields(name, b.get("input")):
                        paths[p] += 1
                        m = _RE_EXT.search(p)
                        if m:
                            exts[m.group(1).lower()] += 1
                        d = _top_dir(p)
                        if d:
                            dirs[d] += 1

    final = next((a for a in reversed(assistants) if len(a) >= FINAL_MIN_CHARS), assistants[-1] if assistants else "")

    meta = {
        "records": n_records,
        "user_turns": len(users),
        "assistant_turns": len(assistants),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "tools": dict(tools.most_common()),
        "exts": dict(exts.most_common()),
        "dirs": dict(dirs.most_common(15)),
        "paths": [p for p, _ in paths.most_common(MAX_PATHS)],
    }
    users_capped = [u[:USER_CAP] for u in users]

    chosen_cap = None
    for cap in ASSISTANT_CAPS:
        a_list = assistants if cap is None else [a[:cap] for a in assistants]
        out = {"meta": meta, "user": users_capped, "assistant": a_list, "final": final}
        tokens = estimate_tokens(render(out))
        chosen_cap = cap
        if tokens <= budget_tokens:
            break

    out["stats"] = {
        "orig_bytes": orig_bytes,
        "out_chars": len(render(out)),
        "est_tokens": tokens,
        "ratio": round(len(render(out)) / max(orig_bytes, 1), 5),
        "assistant_cap": chosen_cap,
        "budget_tokens": budget_tokens,
        "over_budget": tokens > budget_tokens,
    }
    return out


def render(c):
    m = c["meta"]
    lines = ["## META"]
    lines.append(f"turns: user={m['user_turns']} assistant={m['assistant_turns']} span={m.get('first_ts')}..{m.get('last_ts')}")
    lines.append("tools: " + ", ".join(f"{k}={v}" for k, v in m["tools"].items()))
    lines.append("exts: " + ", ".join(f"{k}={v}" for k, v in m["exts"].items()))
    lines.append("dirs: " + ", ".join(f"{k}={v}" for k, v in m["dirs"].items()))
    lines.append("paths:")
    lines.extend(f"  {p}" for p in m["paths"])
    lines.append("\n## USER (all turns)")
    lines.extend(f"U{i+1}> {u}" for i, u in enumerate(c["user"]))
    lines.append("\n## ASSISTANT (all turns, code omitted)")
    lines.extend(f"A{i+1}> {a}" for i, a in enumerate(c["assistant"]))
    lines.append("\n## FINAL ANSWER")
    lines.append(c["final"])
    return "\n".join(lines)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    path = argv[0]
    budget = DEFAULT_BUDGET_TOKENS
    as_text = "--text" in argv
    if "--budget" in argv:
        budget = int(argv[argv.index("--budget") + 1])
    c = condense(path, budget)
    if as_text:
        sys.stdout.write(render(c))
    else:
        json.dump(c, sys.stdout, ensure_ascii=False, indent=1)
    sys.stderr.write(f"\n[condense] {c['stats']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
