# -*- coding: utf-8 -*-
"""
summarize_match.py — 호출한 클로드의 PID로 그 클로드 설정을 물려받아, 하이쿠로
전처리본(condense JSON)의 서머리 + 펑션/프로덕트 매칭을 낸다.

핵심 보장:
  - 그 클로드의 설정 그대로: PID의 실행파일·cwd·환경변수(CLAUDE_CONFIG_DIR, ANTHROPIC_* 등)를
    읽어 같은 계정·같은 설정으로 띄운다. 중첩 세션 마커(CLAUDECODE 등)만 제거.
  - 모델은 하이쿠(--model haiku). 트랜스크립트 안 만듦(--no-session-persistence).
  - 캐시 안 씀: DISABLE_PROMPT_CACHING=1 (Claude Code가 인식하는 환경변수. 서버 측 캐시
    적중까지 막는다는 보장은 없어 "가능하다면" 수준).
  - 툴 없음(--tools ""), MCP 없음(--strict-mcp-config), 프로젝트 설정·훅 무시(--setting-sources user).
  - 토큰 절감: --system-prompt 한 줄(기본 시스템프롬프트 대체), --effort low, MAX_THINKING_TOKENS=0.
    실측(0.5k 토큰 전처리본, haiku): 기본 입력 14.8k/출력 5.9k($0.046, 57s)
    → 절감 후 입력 8.2k/출력 0.3k($0.012, 4.7s). 남은 입력 8k는 CLI 고정 부담.

입력:
  전처리본  : condense.py 출력 JSON 파일
  펑션 파일 : 조직 정보 JSON (functions.example.json 참조)
              {"org": "...", "functions": [{"name","desc"}...], "products": [{"name","desc"}...]}
출력(JSON):
  {"summary": "...", "functions": {"<펑션>": 비중, ...}, "primary": "...",
   "products": ["..."], "evidence": "...", "meta": {pid, exe, config_dir, model, ...}}

사용:
  python summarize_match.py --pid <claude PID> --condensed c.json --functions org.json [--out r.json]
  python summarize_match.py --pid <PID> --transcript session.jsonl --functions org.json   # 전처리부터
  from summarize_match import summarize_match
  r = summarize_match(pid, "c.json", "org.json")
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from condense import condense, render  # noqa: E402

MODEL = "haiku"
EFFORT = "low"          # 분류·요약엔 긴 사고 불필요 — thinking 토큰 절감
SYSTEM_PROMPT = "You are a concise analyst. Reply with exactly one JSON object and nothing else."  # 기본 시스템프롬프트(≈14k 토큰) 대체
# 중첩 세션 마커 — 게이트웨이 sidecar/InteractiveProcess.js 스크럽 목록과 동일 계열
SCRUB_ENV = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_BRIDGE_SESSION_ID",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "AI_AGENT",
    "ANTHROPIC_MODEL",  # 상위 세션 모델 강제 → 하이쿠 지정이 덮이지 않게
)

PROMPT = """아래 [조직 정보]의 펑션(업무 구분)·프로덕트 목록으로 [세션 기록]을 분석하라.

할 일:
1. summary: 이 세션에서 무엇을 요청받아 무엇을 했고 결과가 뭔지 3~6문장. 쉬운 말로.
2. functions: 각 펑션의 비중(정수, 합계 100). 걸치는 게 정상. 목록 밖 업무는 "기타".
3. primary: 비중 최대 펑션.
4. products: 관련된 프로덕트 이름 목록(없으면 빈 배열). 목록에 있는 이름만.
5. evidence: 판단 근거 한두 문장 (USER 지시, ASSISTANT 설명, META 경로·확장자·툴 중 무엇을 봤는지).

코드는 생략돼 있다. 어떤 파일을 만졌는지는 META.paths/exts 로 판단하라.
반드시 JSON 하나만 출력:
{{"summary": "...", "functions": {{"<펑션>": <정수>, ...}}, "primary": "...", "products": ["..."], "evidence": "..."}}

[조직 정보]
{org}

[세션 기록]
{body}
"""


# ---------- PID → 실행파일·cwd·환경 ----------
def _win_proc_env(pid):
    import ctypes
    import ctypes.wintypes as wt
    import struct

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    nt = ctypes.WinDLL("ntdll")

    class PBI(ctypes.Structure):
        _fields_ = [("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
                    ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_void_p),
                    ("Reserved3", ctypes.c_void_p)]

    def read(h, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
            raise OSError(f"ReadProcessMemory failed: {ctypes.get_last_error()}")
        return buf.raw[:got.value]

    h = k32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
    if not h:
        raise OSError(f"OpenProcess({pid}) failed: {ctypes.get_last_error()}")
    try:
        pbi = PBI()
        rl = wt.ULONG()
        r = nt.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(rl))
        if r:
            raise OSError(f"NtQueryInformationProcess {r:#x}")
        params = struct.unpack("<Q", read(h, pbi.PebBaseAddress + 0x20, 8))[0]
        cd_len, _, cd_ptr = struct.unpack("<HHxxxxQ", read(h, params + 0x38, 16))
        cwd = read(h, cd_ptr, cd_len).decode("utf-16-le")
        env_ptr = struct.unpack("<Q", read(h, params + 0x80, 8))[0]
        env_size = struct.unpack("<Q", read(h, params + 0x3F0, 8))[0]
        raw = read(h, env_ptr, env_size).decode("utf-16-le", errors="replace")
        env = {}
        for item in raw.split("\0"):
            if "=" in item[1:]:
                k, v = item.split("=", 1)
                env[k] = v
        return cwd, env
    finally:
        k32.CloseHandle(h)


def _win_exe(pid):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').ExecutablePath"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    return out or None


def _posix_proc(pid):
    base = Path(f"/proc/{pid}")
    exe = os.readlink(base / "exe")
    cwd = os.readlink(base / "cwd")
    env = {}
    for item in (base / "environ").read_bytes().split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return exe, cwd, env


def inspect_claude(pid):
    """PID → {"exe", "cwd", "env", "config_dir"}. 그 클로드가 쓰는 설정의 실체."""
    if os.name == "nt":
        cwd, env = _win_proc_env(pid)
        exe = _win_exe(pid)
    else:
        exe, cwd, env = _posix_proc(pid)
    if not exe or "claude" not in Path(exe).name.lower():
        # node로 띄운 cli.js 등 — 실행파일 이름에 claude 없으면 PATH의 claude로 폴백
        exe = _find_claude_on_path(env) or exe
    config_dir = env.get("CLAUDE_CONFIG_DIR") or str(Path(env.get("USERPROFILE") or env.get("HOME") or Path.home()) / ".claude")
    return {"exe": exe, "cwd": cwd, "env": env, "config_dir": config_dir}


def _find_claude_on_path(env):
    from shutil import which
    return which("claude", path=env.get("PATH") or env.get("Path"))


def child_env(env):
    e = dict(env)
    for k in SCRUB_ENV:
        e.pop(k, None)
    e["DISABLE_PROMPT_CACHING"] = "1"
    e["MAX_THINKING_TOKENS"] = "0"   # 분류·요약엔 확장 사고 불필요
    return e


# ---------- 호출 ----------
def _extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in response: {text[:200]}")
    return json.loads(m.group(0))


def run_claude(info, prompt, model=MODEL, timeout=600, runner=None):
    """그 클로드 실행파일로 -p 1회. runner 주입 시 실제 CLI 대신 호출(테스트)."""
    if runner:
        return runner(prompt), {}
    cmd = [info["exe"], "-p", "--model", model, "--no-session-persistence",
           "--tools", "", "--strict-mcp-config", "--setting-sources", "user",
           "--system-prompt", SYSTEM_PROMPT, "--effort", EFFORT,
           "--output-format", "json"]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=info["cwd"], env=child_env(info["env"]),
                       shell=(os.name == "nt" and info["exe"].lower().endswith(".cmd")))
    if p.returncode != 0:
        raise RuntimeError(f"claude rc={p.returncode}: {(p.stderr or p.stdout or '')[:400]}")
    try:
        wrap = json.loads(p.stdout)
        text = wrap.get("result", "")
        usage = {k: wrap.get(k) for k in ("model", "total_cost_usd", "usage", "duration_ms", "num_turns") if k in wrap}
        if isinstance(wrap.get("modelUsage"), dict):
            usage["modelUsage"] = wrap["modelUsage"]
    except json.JSONDecodeError:
        text, usage = p.stdout, {}
    return text, usage


def _org_text(org):
    lines = [f"조직: {org.get('org', '')}".rstrip(": ")]
    lines.append("펑션:")
    for f in org.get("functions", []):
        lines.append(f"  - {f['name']}: {f.get('desc', '')}".rstrip(": "))
    if org.get("products"):
        lines.append("프로덕트:")
        for pr in org["products"]:
            lines.append(f"  - {pr['name']}: {pr.get('desc', '')}".rstrip(": "))
    return "\n".join(lines)


def _normalize(raw, org):
    fn_names = [f["name"] for f in org.get("functions", [])] + ["기타"]
    pr_names = {p["name"] for p in org.get("products", [])}
    shares = {}
    for k, v in (raw.get("functions") or {}).items():
        if k in fn_names:
            try:
                shares[k] = max(0, int(round(float(v))))
            except (TypeError, ValueError):
                pass
    tot = sum(shares.values())
    if tot and tot != 100:
        shares = {k: int(round(v * 100 / tot)) for k, v in shares.items()}
    primary = raw.get("primary")
    if primary not in shares and shares:
        primary = max(shares, key=shares.get)
    products = [p for p in (raw.get("products") or []) if p in pr_names]
    return {"summary": str(raw.get("summary", "")).strip(), "functions": shares, "primary": primary,
            "products": products, "evidence": str(raw.get("evidence", "")).strip()}


def summarize_match(pid, condensed_path, functions_path, model=MODEL, runner=None, timeout=600):
    c = json.load(open(condensed_path, encoding="utf-8"))
    org = json.load(open(functions_path, encoding="utf-8"))
    info = inspect_claude(pid)
    prompt = PROMPT.format(org=_org_text(org), body=render(c))
    text, usage = run_claude(info, prompt, model=model, timeout=timeout, runner=runner)
    out = _normalize(_extract_json(text), org)
    out["meta"] = {"pid": pid, "exe": info["exe"], "cwd": info["cwd"], "config_dir": info["config_dir"],
                   "model": model, "no_session_persistence": True, "prompt_caching_disabled": True,
                   "prompt_est_chars": len(prompt), "condense_stats": c.get("stats"), "usage": usage}
    return out


def main(argv):
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    pid = int(opt("--pid") or os.getppid())
    functions = opt("--functions")
    if not functions:
        sys.stderr.write("--functions <org.json> 필수\n")
        return 2
    condensed = opt("--condensed")
    if not condensed:
        transcript = opt("--transcript")
        if not transcript:
            sys.stderr.write("--condensed <c.json> 또는 --transcript <session.jsonl> 필요\n")
            return 2
        start, end = opt("--from"), opt("--to")
        c = condense(transcript, window=(start, end) if (start or end) else None)
        condensed = Path(transcript).with_suffix(".condensed.json")
        json.dump(c, open(condensed, "w", encoding="utf-8"), ensure_ascii=False)
    r = summarize_match(pid, condensed, functions, model=opt("--model", MODEL))
    s = json.dumps(r, ensure_ascii=False, indent=1)
    if opt("--out"):
        open(opt("--out"), "w", encoding="utf-8").write(s)
    sys.stdout.write(s + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
