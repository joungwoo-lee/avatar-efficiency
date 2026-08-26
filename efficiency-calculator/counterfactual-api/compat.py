# -*- coding: utf-8 -*-
"""구 시스템(mm_app counterfactual.py) drop-in 어댑터 — integ-spec.md 계약 전용.

계약 (integ-spec.md §2, §3, §6):
    CounterfactualEstimator(llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=8000)
    .estimate_task(title, context, role, skill_names, detail) -> dict
    - 예외 raise 금지 — 실패 시 error 필드에 문자열, 수치는 전부 None
    - 출력 키 전부 존재, agent_min 계열 반드시 수치 (§6.4)

산정: integ-spec §3 그대로 — LLM 1회 호출이 human/agent/hitl 세 경로를 같은
완료상태 기준으로 함께 분해(paths.estimate_paths)하고 코드가 rates.json 요율을
곱한다. 분자 방법론 = 요구사항·행동(행동×사람 단가+닻), 분모 = agent 추산.

이 모듈은 구 계약 어댑터가 전부다 — 다른 방법론 조합이 필요하면
avatar_api.py(estimate_avatar, 사전) 또는 ../session-api(사후)를 쓸 것.
"""
try:  # 배포형: 한 폴더에 모아 복사된 경우
    from paths import estimate_paths
    from agent_effort import load_rates, DEFAULT_RATES_PATH
except ImportError:  # 레포 배치: 형제 폴더 참조
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parent.parent
    for _p in (_root / "counterfactual-api", _root / "agent-effort"):
        if str(_p) not in _sys.path:
            _sys.path.insert(0, str(_p))
    from paths import estimate_paths
    from agent_effort import load_rates, DEFAULT_RATES_PATH

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
    "confidence": None, "confidence_notes": [],
}


class CounterfactualEstimator:
    """실환경에서는 llm에 실물 OnpremLLM 인스턴스를 명시 주입할 것. 미지정 시 시뮬레이터."""

    def __init__(self, llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=8000):
        if llm is None:
            try:
                from onprem_llm_sim import OnpremLLM
            except ImportError:
                import sys as _s
                from pathlib import Path as _P
                _s.path.insert(0, str(_P(__file__).resolve().parent.parent
                                      / "human-effort" / "shared"))
                from onprem_llm_sim import OnpremLLM
            llm = OnpremLLM()
        self.llm = llm
        self.max_tokens = max_tokens
        self.rates = load_rates(rates_path)

    def estimate_task(self, title, context, role, skill_names, detail):
        try:
            skills = (", ".join(skill_names) if isinstance(skill_names, (list, tuple))
                      else (str(skill_names) if skill_names else ""))
            spec = _SPEC_TEMPLATE.format(
                title=title or "", context=context or "", role=role or "",
                skills=skills, detail=detail or "")
            pp = estimate_paths(self.llm, spec, self.rates, self.max_tokens)  # LLM 1회
        except Exception as e:  # LLM 통신 실패·검증 2회 실패 등 — 구 계약대로
            return dict(_ERROR_RESULT, error=f"{type(e).__name__}: {e}")

        human_min = pp["human_min"]
        agent_min = pp["agent_min"]
        agent_bd = _flat(pp["machine_breakdown"])
        for name, minutes in _flat(pp["hitl_breakdown"]).items():
            agent_bd[name] = round(agent_bd.get(name, 0.0) + minutes, 2)
        agent_bd["ai_io"] = pp["ai_io"]

        return {
            "error": None,
            "human_min": human_min,
            "agent_min": agent_min,
            "agent_human_min": pp["agent_human_min"],
            "agent_ai_min": pp["agent_ai_min"],
            "saved_min": round(human_min - agent_min, 2),
            "speedup": round(human_min / agent_min, 2) if agent_min > 0 else None,
            "human_breakdown": _flat(pp["human_breakdown"]),
            "agent_breakdown": agent_bd,
            "rationale": pp["rationale"],
            "confidence": "C (cold-start seed rates, 미보정)",
            "confidence_notes": list(pp["notes"]),
        }


def _flat(breakdown):
    """[{primitive, minutes}, ...] -> {primitive: minutes} (동명 합산)."""
    out = {}
    for b in breakdown:
        out[b["primitive"]] = round(out.get(b["primitive"], 0.0) + b["minutes"], 2)
    return out
