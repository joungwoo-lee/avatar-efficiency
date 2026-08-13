# -*- coding: utf-8 -*-
"""OBHE Layer 1+2 — Outcome Reconstruction + Reference Human Path Generator.

artifact 텍스트 → (LLM) → Outcome Unit + Human Action Ledger.

원칙:
  - LLM은 행동·수량·complexity driver·evidence만 출력한다. 시간·분·요율 출력 금지 (§11).
  - rate card의 요율(base_min/add_min)은 프롬프트에 절대 노출하지 않는다 —
    수량 역산 오염 방지. 행동 이름·단위·driver 라벨만 노출.
  - 3중 추정 (§17): judges회 독립 복원 → 수량 median, 행동 채택 다수결,
    judge 간 편차 과대 시 human_review_required.
  - reference_ledger(정상 인간 경로)와 replication_ledger(AI 산출물 그대로
    복제 경로)를 분리 생성 (§4).

LLM 계약: llm.complete_json(prompt: str, max_tokens: int) -> dict
"""
import statistics

_MAX_TOKENS = 4000
_SPREAD_REVIEW_THRESHOLD = 3.0  # judge 간 max/min 수량비가 이를 넘으면 Human Review


def _catalog_lines(card):
    lines = []
    for name, spec in card["actions"].items():
        drivers = ", ".join(
            f"{d}({ds.get('label', d)})" for d, ds in (spec.get("drivers") or {}).items())
        line = f"- {name} [{spec['taxonomy']}] {spec.get('label', '')} (단위: {spec['unit']})"
        if drivers:
            line += f" | driver: {drivers}"
        lines.append(line)
    return "\n".join(lines)


def build_prompt(artifact_text, card, requirement_text=""):
    """요율(분)은 절대 포함하지 않는다."""
    req = f"\n요구사항·배경 (있으면 참고):\n{requirement_text}\n" if requirement_text else ""
    return f"""너는 결과물 기반 Human Equivalent Effort(OBHE) 산정을 위한 인간 작업경로 복원 엔진이다.
아래 최종 결과물(artifact)을 읽고 다음을 수행하라.

1. Net Accepted Outcome 추출: 최종 결과를 달성하는 데 실제로 필요했던 기능적 완료 단위(Outcome Unit)만 남긴다.
   AI 시행착오·중간 산출물·불필요한 잉여 산출물은 제외한다.
2. reference_ledger: 동일한 요구사항·기능·품질 상태를, 해당 업무에 숙련된 사람(P50 숙련자)이 AI 없이
   정상적인 작업방식으로 달성할 때 밟았을 기준 행동경로를 행동별 수량으로 복원한다.
   이것은 AI가 실제로 밟은 경로가 아니라 사람의 정상 경로다.
3. replication_ledger: 사람이 이 artifact를 거의 그대로 복제할 때의 행동경로. 잉여 산출물 분량까지 포함한다.

규칙:
- 시간·분·시급을 출력하지 마라. 오직 행동 이름, 수량, driver, 근거만 출력한다.
- quantity는 artifact에서 셀 수 있는 실제 수량(section 수, 주장 수, 차트 수, testcase 수 등)에 근거해야 한다.
  근거 없는 큰 수를 지어내지 마라. 각 행에 evidence(artifact의 어느 부분에서 추론했는지)를 반드시 적어라.
- 검증(verify_claim, verify_test, review_final 등 H7 행동)은 반드시 독립 행동으로 포함하라.
- 아래 카탈로그에 없는 action 이름·driver 이름을 쓰지 마라.

Human Action 카탈로그 (이름 [taxonomy] 설명 (수량 단위) | 가능한 driver):
{_catalog_lines(card)}
{req}
출력 JSON 스키마:
{{
  "outcomes": [{{"unit": "검증된 사실", "quantity": 34, "evidence": "..."}}],
  "reference_ledger": [
    {{"outcome": "...", "action": "카탈로그의 action 이름", "quantity": N,
      "drivers": ["해당 action에 정의된 driver만"], "evidence": "...", "role": "...", "confidence": "A|B|C"}}
  ],
  "replication_ledger": [ (같은 스키마) ],
  "outcome_confidence": "A|B|C",
  "rationale": "한 문단"
}}

최종 결과물(artifact):
---
{artifact_text}
---
JSON만 출력하라."""


def _clean_rows(rows, card):
    """카탈로그에 없는 action/driver를 제거한다 (LLM 환각 방어)."""
    actions = card["actions"]
    out = []
    for r in rows or []:
        name = r.get("action")
        if name not in actions:
            continue
        allowed = set((actions[name].get("drivers") or {}).keys())
        try:
            qty = float(r.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        out.append({
            "outcome": r.get("outcome", ""),
            "action": name,
            "quantity": qty,
            "drivers": [d for d in (r.get("drivers") or []) if d in allowed],
            "evidence": r.get("evidence", ""),
            "role": r.get("role", ""),
            "confidence": r.get("confidence", ""),
        })
    return out


def _aggregate_judges(ledgers, judges):
    """행동별 다수결 채택 + 수량 median (§17)."""
    majority = judges // 2 + 1
    by_action = {}
    for ledger in ledgers:
        seen = set()
        for r in ledger:
            key = r["action"]
            if key in seen:  # 같은 judge가 같은 행동을 중복 제시하면 수량 합산
                by_action[key]["quantities"][-1] += r["quantity"]
                continue
            seen.add(key)
            slot = by_action.setdefault(key, {"quantities": [], "rows": [], "driver_votes": {}})
            slot["quantities"].append(r["quantity"])
            slot["rows"].append(r)
            for d in r["drivers"]:
                slot["driver_votes"][d] = slot["driver_votes"].get(d, 0) + 1

    rows, review_required, unanimous = [], False, True
    for key, slot in by_action.items():
        votes = len(slot["quantities"])
        if votes < majority:
            unanimous = False
            continue
        if votes < judges:
            unanimous = False
        qty = statistics.median(slot["quantities"])
        lo, hi = min(slot["quantities"]), max(slot["quantities"])
        if lo > 0 and hi / lo > _SPREAD_REVIEW_THRESHOLD:
            review_required = True
        first = slot["rows"][0]
        rows.append({
            "outcome": first["outcome"],
            "action": key,
            "quantity": qty,
            "drivers": sorted(d for d, v in slot["driver_votes"].items() if v >= majority),
            "evidence": first["evidence"],
            "role": first["role"],
            "confidence": first["confidence"],
        })
    return rows, review_required, unanimous


def restore_paths(artifact_text, llm, card, judges=3, requirement_text=""):
    """artifact에서 reference/replication ledger를 judges회 복원 후 집계한다."""
    prompt = build_prompt(artifact_text, card, requirement_text)
    ref_ledgers, rep_ledgers, outcome_confs, outcomes = [], [], [], []
    for _ in range(max(1, judges)):
        result = llm.complete_json(prompt, max_tokens=_MAX_TOKENS)
        ref_ledgers.append(_clean_rows(result.get("reference_ledger"), card))
        rep_ledgers.append(_clean_rows(result.get("replication_ledger"), card))
        oc = result.get("outcome_confidence", "C")
        outcome_confs.append(oc if oc in ("A", "B", "C") else "C")
        if not outcomes:
            outcomes = result.get("outcomes") or []

    n = len(ref_ledgers)
    ref_rows, ref_review, ref_unanimous = _aggregate_judges(ref_ledgers, n)
    rep_rows, rep_review, _ = _aggregate_judges(rep_ledgers, n)

    review_required = ref_review or rep_review
    if review_required:
        path_confidence = "C"
    elif not ref_unanimous:
        path_confidence = "B"
    else:
        path_confidence = "A"

    # outcome confidence는 judge들 중 최악값 사용
    outcome_confidence = max(outcome_confs, key=lambda g: {"A": 0, "B": 1, "C": 2}[g])

    return {
        "outcomes": outcomes,
        "reference_ledger": ref_rows,
        "replication_ledger": rep_rows,
        "outcome_confidence": outcome_confidence,
        "path_confidence": path_confidence,
        "human_review_required": review_required,
        "judge_count": n,
    }
