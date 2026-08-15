# -*- coding: utf-8 -*-
"""결정론적 Effort Engine — doc/requirement_based_human_effort_service_design.md §4.6.

각 Work Item = Work Unit 기준 시간분포 × 수량분포 + 조건(parameter)별 추가 시간분포.
전체 Human Effort 분포를 재현 가능한 시드의 Monte Carlo로 합성하고,
P50/P80은 최종 총공수분포에서 한 번만 산출한다(단위별 percentile 합산 금지).

LLM 출력에는 시간이 없다 — 시간분포는 이 모듈이 Catalog에서만 읽는다.
"""
import random

DEFAULT_TRIALS = 5000
DEFAULT_SEED = 42

FORBIDDEN_LLM_KEYS = frozenset({
    "minutes", "hours", "person_hours", "person_days", "effort", "duration",
    "multiplier", "effort_multiplier", "p50", "p80", "time", "days",
})


def strip_forbidden_keys(obj, notes, path=""):
    """LLM 출력에서 시간·공수 필드를 재귀 제거(설계서 §7.4 금지 규칙). in-place."""
    if isinstance(obj, dict):
        for key in [k for k in obj if isinstance(k, str) and k.lower() in FORBIDDEN_LLM_KEYS]:
            notes.append(f"금지 필드 제거: {path}.{key}")
            del obj[key]
        for k, v in obj.items():
            strip_forbidden_keys(v, notes, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            strip_forbidden_keys(v, notes, f"{path}[{i}]")
    return obj


def sample_time_model(model, rng):
    """Catalog 시간분포 1회 표본 (분/단위). 지원: point, triangular, uniform, lognormal."""
    family = model["family"]
    if family == "point":
        return float(model["value"])
    if family == "triangular":
        return rng.triangular(float(model["min"]), float(model["max"]), float(model["mode"]))
    if family == "uniform":
        return rng.uniform(float(model["min"]), float(model["max"]))
    if family == "lognormal":
        return rng.lognormvariate(float(model["mu"]), float(model["sigma"]))
    raise ValueError(f"지원하지 않는 시간분포 family: {family}")


def sample_quantity(quantity, rng):
    """LLM 수량분포 1회 표본. 지원: point, triangular, discrete (설계서 §7.4)."""
    dist = quantity.get("distribution", "point")
    if dist == "point":
        return float(quantity["value"])
    if dist == "triangular":
        return rng.triangular(float(quantity["min"]), float(quantity["max"]),
                              float(quantity["mode"]))
    if dist == "discrete":
        values = [float(v) for v in quantity["values"]]
        probs = quantity.get("probabilities")
        if probs:
            return rng.choices(values, weights=[float(p) for p in probs], k=1)[0]
        return rng.choice(values)
    raise ValueError(f"지원하지 않는 수량분포: {dist}")


def validate_quantity(quantity):
    """수량분포 형식 검증. 반환: 오류 문자열 또는 None."""
    if not isinstance(quantity, dict):
        return "quantity가 객체가 아님"
    dist = quantity.get("distribution", "point")
    try:
        if dist == "point":
            v = float(quantity["value"])
            if v < 0:
                return "point 수량이 음수"
        elif dist == "triangular":
            lo, mo, hi = (float(quantity["min"]), float(quantity["mode"]),
                          float(quantity["max"]))
            if not (0 <= lo <= mo <= hi) or hi <= 0:
                return f"triangular 수량 조건 위반 (min={lo}, mode={mo}, max={hi})"
        elif dist == "discrete":
            values = quantity.get("values")
            if not isinstance(values, list) or not values:
                return "discrete values 누락"
            if any(float(v) < 0 for v in values):
                return "discrete 수량에 음수 포함"
            probs = quantity.get("probabilities")
            if probs is not None and len(probs) != len(values):
                return "discrete values/probabilities 길이 불일치"
        else:
            return f"허용되지 않은 수량분포 '{dist}'"
    except (KeyError, TypeError, ValueError) as e:
        return f"수량 필드 불량: {e!r}"
    return None


def _param_deltas(work_unit, parameters, notes, item_id):
    """허용된 parameter 값에 대응하는 추가 시간분포 목록. 미허용 키/값은 경고 후 무시."""
    deltas = []
    allowed = work_unit.get("allowed_parameters", {})
    for key, value in (parameters or {}).items():
        if key not in allowed:
            notes.append(f"{item_id}: 미허용 parameter '{key}' 무시")
            continue
        value_str = str(value).lower() if isinstance(value, bool) else str(value)
        if value_str not in allowed[key]:
            notes.append(f"{item_id}: parameter {key}='{value_str}' 허용값 아님 — 무시")
            continue
        delta = allowed[key][value_str]
        if delta:  # null이면 추가 시간 없음
            deltas.append(delta)
    return deltas


def _percentile(sorted_values, p):
    """선형보간 percentile (p: 0~100)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = (len(sorted_values) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def compute_effort(work_items, catalog, trials=DEFAULT_TRIALS, seed=DEFAULT_SEED):
    """검증된 work_items(모두 Catalog에 존재)에서 전체 공수분포 합성.

    반환:
      {
        "p50_minutes", "p80_minutes", "mean_minutes",
        "simulation": {"method", "trials", "seed"},
        "item_contributions": [{"work_item_id", "work_unit_id", "mean_minutes", "share"}],
        "notes": [...]
      }
    """
    notes = []
    tier_scale = catalog.get("quality_tier_scale", {})
    rng = random.Random(seed)

    # 아이템별 (work_unit, scale, deltas) 사전 해석
    resolved = []
    for item in work_items:
        wu = catalog["work_units"][item["work_unit_id"]]
        tier = item.get("quality_tier", "operational")
        scale = float(tier_scale.get(tier, 1.0))
        if tier not in tier_scale:
            notes.append(f"{item['work_item_id']}: 미정의 quality_tier '{tier}' → 1.0 적용")
        deltas = _param_deltas(wu, item.get("parameters"), notes, item["work_item_id"])
        resolved.append((item, wu, scale, deltas))

    totals = []
    item_sums = [0.0] * len(resolved)
    for _ in range(trials):
        trial_total = 0.0
        for i, (item, wu, scale, deltas) in enumerate(resolved):
            qty = sample_quantity(item["quantity"], rng)
            per_unit = sample_time_model(wu["time_model"], rng)
            per_unit += sum(sample_time_model(d, rng) for d in deltas)
            minutes = max(0.0, per_unit * scale * qty)
            item_sums[i] += minutes
            trial_total += minutes
        totals.append(trial_total)

    totals.sort()
    mean_total = sum(totals) / len(totals) if totals else 0.0
    contributions = []
    for i, (item, wu, _, _) in enumerate(resolved):
        mean_i = item_sums[i] / trials if trials else 0.0
        contributions.append({
            "work_item_id": item["work_item_id"],
            "work_unit_id": item["work_unit_id"],
            "engine": item.get("engine", wu["engine"]),
            "quality_tier": item.get("quality_tier", "operational"),
            "mean_minutes": round(mean_i, 2),
            "share": round(mean_i / mean_total, 4) if mean_total > 0 else 0.0,
        })
    contributions.sort(key=lambda c: -c["mean_minutes"])

    return {
        "p50_minutes": round(_percentile(totals, 50), 1),
        "p80_minutes": round(_percentile(totals, 80), 1),
        "mean_minutes": round(mean_total, 1),
        "simulation": {"method": "monte_carlo", "trials": trials, "seed": seed},
        "item_contributions": contributions,
        "notes": notes,
    }
