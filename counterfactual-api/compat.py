# -*- coding: utf-8 -*-
"""구 시스템(mm_app counterfactual.py) drop-in 어댑터 — integ-spec.md 계약 준수.

분자·분모를 합쳐 구 API로 내보내는 통합 지점:
    human_min       = ../human-effort  (v0.6 Work Unit 엔진 P50 — 사람 w/o AI)
    agent_min 계열  = ../agent-effort  (agent_effort.estimate_agent_min —
                      primitive count × rates.json + ai_io)

계약 (integ-spec.md §2, §6):
    CounterfactualEstimator(llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000)
    .estimate_task(title, context, role, skill_names, detail) -> dict
    - 예외 raise 금지 — 실패 시 error 필드에 문자열, 수치는 전부 None
    - 출력 키 전부 존재, agent_min 계열 반드시 수치 (§6.4)

배포: human-effort/*, agent-effort/agent_effort.py·rates.json, 이 파일을
한 폴더(effort_estimator/)에 모아 복사하면 동일 폴더 import로 동작한다.
레포 배치 그대로면 ../human-effort, ../agent-effort를 자동 참조한다.
"""
try:  # 배포형: 한 폴더에 모아 복사된 경우
    from estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
    from agent_effort import estimate_agent_min, load_rates, DEFAULT_RATES_PATH
except ImportError:  # 레포 배치: 형제 폴더 참조
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parent.parent
    for _p in (_root / "human-effort", _root / "agent-effort"):
        if str(_p) not in _sys.path:
            _sys.path.insert(0, str(_p))
    from estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
    from agent_effort import estimate_agent_min, load_rates, DEFAULT_RATES_PATH

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

# human 파이프라인(Prompt A/B) 프롬프트가 커서 스펙 기본 max_tokens(2000)로는 부족 —
# agent 호출에는 호출자 값을 그대로 쓰고, human 쪽은 최소 6000을 보장한다.
_HUMAN_MIN_TOKENS = 6000


class CounterfactualEstimator:
    """실환경에서는 llm에 실물 OnpremLLM 인스턴스를 명시 주입할 것. 미지정 시 시뮬레이터."""

    def __init__(self, llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000,
                 catalog_path=DEFAULT_CATALOG_PATH, mode="two_pass"):
        if llm is None:
            try:
                from onprem_llm_sim import OnpremLLM
            except ImportError:
                import sys as _s
                from pathlib import Path as _P
                _s.path.insert(0, str(_P(__file__).resolve().parent.parent / "human-effort"))
                from onprem_llm_sim import OnpremLLM
            llm = OnpremLLM()
        self.llm = llm
        self.max_tokens = max_tokens
        self.rates = load_rates(rates_path)
        self._est = HumanEffortEstimator(
            llm, catalog_path=catalog_path,
            max_tokens=max(max_tokens, _HUMAN_MIN_TOKENS), mode=mode)

    def estimate_task(self, title, context, role, skill_names, detail):
        try:
            skills = (", ".join(skill_names) if isinstance(skill_names, (list, tuple))
                      else (str(skill_names) if skill_names else ""))
            spec = _SPEC_TEMPLATE.format(
                title=title or "", context=context or "", role=role or "",
                skills=skills, detail=detail or "")
            r = self._est.estimate(spec)                       # 분자 (human w/o AI)
            ap = estimate_agent_min(self.llm, spec,            # 분모 (agent+hitl)
                                    self.rates, self.max_tokens)
        except Exception as e:  # LLM 통신 실패·검증 2회 실패 등 — 구 계약대로 error 필드로
            return dict(_ERROR_RESULT, error=f"{type(e).__name__}: {e}")

        human_min = r["effort"]["p50_minutes"]
        agent_min = ap["agent_min"]

        human_bd = {c["work_unit_id"]: c["mean_minutes"]
                    for c in r["item_contributions"]}
        agent_bd = _flat(ap["machine_breakdown"])
        for name, minutes in _flat(ap["hitl_breakdown"]).items():
            agent_bd[name] = round(agent_bd.get(name, 0.0) + minutes, 2)
        agent_bd["ai_io"] = ap["ai_io"]

        rationale = ap["rationale"] or "; ".join(
            f"{q['requirement_id']} {q['title']}" for q in r["requirements"])
        notes = ([f"review_required: {reason}" for reason in r.get("review_reasons", [])]
                 + list(r["warnings"]) + list(r["notes"]) + list(ap["notes"]))

        return {
            "error": None,
            "human_min": human_min,
            "agent_min": agent_min,
            "agent_human_min": ap["agent_human_min"],
            "agent_ai_min": ap["agent_ai_min"],
            "saved_min": round(human_min - agent_min, 2),
            "speedup": round(human_min / agent_min, 2) if agent_min > 0 else None,
            "human_breakdown": human_bd,
            "agent_breakdown": agent_bd,
            "rationale": rationale,
            "confidence": "C (cold-start seed rates/catalog, 미보정)",
            "confidence_notes": notes,
            # 구 스키마 외 부가 정보 (무시해도 무방, 저장 권장)
            "human_p80_min": r["effort"]["p80_minutes"],
            "estimate_id": r["estimate_id"],
            "catalog_version": r["catalog_version"],
        }


def _flat(breakdown):
    """[{primitive, minutes}, ...] -> {primitive: minutes} (동명 합산)."""
    out = {}
    for b in breakdown:
        out[b["primitive"]] = round(out.get(b["primitive"], 0.0) + b["minutes"], 2)
    return out
