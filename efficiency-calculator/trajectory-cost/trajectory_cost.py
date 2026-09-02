"""trajectory_cost — Claude Code 트랜스크립트(JSONL)에서 세션 1건의 실제 LLM 호출 비용을 계산.

- 부모 세션 + 모든 서브에이전트(sidechain) 호출을 재귀 합산
- 호출별 모델을 각각 적용 (부모 Opus / 서브 Sonnet 혼재 대응)
- 캐시 토큰은 write-5m 1.25x / write-1h 2.0x / read 0.1x 로 별도 단가 적용
- message.id 기준 중복 제거 (스트리밍 중간 레코드 과대계상 방지)
- 온프렘(사내 구축) 모델 호출은 provider="onprem" 으로 분리하고 비용 0
- <synthetic> 등 free 모델 레코드(실제 LLM 호출 아님)는 by_provider["free"] 에만 남기고 호출 수 집계에서 제외
- 레코드의 Claude Code 버전 범위(min_version/max_version)를 출력해 포맷 드리프트 추적

지표 이름은 llm_cost_usd 대신 trajectory_cost_usd 로 두는 편이 정확하다.
= "해당 trajectory 에서 관측 가능한 모델 호출 비용". Claude Code 내부 background
호출(제목 생성 등) 일부는 JSONL 에 남지 않아 /usage 값과 소폭 차이가 날 수 있다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

RATES_PATH = Path(__file__).with_name("rates.json")
DEFAULT_PROJECTS_ROOT = Path(
    os.environ.get("CLAUDE_PROJECTS_ROOT", Path.home() / ".claude" / "projects")
)

# 날짜 접미사 제거: claude-haiku-4-5-20251001 -> claude-haiku-4-5
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def load_rates(path: Path | str | None = None) -> dict:
    with open(path or RATES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# 모델 분류
# --------------------------------------------------------------------------

def normalize_model(model: str) -> str:
    return _DATE_SUFFIX.sub("", (model or "").strip())


def classify_model(model: str, rates: dict, onprem_models: Iterable[str] = ()) -> str:
    """provider 판정: 'api' | 'onprem' | 'free' | 'unknown'."""
    raw = (model or "").strip()
    norm = normalize_model(raw)
    if raw in rates.get("free_models", []) or norm in rates.get("free_models", []):
        return "free"

    extra = {m.strip().lower() for m in onprem_models if m and m.strip()}
    extra |= {
        m.strip().lower()
        for m in os.environ.get("TRAJECTORY_ONPREM_MODELS", "").split(",")
        if m.strip()
    }
    low = norm.lower()
    if low in extra or raw.lower() in extra:
        return "onprem"
    if norm in rates["models"]:
        return "api"
    for pat in rates.get("onprem_patterns", []):
        if re.search(pat, low):
            return "onprem"
    return "unknown"


# --------------------------------------------------------------------------
# 레코드 추출
# --------------------------------------------------------------------------

@dataclass
class Call:
    message_id: str
    request_id: str | None
    model: str
    agent_id: str | None          # None = 부모(메인) 에이전트
    agent_type: str | None        # attributionAgent (general-purpose 등)
    is_sidechain: bool
    speed: str | None             # standard | fast
    input_tokens: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output_tokens: int = 0
    web_search_requests: int = 0
    web_fetch_requests: int = 0
    source: str = ""
    version: str | None = None    # 레코드의 Claude Code 버전 (드리프트 추적용)

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.cache_write_5m + self.cache_write_1h
                + self.cache_read + self.output_tokens)


def transcript_files(session: str | Path, projects_root: Path | None = None) -> list[Path]:
    """세션 ID 또는 .jsonl 경로 -> [부모 파일, 서브에이전트 파일...]"""
    root = Path(projects_root or DEFAULT_PROJECTS_ROOT)
    p = Path(session)
    if p.suffix == ".jsonl" and p.exists():
        parent = p
    else:
        sid = p.stem if p.suffix == ".jsonl" else str(session)
        matches = sorted(root.glob("*/" + sid + ".jsonl"))
        if not matches:
            raise FileNotFoundError("transcript not found for session %r under %s" % (sid, root))
        parent = matches[0]

    files = [parent]
    side_dir = parent.with_suffix("")           # <프로젝트>/<세션ID>/
    if side_dir.is_dir():
        files += sorted(f for f in side_dir.rglob("*.jsonl") if f.is_file())
    return files


def iter_calls(files: Iterable[Path]) -> Iterator[Call]:
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue

                cc = usage.get("cache_creation") or {}
                w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
                w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
                # 구버전(5m/1h 분리 없음) 또는 딕트는 있으나 전부 0 인데 최상위 값만 있는 경우
                # -> 최상위 cache_creation_input_tokens 를 전량 5m 로 간주
                if not cc or (w5 == 0 and w1 == 0):
                    w5 = int(usage.get("cache_creation_input_tokens") or 0)
                stu = usage.get("server_tool_use") or {}

                yield Call(
                    message_id=msg.get("id") or rec.get("uuid") or "",
                    request_id=rec.get("requestId"),
                    model=msg.get("model") or "",
                    agent_id=rec.get("agentId"),
                    agent_type=rec.get("attributionAgent"),
                    is_sidechain=bool(rec.get("isSidechain")),
                    speed=usage.get("speed"),
                    input_tokens=int(usage.get("input_tokens") or 0),
                    cache_write_5m=w5,
                    cache_write_1h=w1,
                    cache_read=int(usage.get("cache_read_input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    web_search_requests=int(stu.get("web_search_requests") or 0),
                    web_fetch_requests=int(stu.get("web_fetch_requests") or 0),
                    source=str(f),
                    version=rec.get("version"),
                )


def dedupe(calls: Iterable[Call]) -> list[Call]:
    """같은 message.id 의 스트리밍 중간 레코드 제거 — 토큰 합이 가장 큰 것만 남긴다."""
    best: dict[str, Call] = {}
    anon: list[Call] = []
    for c in calls:
        key = c.message_id or ""
        if not key:
            anon.append(c)
            continue
        cur = best.get(key)
        if cur is None or c.total_tokens > cur.total_tokens:
            best[key] = c
    return list(best.values()) + anon


# --------------------------------------------------------------------------
# 비용 계산
# --------------------------------------------------------------------------

def call_cost(call: Call, rates: dict, onprem_models: Iterable[str] = ()) -> tuple[float, str]:
    """(USD, provider). onprem/free/unknown 은 0.0 USD."""
    provider = classify_model(call.model, rates, onprem_models)
    if provider != "api":
        return 0.0, provider

    spec = rates["models"][normalize_model(call.model)]
    if call.speed == "fast" and "fast" in spec:
        spec = spec["fast"]
    mult = rates["cache_multipliers"]
    inp, out = spec["input"], spec["output"]

    # 캐시 단가: rates.json 에 직접 적혀 있으면 그 값, 없으면 input x 배수
    w5_rate = spec.get("cache_write_5m", inp * mult["write_5m"])
    w1_rate = spec.get("cache_write_1h", inp * mult["write_1h"])
    rd_rate = spec.get("cache_read", inp * mult["read"])

    usd = (
        call.input_tokens * inp
        + call.cache_write_5m * w5_rate
        + call.cache_write_1h * w1_rate
        + call.cache_read * rd_rate
        + call.output_tokens * out
    ) / 1_000_000

    st = rates.get("server_tools_usd", {})
    usd += call.web_search_requests * st.get("web_search_per_1k", 0.0) / 1000
    usd += call.web_fetch_requests * st.get("web_fetch_per_1k", 0.0) / 1000
    return usd, provider


@dataclass
class Bucket:
    calls: int = 0
    input_tokens: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, c: Call, usd: float) -> None:
        self.calls += 1
        self.input_tokens += c.input_tokens
        self.cache_write_5m += c.cache_write_5m
        self.cache_write_1h += c.cache_write_1h
        self.cache_read += c.cache_read
        self.output_tokens += c.output_tokens
        self.cost_usd += usd

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["total_tokens"] = (self.input_tokens + self.cache_write_5m
                             + self.cache_write_1h + self.cache_read + self.output_tokens)
        d["cost_usd"] = round(self.cost_usd, 6)
        return d


def _ver_key(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\-+]", v))


def _ver_min_max(versions: set[str]) -> tuple[str | None, str | None]:
    if not versions:
        return None, None
    ordered = sorted(versions, key=_ver_key)
    return ordered[0], ordered[-1]


def session_cost(session: str | Path,
                 projects_root: Path | None = None,
                 rates: dict | None = None,
                 onprem_models: Iterable[str] = ()) -> dict[str, Any]:
    """세션 1건의 trajectory 비용. 부모 + 서브에이전트 전부 포함."""
    rates = rates or load_rates()
    files = transcript_files(session, projects_root)
    calls = dedupe(iter_calls(files))

    total, main, sub = Bucket(), Bucket(), Bucket()
    by_model: dict[str, Bucket] = {}
    by_agent: dict[str, Bucket] = {}
    by_provider: dict[str, Bucket] = {}
    unknown_models: set[str] = set()
    versions: set[str] = set()

    for c in calls:
        if c.version:
            versions.add(str(c.version))
        usd, provider = call_cost(c, rates, onprem_models)
        if provider == "unknown":
            unknown_models.add(c.model)
        by_provider.setdefault(provider, Bucket()).add(c, usd)
        if provider == "free":
            # <synthetic> 등 실제 LLM 호출이 아닌 레코드: by_provider["free"] 에만 남기고
            # total/main/subagents/by_model/by_agent 카운트에서는 제외
            continue
        total.add(c, usd)
        (sub if (c.is_sidechain or c.agent_id) else main).add(c, usd)
        by_model.setdefault(c.model or "(none)", Bucket()).add(c, usd)
        akey = (c.agent_type or "agent") + ":" + c.agent_id if c.agent_id else "main"
        by_agent.setdefault(akey, Bucket()).add(c, usd)

    return {
        "session_id": Path(files[0]).stem,
        "files": [str(f) for f in files],
        "subagent_files": len(files) - 1,
        "min_version": _ver_min_max(versions)[0],
        "max_version": _ver_min_max(versions)[1],
        "trajectory_cost_usd": round(total.cost_usd, 6),
        "total": total.as_dict(),
        "main_agent": main.as_dict(),
        "subagents": sub.as_dict(),
        "by_model": {k: v.as_dict() for k, v in sorted(by_model.items(), key=lambda kv: -kv[1].cost_usd)},
        "by_agent": {k: v.as_dict() for k, v in sorted(by_agent.items(), key=lambda kv: -kv[1].cost_usd)},
        "by_provider": {k: v.as_dict() for k, v in by_provider.items()},
        "onprem": (by_provider["onprem"] if "onprem" in by_provider else Bucket()).as_dict(),
        "warnings": (
            ["unpriced model treated as $0: " + m for m in sorted(unknown_models)]
            + ["일부 background 호출(제목 생성 등)은 트랜스크립트에 남지 않아 /usage 와 소폭 차이 가능"]
        ),
    }


def session_cost_usd(session: str | Path,
                     projects_root: Path | None = None,
                     onprem_models: Iterable[str] = ()) -> float:
    """세션 ID 또는 트랜스크립트 .jsonl 경로 -> 달러(float) 한 개.

    서브에이전트 포함, 온프렘 모델 호출은 0원. 분해가 필요하면 session_cost() 를 쓴다.
    """
    return session_cost(session, projects_root=projects_root,
                        onprem_models=onprem_models)["trajectory_cost_usd"]


def project_cost(project_dir: str | Path,
                 rates: dict | None = None,
                 onprem_models: Iterable[str] = ()) -> dict[str, Any]:
    """프로젝트 폴더의 모든 세션 합계."""
    rates = rates or load_rates()
    pdir = Path(project_dir)
    sessions = [session_cost(f, rates=rates, onprem_models=onprem_models)
                for f in sorted(pdir.glob("*.jsonl"))]
    return {
        "project_dir": str(pdir),
        "sessions": len(sessions),
        "trajectory_cost_usd": round(sum(s["trajectory_cost_usd"] for s in sessions), 6),
        "detail": sessions,
    }


def _fmt(d: dict) -> str:
    t = d["total"]
    lines = [
        "session %s  (서브에이전트 파일 %d개)" % (d["session_id"], d["subagent_files"]),
        "  비용 합계        $%.4f" % d["trajectory_cost_usd"],
        "    메인 에이전트  $%.4f  (%d calls)" % (d["main_agent"]["cost_usd"], d["main_agent"]["calls"]),
        "    서브에이전트   $%.4f  (%d calls)" % (d["subagents"]["cost_usd"], d["subagents"]["calls"]),
        "    온프렘(무료)   $%.4f  (%d calls, %s tok)" % (
            d["onprem"]["cost_usd"], d["onprem"]["calls"], format(d["onprem"]["total_tokens"], ",")),
        "  토큰  in=%s cw5m=%s cw1h=%s cread=%s out=%s" % (
            format(t["input_tokens"], ","), format(t["cache_write_5m"], ","),
            format(t["cache_write_1h"], ","), format(t["cache_read"], ","),
            format(t["output_tokens"], ",")),
        "  모델별:",
    ]
    for m, b in d["by_model"].items():
        lines.append("    %-32s $%9.4f  %4d calls  %12s tok"
                     % (m, b["cost_usd"], b["calls"], format(b["total_tokens"], ",")))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    try:  # Windows cp949 콘솔에서 한글 깨짐 방지
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Claude Code 세션 trajectory 비용 계산 (서브에이전트 포함)")
    ap.add_argument("session", help="세션 ID / 트랜스크립트 .jsonl 경로 / (--project 시) 프로젝트 폴더")
    ap.add_argument("--project", action="store_true", help="인자를 프로젝트 폴더로 보고 전체 세션 합계")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--onprem-model", action="append", default=[],
                    help="온프렘 모델 ID (반복 가능, 비용 0 처리)")
    a = ap.parse_args(argv)

    if a.project:
        out = project_cost(a.session, onprem_models=a.onprem_model)
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("%s  세션 %d개  합계 $%.4f" % (out["project_dir"], out["sessions"], out["trajectory_cost_usd"]))
            for s in out["detail"]:
                print("  %s  $%.4f" % (s["session_id"], s["trajectory_cost_usd"]))
        return 0

    out = session_cost(a.session, onprem_models=a.onprem_model)
    print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else _fmt(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
