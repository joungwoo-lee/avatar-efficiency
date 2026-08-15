# -*- coding: utf-8 -*-
"""요구사항 기반 Human-Equivalent Effort 산정기.

방법론: doc/requirement_based_human_effort_service_design.md (v0.6)
입력: 아바타 디스크립션 — '할일+역할+업무상세+스킬' 업무 정의 텍스트 (업무 실행 전)
출력: 숙련자가 생성형 AI 없이 동일 결과를 만들 때의 Human-Equivalent Effort
      — 최종 총공수분포에서 한 번 산출한 P50/P80 (분 단위)

기본 구조(설계서 원안)는 '클로드코드 트랜스크립트 → 요구사항 추출 → 견적'이다.
본 모듈은 그 구조에서 **첫 단계만 아바타 특화로 교체**한 케이스다:
  트랜스크립트 케이스: Prompt A(§23) — 수행된 일의 복원 (본 모듈 미사용)
  아바타 케이스(본 모듈): Prompt A-avatar — 업무 정의를 요구사항으로 변환.
    아바타 입력의 확정 의미(스킬=기존 도구, 반복 업무 1회분, 명시 산출물만)를
    전제로 하므로 트랜스크립트식 복원 해석이 끼어들 여지가 없다.
  이후 단계(Prompt B → Effort Engine)는 두 케이스 공용.

3계층 분리 (설계서 §1):
  LLM      = 요구사항 변환 + 인간 작업분해 + Work Unit 매핑·수량화 (시간 출력 금지)
  Catalog  = 인간 노동 기준 (catalog.json — Work Unit별 시간분포, 프롬프트 미노출)
  Code     = 수량×시간분포 Monte Carlo 합성 → P50/P80 1회 산출 (engine.py)

실행 모드 (설계서 §7.5):
  two_pass (기본): Prompt A-avatar(요구사항 변환) → Prompt B(분해·매핑) — 2회 호출
  single   (저지연): Prompt C 단일호출
  critic=True (선택): Pass D Consistency Critic 추가 — 기본 OFF

LLM 계약: OnpremLLM.complete_json(prompt: str, max_tokens: int) -> dict
"""
import hashlib
import json
import sys
from pathlib import Path

try:
    from . import engine as _engine
    from . import prompts as _prompts
except ImportError:
    import engine as _engine
    import prompts as _prompts

_HERE = Path(__file__).resolve().parent
DEFAULT_CATALOG_PATH = _HERE / "catalog.json"

METHODOLOGY_VERSION = "0.6.0"
UNMAPPED = "UNMAPPED_WORK_UNIT"

DEFAULT_REFERENCE_WORKER = {
    "role": "competent_practitioner",
    "skill_level": "skilled",
    "gen_ai_allowed": False,
}
# 기본 산정 범위(설계서 §3): 직접 작업 + 필수 QA. 대기·조정시간 제외.
DEFAULT_SCOPE = {
    "direct_work": True,
    "mandatory_qa": True,
    "coordination": False,
    "waiting_time": False,
}


# ---------------------------------------------------------------- 검증

def validate_requirements_output(raw):
    """Prompt A 출력 검증. 반환: (parsed, notes, fatal)."""
    notes = []
    if not isinstance(raw, dict):
        return None, ["Prompt A 응답이 dict가 아님"], True
    _engine.strip_forbidden_keys(raw, notes, "requirements_output")
    reqs = raw.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        return None, notes + ["requirements가 비어 있음"], True
    valid = []
    for r in reqs:
        if not isinstance(r, dict) or not r.get("requirement_id") or not r.get("title"):
            notes.append(f"형식 불량 requirement 폐기: {r!r}"[:200])
            continue
        if not r.get("evidence"):
            notes.append(f"{r['requirement_id']}: 증거 없음 (추적성 저하)")
        valid.append(r)
    if not valid:
        return None, notes + ["유효 requirement 0개"], True
    raw["requirements"] = valid
    return raw, notes, False


_SW_ENGINES = frozenset({"SW_FUNCTIONAL", "SW_NON_FUNCTIONAL"})
_SW_DELIVERABLE_TYPES = frozenset({"software_feature", "software_nonfunctional"})


def validate_effort_input(raw, catalog, requirements_meta=None):
    """Prompt B/C 출력(EffortEngineInput.v1) 검증.

    반환: (parsed, notes, fatal).
      parsed["work_items"]     — Catalog에 존재하고 수량이 유효한 leaf 작업만
      parsed["unmapped_items"] — UNMAPPED + 검증 탈락 항목(사유 포함)

    requirements_meta: two-pass에서 Prompt A의 requirements(deliverable_type 포함).
    제공되면 SW 엔진 라우팅 교차검증에 사용 — 요구사항 산출물이 software_*가 아닌데
    SW 개발 Work Unit이 매핑되면 운영 업무의 '자동화' 문구를 시스템 구축 프로젝트로
    오해석한 스코프 오류로 보고 미산정 처리한다.
    """
    sw_ok_reqs = None
    if requirements_meta is not None:
        sw_ok_reqs = {r.get("requirement_id") for r in requirements_meta
                      if isinstance(r, dict)
                      and r.get("deliverable_type") in _SW_DELIVERABLE_TYPES}
    notes = []
    if not isinstance(raw, dict):
        return None, ["Effort 입력이 dict가 아님"], True
    _engine.strip_forbidden_keys(raw, notes, "effort_input")

    if raw.get("schema_version") != "effort_engine_input.v1":
        notes.append(f"schema_version 불일치: {raw.get('schema_version')!r}")

    work_units = catalog["work_units"]
    valid_items = []
    unmapped = [u for u in raw.get("unmapped_items", []) if isinstance(u, dict)]

    items = raw.get("work_items")
    if not isinstance(items, list):
        return None, notes + ["work_items가 리스트가 아님"], True

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            notes.append(f"work_items[{i}]: 객체가 아님 — 폐기")
            continue
        item_id = item.get("work_item_id") or f"W-auto-{i + 1:03d}"
        item["work_item_id"] = item_id
        wu_id = item.get("work_unit_id")

        def _to_unmapped(reason):
            notes.append(f"{item_id}: {reason} → unmapped 처리")
            unmapped.append({
                "work_item_id": item_id,
                "description": item.get("activity_type") or str(wu_id),
                "reason": reason,
                "candidate_engine": item.get("engine", ""),
                "evidence": item.get("evidence", []),
            })

        if wu_id == UNMAPPED:
            if not any(u.get("work_item_id") == item_id for u in unmapped):
                _to_unmapped("LLM이 UNMAPPED_WORK_UNIT으로 반환")
            continue
        if wu_id not in work_units:
            _to_unmapped(f"Catalog에 없는 work_unit_id '{wu_id}'")
            continue
        # 스코프 교차검증: SW 개발 단위인데 연결된 요구사항 산출물이 software_*가 아님
        # → '자동화' 문구를 시스템 구축으로 오해석한 것 (기존 시스템 사용 운영 업무)
        if sw_ok_reqs is not None and work_units[wu_id]["engine"] in _SW_ENGINES:
            if not (set(item.get("requirement_ids", [])) & sw_ok_reqs):
                _to_unmapped(
                    f"SW 개발 단위 '{wu_id}'가 software_* 산출물 요구사항에 연결되지 "
                    f"않음 — 운영 업무의 시스템 구축 오해석으로 판정, 미산정")
                continue
        qty_err = _engine.validate_quantity(item.get("quantity"))
        if qty_err:
            _to_unmapped(f"수량 불량: {qty_err}")
            continue
        # 단위 불일치 = 시간 폭증/붕괴 직결 (예: message 단위에 단어수 200) — 산정 금지
        cat_unit = str(work_units[wu_id].get("unit", "")).strip().lower()
        qty_unit = str(item["quantity"].get("unit", "")).strip().lower()
        if qty_unit and cat_unit and qty_unit != cat_unit:
            _to_unmapped(f"수량 단위 불일치: quantity.unit='{qty_unit}' ≠ "
                         f"Work Unit unit='{cat_unit}'")
            continue
        if not item.get("evidence"):
            notes.append(f"{item_id}: 증거 없음 (추적성 저하)")
        valid_items.append(item)

    if not valid_items and not unmapped:
        return None, notes + ["유효 work_item 0개"], True

    valid_items = _resolve_unit_conflicts(valid_items, work_units, notes)
    raw["work_items"] = valid_items
    raw["unmapped_items"] = unmapped
    return raw, notes, False


def validate_critic_output(raw, item_ids):
    """Prompt D(Consistency Critic) 출력 검증. 반환: (verdicts, notes, fatal).

    verdicts: {work_item_id: {"verdict", "issue", "reason"}} — 알 수 없는 ID는 무시.
    """
    notes = []
    if not isinstance(raw, dict):
        return None, ["Pass D 응답이 dict가 아님"], True
    vlist = raw.get("verdicts")
    if not isinstance(vlist, list) or not vlist:
        return None, notes + ["Pass D verdicts 누락"], True
    verdicts = {}
    for v in vlist:
        if not isinstance(v, dict):
            continue
        wid = v.get("work_item_id")
        verdict = v.get("verdict")
        if wid not in item_ids:
            notes.append(f"Pass D: 알 수 없는 work_item_id '{wid}' 무시")
            continue
        if verdict not in ("keep", "drop", "flag"):
            notes.append(f"Pass D: {wid} 판정값 불량 '{verdict}' → keep 처리")
            verdict = "keep"
        verdicts[wid] = {"verdict": verdict,
                         "issue": v.get("issue", ""),
                         "reason": v.get("reason", "")}
    if not verdicts:
        return None, notes + ["유효 verdict 0개"], True
    for wid in item_ids - set(verdicts):
        notes.append(f"Pass D: {wid} 판정 누락 → keep 처리")
    return verdicts, notes, False


def _resolve_unit_conflicts(items, work_units, notes):
    """Catalog의 conflicts_with 강제 (설계서 §6.2 단위 배타성).

    어떤 Work Unit이 conflicts_with를 선언하면, 같은 requirement를 공유하는
    충돌 단위 Work Item은 중복 계상으로 보고 제거한다(선언한 경량 단위가 노동을
    이미 포함). 예: writing.short_message가 있는 요구사항에 section_draft·
    edit_proofread를 얹으면 얹힌 쪽이 제거된다.
    """
    drop_ids = set()
    for item in items:
        conflicts = set(work_units[item["work_unit_id"]].get("conflicts_with", []))
        if not conflicts:
            continue
        reqs = set(item.get("requirement_ids", []))
        for other in items:
            if other is item or other["work_item_id"] in drop_ids:
                continue
            if other["work_unit_id"] in conflicts and \
                    reqs & set(other.get("requirement_ids", [])):
                drop_ids.add(other["work_item_id"])
                notes.append(
                    f"{other['work_item_id']}: {other['work_unit_id']}가 "
                    f"{item['work_unit_id']}({item['work_item_id']})와 동일 요구사항에서 "
                    f"중복 계상 — 제거(카탈로그 conflicts_with)")
    return [it for it in items if it["work_item_id"] not in drop_ids]


# ---------------------------------------------------------------- 산정기

class HumanEffortEstimator:
    """llm: complete_json(prompt, max_tokens) -> dict 를 가진 객체 (OnpremLLM 계약)."""

    def __init__(self, llm, catalog_path=DEFAULT_CATALOG_PATH, max_tokens=6000,
                 trials=_engine.DEFAULT_TRIALS, seed=_engine.DEFAULT_SEED,
                 mode="two_pass", reference_worker=None, scope=None, critic=None):
        if mode not in ("two_pass", "single"):
            raise ValueError(f"mode는 two_pass 또는 single: {mode!r}")
        # Pass D(Consistency Critic, 설계서 §7.1): 선택 안전망. 아바타 특화 A로
        # 첫 단계 해석 오류원이 제거되어 기본 OFF(호출 2회 유지) — critic=True로 활성화.
        # 결정론적 가드(단위 일치·conflicts_with·SW 교차검증)와 review 게이트는 무비용이라 상시.
        self.critic_enabled = bool(critic)
        self.llm = llm
        self.max_tokens = max_tokens
        self.trials = trials
        self.seed = seed
        self.mode = mode
        self.reference_worker = reference_worker or dict(DEFAULT_REFERENCE_WORKER)
        self.scope = scope or dict(DEFAULT_SCOPE)
        with open(catalog_path, encoding="utf-8") as f:
            self.catalog = json.load(f)

    # ---- LLM 호출 (Schema 실패 시 자동 복구 1회 — 설계서 §22)

    def _call_validated(self, prompt, validator, stage):
        raw = self.llm.complete_json(prompt, self.max_tokens)
        parsed, notes, fatal = validator(raw)
        if fatal:
            retry_prompt = (prompt + f"\n\n[재시도] 직전 응답이 유효하지 않았다: "
                            + "; ".join(notes)[:500]
                            + "\nSchema를 정확히 지켜 JSON 객체 하나만 다시 출력하라.")
            raw = self.llm.complete_json(retry_prompt, self.max_tokens)
            parsed, notes2, fatal = validator(raw)
            notes = notes + [f"{stage}: 1회 재시도 수행"] + notes2
            if fatal:
                raise ValueError(f"{stage} 출력 검증 2회 실패: " + "; ".join(notes))
        return parsed, notes

    # ---- 파이프라인

    def estimate(self, avatar_text):
        """아바타 케이스 전체 파이프라인: A-avatar(1단계) → 공용 2단계."""
        if self.mode == "two_pass":
            req_out, notes = self._call_validated(
                _prompts.build_prompt_a_avatar(avatar_text),
                validate_requirements_output, "Prompt A(avatar)")
            result = self._run_stage2(req_out, avatar_text, notes)
            result["prompt_versions"] = ([_prompts.PROMPT_A_AVATAR_VERSION]
                                         + result["prompt_versions"])
            result["input_mode"] = "avatar_description"
            result["mode"] = "two_pass"
            return result

        # single: Prompt C 단일호출 (아바타 전제 내장)
        effort_in, notes = self._call_validated(
            _prompts.build_prompt_c(avatar_text, self.catalog,
                                    self.reference_worker, self.scope),
            lambda raw: validate_effort_input(raw, self.catalog), "Prompt C")
        requirements_view = effort_in.get("requirements", [])
        review_reasons = []
        prompt_versions = [_prompts.PROMPT_C_VERSION]
        if self.critic_enabled and effort_in["work_items"]:
            notes += self._apply_critic(avatar_text, requirements_view,
                                        effort_in, review_reasons)
            prompt_versions.append(_prompts.PROMPT_D_VERSION)
        result = self._compute(effort_in, avatar_text, requirements_view,
                               notes, review_reasons)
        result["prompt_versions"] = prompt_versions
        result["input_mode"] = "avatar_description"
        result["mode"] = self.mode
        return result

    def estimate_from_requirements(self, requirements_output, source_text=""):
        """공용 2단계 진입점: 외부 1단계 모듈이 만든 requirements.v1 JSON을 받아
        Prompt B → Effort Engine을 실행한다.

        트랜스크립트 케이스는 transcript_requirements.extract_requirements()로
        1단계를 수행한 뒤 그 출력을 여기에 넘긴다 — 2단계부터는 아바타 케이스와
        완전히 동일한 코드 경로다. source_text는 critic·estimate_id용 원문(선택).
        """
        parsed, notes, fatal = validate_requirements_output(
            dict(requirements_output))
        if fatal:
            raise ValueError("requirements 입력 검증 실패: " + "; ".join(notes))
        result = self._run_stage2(parsed, source_text, notes)
        result["input_mode"] = requirements_output.get(
            "input_mode", "external_requirements")
        result["mode"] = "from_requirements"
        return result

    def _run_stage2(self, req_out, source_text, notes):
        """공용 2단계: Prompt B(분해·매핑) [+ Pass D] → 결정론적 계산."""
        effort_in, n = self._call_validated(
            _prompts.build_prompt_b(req_out, self.catalog,
                                    self.reference_worker, self.scope),
            lambda raw: validate_effort_input(
                raw, self.catalog, requirements_meta=req_out["requirements"]),
            "Prompt B")
        notes = notes + n
        review_reasons = []
        prompt_versions = [_prompts.PROMPT_B_VERSION]
        if self.critic_enabled and effort_in["work_items"]:
            notes += self._apply_critic(source_text, req_out["requirements"],
                                        effort_in, review_reasons)
            prompt_versions.append(_prompts.PROMPT_D_VERSION)
        result = self._compute(effort_in, source_text, req_out["requirements"],
                               notes, review_reasons)
        result["prompt_versions"] = prompt_versions
        return result

    def _apply_critic(self, work_order_text, requirements_view, effort_in,
                      review_reasons):
        """Pass D 실행·적용. Critic은 산정을 깎거나(drop→미산정) 지적(flag)만 가능 —
        결과를 부풀릴 수 없다. Critic 자체가 실패하면 산정은 진행하되 검토 필요 표시."""
        items = effort_in["work_items"]
        item_ids = {it["work_item_id"] for it in items}
        prompt = _prompts.build_prompt_d(work_order_text, requirements_view,
                                         items, self.catalog)
        try:
            verdicts, notes = self._call_validated(
                prompt, lambda raw: validate_critic_output(raw, item_ids), "Pass D")
        except ValueError as e:
            review_reasons.append("Pass D(Consistency Critic) 실패 — 미적용, 사람 검토 필요")
            return [f"Pass D 실패: {e}"]

        kept = []
        for it in items:
            v = verdicts.get(it["work_item_id"])
            if v and v["verdict"] == "drop":
                effort_in["unmapped_items"].append({
                    "work_item_id": it["work_item_id"],
                    "description": it.get("activity_type") or it["work_unit_id"],
                    "reason": f"Pass D drop({v['issue']}): {v['reason']}",
                    "candidate_engine": it.get("engine", ""),
                    "evidence": it.get("evidence", []),
                })
                review_reasons.append(
                    f"{it['work_item_id']} 제외({v['issue']}): {v['reason']}")
                continue
            if v and v["verdict"] == "flag":
                review_reasons.append(
                    f"{it['work_item_id']} 의심({v['issue']}): {v['reason']}")
            kept.append(it)
        effort_in["work_items"] = kept
        return notes

    def estimate_from_effort_input(self, effort_input, work_order_text=""):
        """수동 입력·Review Studio 재계산 경로(설계서 §12 recalculate) —
        검증된 EffortEngineInput만으로 재산정. LLM 미호출, 결과 재현 가능."""
        parsed, notes, fatal = validate_effort_input(effort_input, self.catalog)
        if fatal:
            raise ValueError("EffortEngineInput 검증 실패: " + "; ".join(notes))
        result = self._compute(parsed, work_order_text,
                               parsed.get("requirements", []), notes, [])
        result["prompt_versions"] = []
        result["mode"] = "recalculate"
        return result

    def _compute(self, effort_in, work_order_text, requirements_view, notes,
                 review_reasons):
        work_items = effort_in["work_items"]
        unmapped = effort_in["unmapped_items"]
        warnings = list(effort_in.get("warnings", []))
        assumptions = list(effort_in.get("assumptions", []))

        if work_items:
            eff = _engine.compute_effort(work_items, self.catalog,
                                         trials=self.trials, seed=self.seed)
            notes += eff.pop("notes")
        else:
            eff = {"p50_minutes": 0.0, "p80_minutes": 0.0, "mean_minutes": 0.0,
                   "simulation": {"method": "monte_carlo",
                                  "trials": self.trials, "seed": self.seed},
                   "item_contributions": []}
        if unmapped:
            warnings.append(f"미산정 항목 {len(unmapped)}건 — 총공수는 과소추정일 수 있음")
        if any(it.get("engine") == "PROFESSIONAL_REVIEW" for it in work_items):
            warnings.append("PROFESSIONAL_REVIEW 포함 — 전문가 검토 없이 확정값으로 사용 금지(설계서 §5.3)")

        confidences = [float(it.get("confidence", 0.5)) for it in work_items
                       if isinstance(it.get("confidence", 0.5), (int, float))]
        overall_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

        # 사람 검토 게이트 (설계서 §8): 조건 해당 시 결과를 확정값으로 쓰지 말 것
        review_reasons = list(review_reasons)
        if unmapped:
            review_reasons.append(f"미산정 항목 {len(unmapped)}건")
        if work_items and overall_conf < 0.6:
            review_reasons.append(f"매핑 신뢰도 낮음({overall_conf})")
        if any(it.get("engine") == "PROFESSIONAL_REVIEW" for it in work_items):
            review_reasons.append("전문 판단 업무 포함")

        digest = hashlib.sha1(
            (work_order_text + self.catalog["catalog_version"]).encode("utf-8")
        ).hexdigest()[:10]
        return {
            "estimate_id": f"E-{digest}",
            "methodology_version": METHODOLOGY_VERSION,
            "catalog_version": self.catalog["catalog_version"],
            "input_mode": "avatar_description",
            "reference_worker": self.reference_worker,
            "scope": self.scope,
            "effort": {
                "p50_minutes": eff["p50_minutes"],
                "p80_minutes": eff["p80_minutes"],
                "mean_minutes": eff["mean_minutes"],
                "p50_person_hours": round(eff["p50_minutes"] / 60, 2),
                "p80_person_hours": round(eff["p80_minutes"] / 60, 2),
            },
            "simulation": eff["simulation"],
            "confidence": overall_conf,
            "review_required": bool(review_reasons),
            "review_reasons": review_reasons,
            "requirements": [
                {"requirement_id": r.get("requirement_id"),
                 "title": r.get("title"),
                 "status": r.get("status", "planned"),
                 "confidence": r.get("confidence")}
                for r in requirements_view if isinstance(r, dict)
            ],
            "work_items": [
                {
                    "work_item_id": it["work_item_id"],
                    "requirement_ids": it.get("requirement_ids", []),
                    "engine": it.get("engine"),
                    "activity_type": it.get("activity_type"),
                    "work_unit_id": it["work_unit_id"],
                    "quantity": it.get("quantity"),
                    "parameters": it.get("parameters", {}),
                    "quality_tier": it.get("quality_tier", "operational"),
                    "reuse_of_work_item_id": it.get("reuse_of_work_item_id"),
                    "evidence": it.get("evidence", []),
                    "confidence": it.get("confidence"),
                }
                for it in work_items
            ],
            "item_contributions": eff["item_contributions"],
            "unscored_items": unmapped,
            "assumptions": assumptions,
            "warnings": warnings,
            "notes": notes,
            "seed_catalog_notice": "Catalog는 expert seed(confidence C, sample_count 0) — 실측 calibration 전 절대값 신뢰 금지",
        }


# ---------------------------------------------------------------- 리포트·CLI

def format_report(result):
    e = result["effort"]
    lines = [
        "Human-Equivalent Effort (숙련자, 생성형 AI 미사용)",
        f"  P50  : {e['p50_minutes']:>8.1f} min ({e['p50_person_hours']} h)",
        f"  P80  : {e['p80_minutes']:>8.1f} min ({e['p80_person_hours']} h)",
        f"  mean : {e['mean_minutes']:>8.1f} min",
        f"Simulation : {result['simulation']['method']}"
        f" trials={result['simulation']['trials']} seed={result['simulation']['seed']}",
        f"Catalog    : {result['catalog_version']} / methodology {result['methodology_version']}"
        f" / mode {result.get('mode')}",
        f"Confidence : {result['confidence']} (매핑 신뢰도 평균)",
    ]
    if result.get("review_required"):
        lines.append("Review     : 사람 검토 필요")
        for reason in result.get("review_reasons", []):
            lines.append(f"  - {reason}")
    if result["requirements"]:
        lines.append("Requirements:")
        for r in result["requirements"]:
            lines.append(f"  - {r['requirement_id']}: {r['title']} [{r['status']}]")
    if result["item_contributions"]:
        lines.append("Work Items (평균 기여 상위):")
        for c in result["item_contributions"][:10]:
            lines.append(f"  - {c['work_item_id']} {c['work_unit_id']}"
                         f" ({c['engine']}, {c['quality_tier']})"
                         f" : {c['mean_minutes']:.1f} min ({c['share'] * 100:.1f}%)")
    for u in result["unscored_items"]:
        lines.append(f"  unscored: {u.get('work_item_id')} — {u.get('reason')}")
    for w in result["warnings"]:
        lines.append(f"  warning: {w}")
    for n in result["notes"]:
        lines.append(f"  note: {n}")
    lines.append(f"  ({result['seed_catalog_notice']})")
    return "\n".join(lines)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("usage: python estimator.py <work_order.txt> [--json] [--single] "
              "[--seed=N] [--trials=N]", file=sys.stderr)
        return 2
    seed = _engine.DEFAULT_SEED
    trials = _engine.DEFAULT_TRIALS
    for f in flags:
        if f.startswith("--seed="):
            seed = int(f.split("=", 1)[1])
        elif f.startswith("--trials="):
            trials = int(f.split("=", 1)[1])
    mode = "single" if "--single" in flags else "two_pass"
    work_order = Path(args[0]).read_text(encoding="utf-8")

    from onprem_llm_sim import OnpremLLM
    est = HumanEffortEstimator(OnpremLLM(), mode=mode, seed=seed, trials=trials)
    result = est.estimate(work_order)
    if "--json" in flags:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
