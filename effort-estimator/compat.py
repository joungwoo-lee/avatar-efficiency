# -*- coding: utf-8 -*-
"""구 시스템(mm_app counterfactual.py) drop-in 어댑터 — doc/integ-spec.md 계약 준수.

계약 (integ-spec.md §2, §6):
    CounterfactualEstimator(llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000)
    .estimate_task(title, context, role, skill_names, detail) -> dict
    - 예외 raise 금지 — 실패 시 error 필드에 문자열, 수치는 전부 None
    - 출력 키 전부 존재: error, human_min, agent_min, agent_human_min, agent_ai_min,
      saved_min, speedup, human_breakdown, agent_breakdown, rationale,
      confidence, confidence_notes
    - agent_min 계열 반드시 수치 (§6.4 — None이면 analyze_card TypeError)

산정 구성 (하이브리드):
    human_min       = v0.5 Work Unit 엔진 P50 (estimator.HumanEffortEstimator,
                      catalog.json Monte Carlo) — 재개발된 human-equivalent 방법론
    agent_ai_min    = agent primitive count × rates.json 요율 + ai_io, revision factor 곱
    agent_human_min = hitl primitive count × rates.json 요율 (감독 + 잔여 직접작업)
    agent_min       = agent_ai_min + agent_human_min
    saved_min       = human_min - agent_min
    speedup         = human_min / agent_min (agent_min<=0이면 None)
"""
try:  # 패키지로 복사된 경우 (effort_estimator/)
    from .estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
    from . import agent_path as _agent_path
    from .agent_path import DEFAULT_RATES_PATH
except ImportError:  # 폴더를 직접 sys.path에 놓고 쓰는 경우 (개발·테스트)
    from estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
    import agent_path as _agent_path
    from agent_path import DEFAULT_RATES_PATH

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

# v0.5 파이프라인(Prompt A/B) 프롬프트가 커서 스펙 기본 max_tokens(2000)로는 부족 —
# agent-path 호출에는 호출자 값을 그대로 쓰고, v0.5 쪽은 최소 6000을 보장한다.
_V05_MIN_TOKENS = 6000


class CounterfactualEstimator:
    """실환경에서는 llm에 실물 OnpremLLM 인스턴스를 명시 주입할 것. 미지정 시 시뮬레이터."""

    def __init__(self, llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000,
                 catalog_path=DEFAULT_CATALOG_PATH, mode="two_pass"):
        if llm is None:
            # 실환경 경로(mm_app/onprem-llm)는 하이픈 폴더라 자동 import 불가 —
            # 실환경에서는 반드시 llm을 명시 주입할 것. 미주입 시 시뮬레이터 사용.
            try:
                from .onprem_llm_sim import OnpremLLM
            except ImportError:
                from onprem_llm_sim import OnpremLLM
            llm = OnpremLLM()
        self.llm = llm
        self.max_tokens = max_tokens
        self.rates = _agent_path.load_rates(rates_path)
        self._est = HumanEffortEstimator(
            llm, catalog_path=catalog_path,
            max_tokens=max(max_tokens, _V05_MIN_TOKENS), mode=mode)

    def estimate_task(self, title, context, role, skill_names, detail):
        try:
            skills = (", ".join(skill_names) if isinstance(skill_names, (list, tuple))
                      else (str(skill_names) if skill_names else ""))
            spec = _SPEC_TEMPLATE.format(
                title=title or "", context=context or "", role=role or "",
                skills=skills, detail=detail or "")
            r = self._est.estimate(spec)                       # human 경로 (v0.5)
            ap = _agent_path.estimate_agent_path(              # agent 경로 (spec §3)
                self.llm, spec, self.rates, self.max_tokens)
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
        notes = list(r["warnings"]) + list(r["notes"]) + list(ap["notes"])

        return {
            "error": None,
            "human_min": human_min,
            "agent_min": agent_min,
            "agent_human_min": ap["hitl_min"],
            "agent_ai_min": ap["machine_min"],
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
