# -*- coding: utf-8 -*-
"""OBHE Layer 3 — Empirical Human Rate Engine.

Human Action Ledger(행동 x 수량 x complexity driver)를 rate_card.json의
time equation으로 환산한다.

  시간 = 수량 x (기본 단위시간 + Σ 적용된 driver 추가시간)   (TDABC, §8·§10)

원칙 (OBHE 방법론 문서 기준):
  - LLM은 시간을 출력하지 않는다. 시간은 이 엔진만 계산한다 (§11).
  - 결과는 단일 숫자가 아니라 P50/P80 범위 + Confidence (§18).
  - Verification(H7)이 ledger에 없으면 경고한다 (§13).
  - Expected Human Rework를 별도 항목으로 가산한다 (§14).
  - HRE / RHE / AI Actual Effort 세 숫자를 분리 보존한다 (§19).
"""
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_RATE_CARD_PATH = _HERE / "rate_card.json"

_CONFIDENCE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


class RateCardError(ValueError):
    pass


def load_rate_card(path=None):
    """외부 rate card 파일을 읽고 최소 스키마를 검증한다."""
    p = Path(path) if path else DEFAULT_RATE_CARD_PATH
    card = json.loads(p.read_text(encoding="utf-8"))
    if "actions" not in card or not isinstance(card["actions"], dict):
        raise RateCardError(f"rate card에 actions 없음: {p}")
    for name, spec in card["actions"].items():
        for key in ("taxonomy", "unit", "base_min"):
            if key not in spec:
                raise RateCardError(f"action '{name}'에 '{key}' 필드 없음")
    return card


def price_row(row, card):
    """ledger row 1건에 time equation을 적용한다.

    row 필수 필드: action, quantity. 선택: drivers(list), outcome, evidence,
    role, confidence (§12 필드 구조).
    """
    actions = card["actions"]
    name = row.get("action")
    if name not in actions:
        raise RateCardError(f"rate card에 없는 action: {name!r}")
    spec = actions[name]
    qty = float(row.get("quantity", 0))
    if qty < 0:
        raise RateCardError(f"음수 quantity: {name}={qty}")

    min_per_unit = float(spec["base_min"])
    applied = []
    for d in row.get("drivers", []) or []:
        dspec = (spec.get("drivers") or {}).get(d)
        if dspec is None:
            raise RateCardError(f"action '{name}'에 정의되지 않은 driver: {d!r}")
        min_per_unit += float(dspec["add_min"])
        applied.append(d)

    p80_factor = float(spec.get("p80_factor", card.get("p80_factor_default", 1.4)))
    p50_min = qty * min_per_unit
    return {
        "outcome": row.get("outcome", ""),
        "action": name,
        "label": spec.get("label", name),
        "taxonomy": spec["taxonomy"],
        "unit": spec["unit"],
        "quantity": qty,
        "drivers": applied,
        "evidence": row.get("evidence", ""),
        "role": row.get("role", ""),
        "confidence": row.get("confidence", ""),
        "min_per_unit": min_per_unit,
        "p50_min": p50_min,
        "p80_min": p50_min * p80_factor,
        "rate_source": card.get("meta", {}).get("rate_source", ""),
    }


def price_ledger(rows, card):
    """ledger 전체를 환산한다. 반환: rows(환산본), 작업/rework/총계, 경고."""
    priced = [price_row(r, card) for r in rows]
    work_p50 = sum(r["p50_min"] for r in priced)
    work_p80 = sum(r["p80_min"] for r in priced)

    rework = card.get("expected_rework") or {}
    ratio = float(rework.get("ratio", 0.0))
    scope = set(rework.get("applies_to_taxonomy", []))
    base_p50 = sum(r["p50_min"] for r in priced if r["taxonomy"] in scope)
    base_p80 = sum(r["p80_min"] for r in priced if r["taxonomy"] in scope)
    rework_p50 = ratio * base_p50
    rework_p80 = ratio * base_p80

    warnings = []
    if priced and not any(r["taxonomy"] == "H7" for r in priced):
        warnings.append("Verification(H7) 행동이 ledger에 없음 — §13 위반 가능. 검증을 독립 행동으로 계측할 것.")

    return {
        "rows": priced,
        "work_p50_min": work_p50,
        "work_p80_min": work_p80,
        "rework_p50_min": rework_p50,
        "rework_p80_min": rework_p80,
        "total_p50_min": work_p50 + rework_p50,
        "total_p80_min": work_p80 + rework_p80,
        "warnings": warnings,
    }


def _worst_confidence(*grades):
    """§18: Confidence = Outcome/Path/Rate 신뢰도 중 최악값."""
    valid = [g for g in grades if g in _CONFIDENCE_ORDER]
    if not valid:
        return "D"
    return max(valid, key=lambda g: _CONFIDENCE_ORDER[g])


def build_report(reference_ledger, card, replication_ledger=None,
                 ai_actual_hours=None, outcome_confidence="B",
                 path_confidence="B", human_review_required=False):
    """RHE(P50/P80), HRE, Output Inflation, 현실화 효율, Confidence를 계산한다."""
    ref = price_ledger(reference_ledger, card)
    rep = price_ledger(replication_ledger, card) if replication_ledger else None

    rhe_p50_h = ref["total_p50_min"] / 60.0
    rhe_p80_h = ref["total_p80_min"] / 60.0

    report = {
        "reference": ref,
        "rhe_p50_hours": round(rhe_p50_h, 2),
        "rhe_p80_hours": round(rhe_p80_h, 2),
        "confidence": _worst_confidence(
            outcome_confidence, path_confidence,
            card.get("meta", {}).get("rate_confidence", "C")),
        "confidence_components": {
            "outcome": outcome_confidence,
            "path": path_confidence,
            "rate_db": card.get("meta", {}).get("rate_confidence", "C"),
        },
        "human_review_required": bool(human_review_required),
        "warnings": list(ref["warnings"]),
    }

    if rep is not None:
        hre_p50_h = rep["total_p50_min"] / 60.0
        report["replication"] = rep
        report["hre_p50_hours"] = round(hre_p50_h, 2)
        report["output_inflation"] = (
            round(hre_p50_h / rhe_p50_h, 2) if rhe_p50_h > 0 else None)
        report["warnings"].extend(rep["warnings"])

    if ai_actual_hours is not None:
        report["ai_actual_hours"] = float(ai_actual_hours)
        report["realized_efficiency"] = (
            round(rhe_p50_h / float(ai_actual_hours), 2)
            if float(ai_actual_hours) > 0 else None)
        if rep is not None and float(ai_actual_hours) > 0:
            report["naive_efficiency"] = round(
                rep["total_p50_min"] / 60.0 / float(ai_actual_hours), 2)

    return report
