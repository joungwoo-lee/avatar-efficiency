# -*- coding: utf-8 -*-
"""구 시스템(mm_app counterfactual.py CounterfactualEstimator) drop-in 호환 어댑터.

구 계약:
    CounterfactualEstimator.estimate_task(title, context, role, skill_names, detail) -> dict
    반환 키: error, human_min, agent_min, agent_human_min, agent_ai_min,
             saved_min, speedup, human_breakdown, agent_breakdown, rationale

매핑 (신규 EffortEstimator 출력 기준):
    agent_ai_min    = agent.machine.minutes   (기계 활성시간, ai_io 포함)
    agent_human_min = agent.hitl.minutes      (감독 + 잔여 직접작업)
    agent_min       = agent.minutes           (= machine + hitl)
    saved_min       = human_min - agent_min   (구 예시 수치 기준: 12.5-4.2=8.3)
    speedup         = human_min / agent_min   (구 예시 수치 기준: 12.5/4.2=2.98)
    breakdown       = primitive -> minutes flat map (machine·hitl 동명 primitive는 합산)
    agent_breakdown["ai_io"] = {"input_words", "output_words", "minutes"}

예외를 raise하지 않는다 — 실패 시 error 필드에 문자열, 수치는 None.
"""
from estimator import EffortEstimator, DEFAULT_RATES_PATH

_SPEC_TEMPLATE = """업무 제목: {title}
업무 맥락: {context}
소속 역할: {role}
연결된 스킬: {skills}
업무 상세: {detail}"""

_ERROR_RESULT = {
    "human_min": None, "agent_min": None,
    "agent_human_min": None, "agent_ai_min": None,
    "saved_min": None, "speedup": None,
    "human_breakdown": {}, "agent_breakdown": {},
    "rationale": "",
}


def _flat(breakdown):
    """[{primitive, minutes}, ...] -> {primitive: minutes} (동명 합산)."""
    out = {}
    for b in breakdown:
        out[b["primitive"]] = round(out.get(b["primitive"], 0.0) + b["minutes"], 2)
    return out


class CounterfactualEstimator:
    """llm 미지정 시: 실환경 onprem_llm.OnpremLLM 우선, 없으면 시뮬레이터."""

    def __init__(self, llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000):
        if llm is None:
            try:
                from onprem_llm import OnpremLLM        # 실환경 (mm_app/onprem-llm)
            except ImportError:
                from onprem_llm_sim import OnpremLLM    # 로컬/테스트 시뮬
            llm = OnpremLLM()
        self._est = EffortEstimator(llm, rates_path=rates_path, max_tokens=max_tokens)

    def estimate_task(self, title, context, role, skill_names, detail):
        try:
            skills = ", ".join(skill_names) if isinstance(skill_names, (list, tuple)) else str(skill_names)
            spec = _SPEC_TEMPLATE.format(
                title=title, context=context, role=role, skills=skills, detail=detail)
            r = self._est.estimate(spec)
        except Exception as e:  # LLM 통신 실패·2회 검증 실패 등 — 구 계약대로 error 필드로
            return dict(_ERROR_RESULT, error=f"{type(e).__name__}: {e}")

        human_min = r["human_only"]["minutes"]
        machine = r["agent"]["machine"]
        hitl = r["agent"]["hitl"]
        agent_min = r["agent"]["minutes"]

        agent_bd = _flat(machine["breakdown"])
        for name, minutes in _flat(hitl["breakdown"]).items():
            agent_bd[name] = round(agent_bd.get(name, 0.0) + minutes, 2)
        agent_bd["ai_io"] = machine["ai_io"]

        return {
            "error": None,
            "human_min": human_min,
            "agent_min": agent_min,
            "agent_human_min": hitl["minutes"],
            "agent_ai_min": machine["minutes"],
            "saved_min": round(human_min - agent_min, 2),
            "speedup": round(human_min / agent_min, 2) if agent_min > 0 else None,
            "human_breakdown": _flat(r["human_only"]["breakdown"]),
            "agent_breakdown": agent_bd,
            "rationale": r["rationale"],
            # 구 스키마 외 부가 정보 (무시해도 무방, 저장 권장)
            "confidence": r["confidence"],
            "confidence_notes": r["confidence_notes"],
        }
