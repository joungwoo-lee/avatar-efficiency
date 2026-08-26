# -*- coding: utf-8 -*-
"""아바타(사전) 측정 API — 아바타 카드 → speedup. 조합은 인자로만 지정.

사전 측정의 조합 입구 (구 efficiency/api.py의 estimate_avatar 이동, §22):
    estimate_avatar(llm, card_text, human=..., agent=..., calls=...)

분자(human) 방식:
    "req-actions" (기본) 요구사항·행동: 사람 행동 × 단가, 숫자는 닻
    "workunit"           요구사항·산출물 → P50/P80 (분포 필요 시)
분모(agent) 방식:
    "agent-llm"   (유일) AI+감독 행동 × 단가

호출 병합(방식이 아님): 기본 조합(req-actions + agent-llm) + calls="single"이면
두 방법론을 한 프롬프트로 묶어 LLM 1회에 처리 (paths.estimate_paths,
integ-spec §3). calls="staged"면 각자 따로 호출 — 감사·재처리 가능.

구 시스템 drop-in 계약(estimate_task)은 compat.py.
사후(세션) 측정은 ../session-api (req_actions_api / record_actions_api).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (_HERE,
           _ROOT / "human-effort" / "requirement-based",
           _ROOT / "human-effort" / "requirement-actions",
           _ROOT / "human-effort" / "shared",
           _ROOT / "agent-effort"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_effort import load_rates, estimate_agent_min, speedup  # noqa: E402
from paths import estimate_paths  # noqa: E402
from estimator import HumanEffortEstimator, validate_requirements_output  # noqa: E402
from prompts import build_prompt_a_avatar  # noqa: E402
from requirement_actions import (estimate_actions_from_requirements,  # noqa: E402
                                 estimate_actions_single)


def _extract_avatar_todos(llm, card_text, max_tokens=8000):
    raw = llm.complete_json(build_prompt_a_avatar(card_text), max_tokens)
    req, notes, fatal = validate_requirements_output(raw)
    if fatal:
        raise ValueError("할일 변환 실패: " + "; ".join(notes))
    return req, notes


def estimate_avatar(llm, card_text, human="req-actions", agent="agent-llm",
                    rates=None, calls="single"):
    """사전 측정: 아바타 카드 → speedup. 조합은 인자로만 지정.

    기본(req-actions + agent-llm + calls="single")은 두 방법론을 한 프롬프트로
    묶어 LLM 1회에 처리한다(호출 병합, integ-spec §3). calls="staged"면 각자
    따로 호출 — 방법론과 결과 원리는 동일, 감사·재처리 가능."""
    rates = rates or load_rates()
    notes = []

    # 호출 병합: 같은 방법론 쌍을 한 프롬프트로 — 방식이 아니라 호출 최적화
    if calls == "single" and human == "req-actions" and agent == "agent-llm":
        pp = estimate_paths(llm, card_text, rates)
        return {"input": "avatar_card",
                "human": {"min": pp["human_min"], "p80_min": None,
                          "method": "req-actions", "merged_call": True},
                "agent": {"total_min": pp["agent_min"],
                          "ai_min": pp["agent_ai_min"],
                          "hitl_min": pp["agent_human_min"],
                          "method": "agent-llm", "merged_call": True},
                "speedup": speedup(pp["human_min"], pp["agent_min"]),
                "notes": pp["notes"]}

    # ---- 분모
    if agent == "agent-llm":
        ap = estimate_agent_min(llm, card_text, rates)
        a = {"total_min": ap["agent_min"], "ai_min": ap["agent_ai_min"],
             "hitl_min": ap["agent_human_min"], "method": "agent-llm"}
        notes += ap["notes"]
    else:
        raise ValueError(f"사전 측정에서 지원하지 않는 agent 방식: {agent}")

    # ---- 분자
    if human == "workunit":
        mode = "single" if calls == "single" else "two_pass"
        r = HumanEffortEstimator(llm, mode=mode).estimate(card_text)
        h = {"min": r["effort"]["p50_minutes"], "p80_min": r["effort"]["p80_minutes"],
             "method": "workunit", "review_required": r["review_required"]}
        notes += r["warnings"] + r["notes"]
    elif human == "req-actions":
        if calls == "single":
            ra = estimate_actions_single(llm, card_text, rates=rates)
        else:
            req, n = _extract_avatar_todos(llm, card_text)
            notes += n
            ra = estimate_actions_from_requirements(llm, req, rates=rates)
        h = {"min": ra["human_min"], "p80_min": None, "method": "req-actions",
             "anchors": ra["anchors"]}
        notes += ra["notes"]
    else:
        raise ValueError(f"사전 측정에서 지원하지 않는 human 방식: {human}")

    return {"input": "avatar_card", "human": h, "agent": a,
            "speedup": speedup(h["min"], a["total_min"]), "notes": notes}
