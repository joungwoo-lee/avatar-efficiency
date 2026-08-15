# -*- coding: utf-8 -*-
"""구 시스템(mm_app counterfactual.py CounterfactualEstimator) 호환 어댑터.

구 계약:
    CounterfactualEstimator.estimate_task(title, context, role, skill_names, detail) -> dict
    반환 키: error, human_min, agent_min, agent_human_min, agent_ai_min,
             saved_min, speedup, human_breakdown, agent_breakdown, rationale

주의 — 방법론 변경 (doc/requirement_based_human_effort_service_design.md v0.5):
    신규 산정기는 Human-Equivalent Effort(P50/P80)만 산출한다. agent/machine/hitl
    경로 산정은 신규 방법론의 범위 밖(비목표 §2.3)이므로 agent_min, agent_human_min,
    agent_ai_min, saved_min, speedup은 None으로 반환한다. 소비 측은 human_min
    (P50 분)과 부가 필드 human_p80_min만 사용할 것.
"""
try:  # 패키지로 복사된 경우 (effort_estimator/)
    from .estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
except ImportError:  # 폴더를 직접 sys.path에 놓고 쓰는 경우 (개발·테스트)
    from estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH

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


class CounterfactualEstimator:
    """실환경에서는 llm에 실물 OnpremLLM 인스턴스를 명시 주입할 것. 미지정 시 시뮬레이터."""

    def __init__(self, llm=None, catalog_path=DEFAULT_CATALOG_PATH, max_tokens=6000,
                 mode="two_pass"):
        if llm is None:
            # 실환경 경로(mm_app/onprem-llm)는 하이픈 폴더라 자동 import 불가 —
            # 실환경에서는 반드시 llm을 명시 주입할 것. 미주입 시 시뮬레이터 사용.
            try:
                from .onprem_llm_sim import OnpremLLM
            except ImportError:
                from onprem_llm_sim import OnpremLLM
            llm = OnpremLLM()
        self._est = HumanEffortEstimator(llm, catalog_path=catalog_path,
                                         max_tokens=max_tokens, mode=mode)

    def estimate_task(self, title, context, role, skill_names, detail):
        try:
            skills = ", ".join(skill_names) if isinstance(skill_names, (list, tuple)) else str(skill_names)
            spec = _SPEC_TEMPLATE.format(
                title=title, context=context, role=role, skills=skills, detail=detail)
            r = self._est.estimate(spec)
        except Exception as e:  # LLM 통신 실패·2회 검증 실패 등 — 구 계약대로 error 필드로
            return dict(_ERROR_RESULT, error=f"{type(e).__name__}: {e}")

        breakdown = {c["work_unit_id"]: c["mean_minutes"]
                     for c in r["item_contributions"]}
        rationale = "; ".join(f"{q['requirement_id']} {q['title']}"
                              for q in r["requirements"])
        return {
            "error": None,
            "human_min": r["effort"]["p50_minutes"],
            "agent_min": None,          # 신규 방법론 범위 밖 (docstring 참조)
            "agent_human_min": None,
            "agent_ai_min": None,
            "saved_min": None,
            "speedup": None,
            "human_breakdown": breakdown,
            "agent_breakdown": {},
            "rationale": rationale,
            # 구 스키마 외 부가 정보 (무시해도 무방, 저장 권장)
            "human_p80_min": r["effort"]["p80_minutes"],
            "estimate_id": r["estimate_id"],
            "catalog_version": r["catalog_version"],
            "confidence": r["confidence"],
            "warnings": r["warnings"] + r["notes"],
        }
