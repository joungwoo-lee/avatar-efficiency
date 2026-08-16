# -*- coding: utf-8 -*-
"""구 시스템(mm_app counterfactual.py) drop-in 어댑터 — integ-spec.md 계약 준수.

계약 (integ-spec.md §2, §3, §6):
    CounterfactualEstimator(llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000)
    .estimate_task(title, context, role, skill_names, detail) -> dict
    - 예외 raise 금지 — 실패 시 error 필드에 문자열, 수치는 전부 None
    - 출력 키 전부 존재, agent_min 계열 반드시 수치 (§6.4)

산정 (기본, human_method="combined"): integ-spec §3 그대로 — **LLM 1회** 호출이 human/agent/hitl 세 경로를
같은 완료상태 기준으로 함께 분해(paths.estimate_paths), 코드가 rates.json 요율을
곱한다. 아바타 카드는 이미 정리된 업무 정의라 별도 할일 변환 호출이 불필요.
분자·분모가 같은 행동×단가 체계 — speedup 배율이 해석 가능.

human_method="workunit" 옵션: 분자만 요구사항·산출물 방식(카탈로그×Monte Carlo,
P50/P80 분포)으로 교체 — 분포·보수치가 필요한 정식 산정용 (LLM 3회).
"""
try:  # 배포형: 한 폴더에 모아 복사된 경우
    from estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
    from paths import estimate_paths
    from agent_effort import load_rates, DEFAULT_RATES_PATH
except ImportError:  # 레포 배치: 형제 폴더 참조
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parent.parent
    for _p in (_root / "human-effort" / "requirement-based",
               _root / "human-effort" / "shared",
               _root / "counterfactual-api",
               _root / "agent-effort"):
        if str(_p) not in _sys.path:
            _sys.path.insert(0, str(_p))
    from estimator import HumanEffortEstimator, DEFAULT_CATALOG_PATH
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

# workunit 분자(Prompt A/B) 프롬프트가 커서 스펙 기본 max_tokens(2000)로는 부족
_HUMAN_MIN_TOKENS = 6000


class CounterfactualEstimator:
    """실환경에서는 llm에 실물 OnpremLLM 인스턴스를 명시 주입할 것. 미지정 시 시뮬레이터."""

    def __init__(self, llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000,
                 catalog_path=DEFAULT_CATALOG_PATH, mode="two_pass",
                 human_method="combined"):
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
        self.human_method = human_method
        self.rates = load_rates(rates_path)
        self._est = None
        if human_method == "workunit":
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
            pp = estimate_paths(self.llm, spec, self.rates, self.max_tokens)  # 1회
            if self.human_method == "workunit":
                r = self._est.estimate(spec)                                  # +2회
        except Exception as e:  # LLM 통신 실패·검증 2회 실패 등 — 구 계약대로
            return dict(_ERROR_RESULT, error=f"{type(e).__name__}: {e}")

        if self.human_method == "workunit":
            human_min = r["effort"]["p50_minutes"]
            human_bd = {c["work_unit_id"]: c["mean_minutes"]
                        for c in r["item_contributions"]}
            human_p80 = r["effort"]["p80_minutes"]
            extra = ([f"review_required: {x}" for x in r.get("review_reasons", [])]
                     + list(r["warnings"]) + list(r["notes"]))
            est_id, cat_ver = r["estimate_id"], r["catalog_version"]
        else:
            human_min = pp["human_min"]
            human_bd = _flat(pp["human_breakdown"])
            human_p80 = None  # 행동×단가는 점추정 — 분포는 workunit 모드
            extra = []
            est_id = None
            cat_ver = "rates.json(행동 단가) — 분자·분모 동일 체계"

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
            "human_breakdown": human_bd,
            "agent_breakdown": agent_bd,
            "rationale": pp["rationale"],
            "confidence": "C (cold-start seed rates/catalog, 미보정)",
            "confidence_notes": extra + list(pp["notes"]),
            # 구 스키마 외 부가 정보 (무시해도 무방, 저장 권장)
            "human_p80_min": human_p80,
            "estimate_id": est_id,
            "catalog_version": cat_ver,
        }


def _flat(breakdown):
    """[{primitive, minutes}, ...] -> {primitive: minutes} (동명 합산)."""
    out = {}
    for b in breakdown:
        out[b["primitive"]] = round(out.get(b["primitive"], 0.0) + b["minutes"], 2)
    return out
