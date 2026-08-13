# -*- coding: utf-8 -*-
"""human_rate_engine — deterministic 계산기 (방법론 §11~§12, LLM 미사용).

Action Effort = Workload × Human Rate × Complexity Adjustment
Reference Human Effort = 모든 unique action effort 합 + 정상적 Human Rework
시간은 LLM이 아니라 이 엔진과 rates.json만 결정한다.
"""
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_RATES_PATH = _HERE / "rates.json"

AUTO_APPROVE_STATES = {"EXACT", "HIGH_CONFIDENCE"}  # §14


class RateError(ValueError):
    pass


def load_rates(path=None):
    p = Path(path) if path else DEFAULT_RATES_PATH
    rates = json.loads(p.read_text(encoding="utf-8"))
    for key in ("actions", "units", "complexity_adjustment"):
        if key not in rates:
            raise RateError(f"rates 파일에 '{key}' 없음: {p}")
    return rates


def price_ledger(ledger, rates):
    adj = rates["complexity_adjustment"]
    rows = []
    for r in ledger:
        unit = rates["units"].get(r["workload_unit"])
        if unit is None:
            raise RateError(f"rates에 없는 workload 단위: {r['workload_unit']!r}")
        mult = float(adj.get(r.get("complexity", "normal"), 1.0))
        p50 = r["workload"] * float(unit["p50_min"]) * mult
        p80 = r["workload"] * float(unit["p80_min"]) * mult
        rows.append({**r, "p50_min": p50, "p80_min": p80})
    work_p50 = sum(r["p50_min"] for r in rows)
    work_p80 = sum(r["p80_min"] for r in rows)
    ratio = float(rates.get("expected_rework_ratio", 0.0))
    warnings = []
    if rows and not any(r["action"] in ("verify", "finalize") for r in rows):
        warnings.append("검증(verify)·최종 정리(finalize) 행동이 ledger에 없음 — 사람 시간 과소평가 가능.")
    return {
        "rows": rows,
        "work_p50_min": work_p50,
        "work_p80_min": work_p80,
        "rework_p50_min": work_p50 * ratio,
        "rework_p80_min": work_p80 * ratio,
        "total_p50_min": work_p50 * (1 + ratio),
        "total_p80_min": work_p80 * (1 + ratio),
        "warnings": warnings,
    }


def build_report(manifest, estimation, rates, ai_actual_hours=None):
    priced = price_ledger(estimation["action_ledger"], rates)
    rhe_p50_h = priced["total_p50_min"] / 60.0
    rhe_p80_h = priced["total_p80_min"] / 60.0
    recovery = manifest.get("recovery", "UNRECOVERABLE")
    report = {
        "job_id": manifest["job_id"],
        "recovery": recovery,
        "auto_approved": recovery in AUTO_APPROVE_STATES,
        "rhe_p50_hours": round(rhe_p50_h, 2),
        "rhe_p80_hours": round(rhe_p80_h, 2),
        "rate_confidence": rates.get("meta", {}).get("rate_confidence", "C"),
        "priced": priced,
        "completed_outcomes": estimation["completed_outcomes"],
        "excluded_outputs": estimation["excluded_outputs"],
        "measurement_required": estimation["measurement_required"],
        "warnings": list(priced["warnings"]),
    }
    if not report["auto_approved"]:
        report["warnings"].append(
            f"복원 상태 {recovery} — Human Equivalent Effort 자동 승인 불가 (§14). 참고치로만 사용할 것.")
    if ai_actual_hours is not None and float(ai_actual_hours) > 0:
        report["ai_actual_hours"] = float(ai_actual_hours)
        report["realized_efficiency"] = round(rhe_p50_h / float(ai_actual_hours), 2)
    return report
