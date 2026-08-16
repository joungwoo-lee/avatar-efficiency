# -*- coding: utf-8 -*-
"""efficiency 조합 층 — 방법론(부품)을 명령한 조합으로 돌리는 단일 지점.

부품(방법론)과 조합 선택을 여기 한 곳에서만 한다. 다른 모듈은 부품일 뿐이다.

    estimate_avatar(llm, card_text, human=..., agent=...)   # 사전
    measure_session(llm, jsonl_path, human=...)             # 사후

분자(human) 방식:
    "req-actions"    요구사항·행동: 사람 행동 × 단가, 숫자는 닻 (사전·사후 기본)
    "record-actions" 세션기록·행동: 기록에서 바로 시뮬 (사후 전용, 교차확인)
    "workunit"       요구사항·산출물 → P50/P80 (사전만 잔존; **사후는 폐기** —
                     session-api/workunit_deprecated.py, CHANGELOG §20)

분모(agent) 방식:
    "agent-llm"    사전 추산 — AI+감독 행동 × 단가 (사전 기본)
    "record"       기록 실측, LLM 0회 (사후 기본·유일)

사후(세션) 측정 본체는 session-api/session_api.py — 여기선 위임만.

호출 병합(방식이 아님): 사전에서 human="req-actions" + agent="agent-llm" +
calls="single"이면 두 방법론을 **한 프롬프트로 묶어 LLM 1회**에 처리한다
(paths.estimate_paths, integ-spec §3). 방법론은 그대로고 호출만 합친 것.

반환(공통): {human: {...}, agent: {...}, speedup, notes, ...}
"""
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent
for _p in (_BASE / "human-effort" / "requirement-based",
           _BASE / "human-effort" / "requirement-actions",
           _BASE / "human-effort" / "record-actions",
           _BASE / "human-effort" / "shared",
           _BASE / "agent-effort",
           _BASE / "counterfactual-api",
           _BASE / "session-api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_effort import load_rates, estimate_agent_min, speedup  # noqa: E402
from paths import estimate_paths  # noqa: E402
from estimator import HumanEffortEstimator, validate_requirements_output  # noqa: E402
from prompts import build_prompt_a_avatar  # noqa: E402
from requirement_actions import (estimate_actions_from_requirements,  # noqa: E402
                                 estimate_actions_single)
from session_api import measure_session as sa_measure_session  # noqa: E402


def _extract_avatar_todos(llm, card_text, max_tokens=6000):
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


def measure_session(llm, jsonl_path, human="req-actions", force=False,
                    rates=None, max_chars=8000, calls="single"):
    """사후 측정: 세션 기록 → speedup. 세션 측정 본체는 session-api에 산다
    (session_api.measure_session) — 여기서는 위임만 한다.

    human: "req-actions"(기본) | "record-actions"(교차확인 기준선).
    workunit 방식은 폐기 — session-api/workunit_deprecated.py 참고 보관.
    calls="single"(기본): 분자를 한 호출(내부 할일 정리 포함)로 — 세션당 LLM 1회.
    """
    if human == "workunit":
        raise ValueError("workunit 방식은 폐기됨 — "
                         "session-api/workunit_deprecated.py 참고 보관")
    r = sa_measure_session(llm, jsonl_path, human=human, calls=calls,
                           rates=rates, max_chars=max_chars, force=force)
    r["input"] = "session"
    return r
