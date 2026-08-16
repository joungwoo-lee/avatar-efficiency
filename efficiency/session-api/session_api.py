# -*- coding: utf-8 -*-
"""세션 측정 API — 실행된 Claude Code 세션 1개의 AI 효율(speedup) 산정.

speedup = human_min(분자) ÷ agent_min(분모)
  분자: 트랜스크립트에서 완료된 요구사항 복원(§23) → 사람 w/o 생성형AI 견적
        (../human-effort — transcript_requirements + estimate_from_requirements)
  분모: 트랜스크립트에 기록된 동작 단서 × 요율 (LLM 미사용)
        (../agent-effort/transcript_actual — 병렬 서브에이전트는 시간 미가산)

아바타(사전) 측정 API는 ../counterfactual-api. 본 모듈은 사후(세션) 전용.

사용:
    from session_api import measure_session
    r = measure_session(llm, "session.jsonl")
    r["speedup"], r["human"]["p50_min"], r["agent"]["total_min"]
"""
import glob
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (_ROOT / "human-effort" / "requirement-based",
           _ROOT / "human-effort" / "shared",
           _ROOT / "human-effort" / "record-actions",
           _ROOT / "human-effort" / "requirement-actions",
           _ROOT / "agent-effort"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from transcript_requirements import (extract_requirements,  # noqa: E402
                                     normalize_claude_code_jsonl)
from transcript_actual import parse_actions, actual_effort_minutes  # noqa: E402
from agent_effort import load_rates, speedup  # noqa: E402
from estimator import HumanEffortEstimator  # noqa: E402


class JsonRetryLLM:
    """프록시가 불량 JSON을 뱉으면 최대 retries회 재호출하는 래퍼."""

    def __init__(self, inner, retries=2):
        self.inner = inner
        self.retries = retries

    def complete_json(self, prompt, max_tokens):
        last = None
        for _ in range(self.retries + 1):
            try:
                return self.inner.complete_json(prompt, max_tokens)
            except Exception as e:
                last = e
        raise last


def measure_agent_actual(jsonl_path, rates=None, include_subagents=False):
    """분모만: 트랜스크립트 실측 agent_min. LLM 미사용, 결정론적.

    측정 기조: 분모 = "AI를 쓰는 사람의 에포트" + "AI가 실제 소모한 시간".
    - hitl은 단서(지시 건수·산출물 분량) × 요율 추정 — 산출물 검토·후작업은
      세션 밖에서 몰아 할 수 있어 세션 wall-clock으로는 못 잡는다.
    - 서브에이전트는 메인 타임라인과 **병렬**로 돌므로 실제 소모 시간에
      가산하지 않는다(기본 False). include_subagents=True는 자원량 참고용.
    """
    rates = rates or load_rates()
    counts = parse_actions(jsonl_path)
    sub_files = glob.glob(str(Path(jsonl_path).with_suffix("")) + "/subagents/*.jsonl")
    if include_subagents:  # 자원량(토큰·동작 총량) 관점 참고용 — 시간 아님
        for sf in sub_files:
            sc = parse_actions(sf)
            for k in ("tool_calls", "tool_result_words", "assistant_words"):
                counts[k] += sc[k]
    actual = actual_effort_minutes(counts, rates)
    actual["subagent_files"] = len(sub_files)
    actual["subagents_included"] = include_subagents
    return actual


def measure_session(llm, jsonl_path, rates=None, max_chars=12000,
                    include_subagents=False, estimator=None):
    """세션 1개 → 분자·분모·speedup.

    반환: {
      "session": 파일명, "session_id",
      "human": {p50_min, p80_min, requirements[], n_items, unscored, review_required,
                review_reasons},
      "agent": {machine_min, hitl_min, total_min, breakdown, counts, subagent_files},
      "speedup": human_p50 / agent_total (None if agent 0),
      "speedup_vs_hitl": human_p50 / hitl_min (사람 감독시간 대비),
      "first_request": 첫 사용자 지시 요약
    }
    """
    rates = rates or load_rates()
    est = estimator or HumanEffortEstimator(llm)

    actual = measure_agent_actual(jsonl_path, rates, include_subagents)

    norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars)
    req, notes = extract_requirements(llm, norm)
    r = est.estimate_from_requirements(req, norm)

    p50 = r["effort"]["p50_minutes"]
    total = actual["total_min"]
    return {
        "session": Path(jsonl_path).name,
        "session_id": actual["counts"].get("session_id"),
        "human": {
            "p50_min": p50,
            "p80_min": r["effort"]["p80_minutes"],
            "requirements": [(q["requirement_id"], q["title"], q["status"])
                             for q in r["requirements"]],
            "n_items": len(r["work_items"]),
            "unscored": len(r["unscored_items"]),
            "review_required": r["review_required"],
            "review_reasons": r["review_reasons"],
        },
        "agent": {
            "machine_min": actual["machine_min"],
            "hitl_min": actual["hitl_min"],
            "total_min": total,
            "breakdown": actual["breakdown"],
            "counts": {k: v for k, v in actual["counts"].items()
                       if k not in ("first_ts", "last_ts")},
            "subagent_files": actual["subagent_files"],
        },
        "speedup": speedup(p50, total),
        "speedup_vs_hitl": speedup(p50, actual["hitl_min"]),
        "first_request": (norm.split("\n")[0][:120] if norm else ""),
        "notes": notes,
    }


def measure_sessions(llm, jsonl_paths, **kw):
    """배치: 세션별 measure_session. 실패는 {"session", "error"}로 기록하고 계속."""
    results = []
    for p in jsonl_paths:
        try:
            results.append(measure_session(llm, p, **kw))
        except Exception as e:
            results.append({"session": Path(p).name,
                            "error": f"{type(e).__name__}: {e}"})
    return results


def format_report(rows):
    lines = []
    th = ta = 0.0
    for r in rows:
        if "error" in r:
            lines.append(f"{r['session'][:12]}  FAIL: {r['error'][:70]}")
            continue
        h, a = r["human"], r["agent"]
        th += h["p50_min"]
        ta += a["total_min"]
        flag = " [review]" if h["review_required"] else ""
        lines.append(
            f"{r['session'][:12]}  human={h['p50_min']:>7.1f}min  "
            f"agent={a['total_min']:>7.1f}min "
            f"({a['machine_min']:.1f}+{a['hitl_min']:.1f})  "
            f"speedup={r['speedup'] or 0:>5.2f}x{flag}")
        for q in h["requirements"][:3]:
            lines.append(f"              req: {q[1][:64]} [{q[2]}]")
    ok = [r for r in rows if "error" not in r]
    if ok and ta > 0:
        lines.append(f"합산: human={th:.0f}min  agent={ta:.1f}min  "
                     f"overall speedup={th / ta:.2f}x  ({len(ok)}/{len(rows)} 세션)")
    return "\n".join(lines)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: python session_api.py <session.jsonl> [...] [--json] [--actual-only]",
              file=sys.stderr)
        return 2
    if "--actual-only" in argv:  # 분모 실측만 — LLM 불필요
        for p in paths:
            a = measure_agent_actual(p)
            print(f"{Path(p).name}: agent={a['total_min']}min "
                  f"(기계 {a['machine_min']} + hitl {a['hitl_min']})")
        return 0
    from onprem_llm_sim import OnpremLLM
    llm = JsonRetryLLM(OnpremLLM())
    rows = measure_sessions(llm, paths)
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(format_report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
