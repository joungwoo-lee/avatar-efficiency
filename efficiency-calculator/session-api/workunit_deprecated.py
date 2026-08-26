# -*- coding: utf-8 -*-
"""[폐기] workunit 방식 세션 측정 — 참고 보관용.

분자를 Work Unit(산출물 단위 × 카탈로그 → Monte Carlo P50/P80)으로 계산하던
구 세션 측정. 신구 대조 실험(CHANGELOG §20)에서 행동×요율(req-actions) 방식이
세션 측정 기본으로 확정되며 폐기됐다. 현행 API는 session_api.measure_session
(human="req-actions" 기본, "record-actions" 교차확인).

이 모듈은 재현·감사 목적으로만 남긴다. 신규 코드에서 import 금지.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (_ROOT / "human-effort" / "requirement-based",
           _ROOT / "human-effort" / "shared",
           _ROOT / "human-effort" / "requirement-actions",
           _ROOT / "agent-effort"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from transcript_requirements import (extract_requirements,  # noqa: E402
                                     normalize_claude_code_jsonl)
from requirement_actions import collect_record_stats  # noqa: E402
from agent_effort import load_rates, speedup  # noqa: E402
from estimator import HumanEffortEstimator  # noqa: E402
from session_api import measure_agent_actual, is_trivial_session  # noqa: E402


def measure_session_workunit(llm, jsonl_path, rates=None, max_chars=12000,
                             include_subagents=False, estimator=None,
                             force=False):
    """[폐기] 세션 1개 → workunit 분자 + 실측 분모 → speedup."""
    rates = rates or load_rates()
    est = estimator or HumanEffortEstimator(llm)

    stats = collect_record_stats(jsonl_path)
    if is_trivial_session(stats) and not force:
        return {"session": Path(jsonl_path).name,
                "excluded": True,
                "reason": (f"초소형 세션 — 검토·입력 {stats['reviewed_words'] + stats['input_words']}단어, "
                           f"산출물 {stats['artifact_words']}단어 (기준 미달). "
                           "측정 시 역부풀림 확인돼 제외. force=True로 강제 측정 가능"),
                "record_stats": stats}

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
