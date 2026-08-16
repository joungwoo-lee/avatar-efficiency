# -*- coding: utf-8 -*-
"""efficiency 조합 층 — 방법론(부품)을 명령한 조합으로 돌리는 단일 지점.

부품(방법론)과 조합 선택을 여기 한 곳에서만 한다. 다른 모듈은 부품일 뿐이다.

    estimate_avatar(llm, card_text, human=..., agent=...)   # 사전
    measure_session(llm, jsonl_path, human=...)             # 사후

분자(human) 방식:
    "combined"     한 호출로 세 경로(사람/AI/감독) 동시 분해 (사전 전용, integ-spec §3) — 기본
    "workunit"     요구사항·산출물: 할일 → 산출물 단위 × 카탈로그 → P50/P80
    "req-actions"  요구사항·행동: 할일 → 사람 행동 × 단가, 숫자는 닻
    "record-actions" 세션기록·행동: 기록에서 바로 시뮬 (사후 전용, 교차확인)

분모(agent) 방식:
    "combined"     위 동시 분해의 AI+감독 부분 (사전 기본)
    "agent-llm"    별도 호출 사전 추산 (agent_effort)
    "record"       기록 실측, LLM 0회 (사후 기본·유일)

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
                                 estimate_actions_single, collect_record_stats)
from primitive_effort import estimate_human_min  # noqa: E402
from transcript_requirements import (extract_requirements,  # noqa: E402
                                     normalize_claude_code_jsonl)
from session_api import measure_agent_actual, is_trivial_session  # noqa: E402


def _extract_avatar_todos(llm, card_text, max_tokens=6000):
    raw = llm.complete_json(build_prompt_a_avatar(card_text), max_tokens)
    req, notes, fatal = validate_requirements_output(raw)
    if fatal:
        raise ValueError("할일 변환 실패: " + "; ".join(notes))
    return req, notes


def estimate_avatar(llm, card_text, human="combined", agent="combined", rates=None,
                    calls="staged"):
    """사전 측정: 아바타 카드 → speedup. 조합은 인자로만 지정.

    calls="single": 분자를 단일호출판으로 — workunit은 Prompt C(할일+분해
    한 호출), req-actions는 내부 할일 정리 포함 한 호출. combined는 원래 1회.
    단일호출은 저렴하지만 할일 목록의 단계별 감사·재처리는 포기."""
    rates = rates or load_rates()
    notes = []
    pp = None
    if human == "combined" or agent == "combined":
        pp = estimate_paths(llm, card_text, rates)
        notes += pp["notes"]

    # ---- 분모
    if agent == "combined":
        a = {"total_min": pp["agent_min"], "ai_min": pp["agent_ai_min"],
             "hitl_min": pp["agent_human_min"], "method": "combined"}
    elif agent == "agent-llm":
        ap = estimate_agent_min(llm, card_text, rates)
        a = {"total_min": ap["agent_min"], "ai_min": ap["agent_ai_min"],
             "hitl_min": ap["agent_human_min"], "method": "agent-llm"}
        notes += ap["notes"]
    else:
        raise ValueError(f"사전 측정에서 지원하지 않는 agent 방식: {agent}")

    # ---- 분자
    if human == "combined":
        h = {"min": pp["human_min"], "p80_min": None, "method": "combined"}
    elif human == "workunit":
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


def measure_session(llm, jsonl_path, human="workunit", force=False,
                    rates=None, max_chars=8000, calls="staged"):
    """사후 측정: 세션 기록 → speedup. 분모는 실측 고정(LLM 0회), 분자만 조합.

    calls="single" + human="req-actions": 분자를 한 호출(내부 할일 정리 포함)로
    — 세션당 LLM 1회."""
    rates = rates or load_rates()
    stats = collect_record_stats(jsonl_path)
    if is_trivial_session(stats) and not force:
        return {"input": "session", "excluded": True,
                "reason": "초소형 세션(검토·입력·산출물 기준 미달) — force=True로 강제"}

    actual = measure_agent_actual(jsonl_path, rates)
    a = {"total_min": actual["total_min"], "ai_min": actual["machine_min"],
         "hitl_min": actual["hitl_min"], "method": "record"}

    notes = []
    if human == "req-actions" and calls == "single":
        norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars,
                                           include_tool_stats=False)
        ra = estimate_actions_single(llm, norm, record_stats=stats, rates=rates)
        h = {"min": ra["human_min"], "p80_min": None, "method": "req-actions",
             "anchors": ra["anchors"], "todos": ra.get("todos")}
        notes += ra["notes"]
        return {"input": "session", "human": h, "agent": a,
                "speedup": speedup(h["min"], a["total_min"]), "notes": notes}
    if human == "record-actions":
        norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars,
                                           include_tool_stats=False)
        pr = estimate_human_min(llm, norm, rates=rates)
        h = {"min": pr["human_min"], "p80_min": None, "method": "record-actions"}
        notes += pr["notes"]
    else:
        norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars)
        req, n = extract_requirements(llm, norm)
        notes += n
        if human == "workunit":
            r = HumanEffortEstimator(llm).estimate_from_requirements(req, norm)
            h = {"min": r["effort"]["p50_minutes"],
                 "p80_min": r["effort"]["p80_minutes"], "method": "workunit",
                 "review_required": r["review_required"]}
            notes += r["warnings"] + r["notes"]
        elif human == "req-actions":
            ra = estimate_actions_from_requirements(llm, req, record_stats=stats,
                                                    rates=rates)
            h = {"min": ra["human_min"], "p80_min": None, "method": "req-actions",
                 "anchors": ra["anchors"]}
            notes += ra["notes"]
        else:
            raise ValueError(f"사후 측정에서 지원하지 않는 human 방식: {human}")

    return {"input": "session", "human": h, "agent": a,
            "speedup": speedup(h["min"], a["total_min"]), "notes": notes}
