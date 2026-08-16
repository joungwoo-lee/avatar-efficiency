# -*- coding: utf-8 -*-
"""단위테스트(mock LLM) + --live 프록시 실호출 테스트.

    python test_estimator.py            # 오프라인 (mock)
    python test_estimator.py --live     # + onprem_llm_sim 프록시 실호출 (two-pass)
"""
import copy
import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _d in ("requirement-based", "shared", "record-actions",
           "requirement-actions"):
    _p = str(_HERE / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import engine  # noqa: E402
from estimator import (HumanEffortEstimator, DEFAULT_CATALOG_PATH,  # noqa: E402
                       validate_effort_input, validate_requirements_output)

with open(DEFAULT_CATALOG_PATH, encoding="utf-8") as f:
    CATALOG = json.load(f)

SPEC = (Path(__file__).parent / "examples" / "sample_spec.txt").read_text(encoding="utf-8")

# ---------------------------------------------------------------- mock 데이터

REQ_OUT = {
    "schema_version": "requirements.v1",
    "prompt_version": "work_order_requirement_extractor.v1",
    "analysis_language": "ko",
    "input_mode": "work_order",
    "requirements": [{
        "requirement_id": "R-001",
        "title": "경쟁사 5곳 월간 동향 요약 보고서 작성",
        "description": "경쟁사 5곳의 30일 제품·가격 변화를 조사·검증하고 2,000단어 보고서 작성",
        "deliverable_type": "document",
        "status": "planned",
        "requested_quantities": [
            {"name": "competitors", "distribution": "point", "value": 5,
             "min": None, "mode": None, "max": None, "unit": "organization",
             "basis": "explicit", "confidence": 0.95}],
        "acceptance_criteria": ["5개 경쟁사 포함", "가격 변동 10건 출처 검증"],
        "constraints": [], "quality_attributes": [], "dependencies": [],
        "evidence": [{"source_id": "WO-01", "locator": "line:1-13",
                      "supports": "지침 전체"}],
        "confidence": 0.9,
    }],
    "assumptions": [], "warnings": [],
}


def _item(iid, wu, qty, **kw):
    base = {
        "work_item_id": iid, "requirement_ids": ["R-001"], "work_package_id": "WP-001",
        "engine": CATALOG["work_units"].get(wu, {}).get("engine", "KNOWLEDGE_RESEARCH"),
        "activity_type": wu, "work_unit_id": wu, "quantity": qty,
        "parameters": {}, "quality_tier": "operational",
        "role_profile": "skilled_practitioner", "dependencies": [],
        "reuse_of_work_item_id": None,
        "evidence": [{"source_id": "WO-01", "locator": "line:5"}],
        "confidence": 0.85,
    }
    base.update(kw)
    return base


EFFORT_OUT = {
    "schema_version": "effort_engine_input.v1",
    "prompt_version": "work_mapper.v1",
    "catalog_version": CATALOG["catalog_version"],
    "input_mode": "work_order",
    "reference_worker": {"role": "competent_practitioner",
                         "skill_level": "skilled", "gen_ai_allowed": False},
    "scope": {"direct_work": True, "mandatory_qa": True,
              "coordination": False, "waiting_time": False},
    "requirements": [{"requirement_id": "R-001",
                      "title": "경쟁사 5곳 월간 동향 요약 보고서 작성",
                      "description": "...", "status": "planned",
                      "evidence": [{"source_id": "WO-01", "locator": "line:1-13"}],
                      "confidence": 0.9}],
    "work_packages": [{"work_package_id": "WP-001", "requirement_ids": ["R-001"],
                       "name": "경쟁사 동향 조사·보고", "parent_work_package_id": None}],
    "work_items": [
        _item("W-001", "research.source_search",
              {"distribution": "point", "value": 10, "unit": "query"}),
        _item("W-002", "research.source_deep_review",
              {"distribution": "triangular", "min": 5, "mode": 5, "max": 8,
               "unit": "source"},
              parameters={"source_complexity": "professional"}),
        _item("W-003", "research.cross_verification",
              {"distribution": "point", "value": 10, "unit": "fact"}),
        _item("W-004", "writing.section_draft",
              {"distribution": "point", "value": 4, "unit": "section"},
              quality_tier="decision_grade"),
        _item("W-005", "writing.edit_proofread",
              {"distribution": "point", "value": 4, "unit": "page"}),
    ],
    "unmapped_items": [],
    "assumptions": ["섹션 4개로 가정"], "warnings": [],
}


def _critic_keep_all(prompt):
    """Prompt D에 나열된 모든 work_item_id에 keep 판정."""
    import re
    ids = sorted(set(re.findall(r'"work_item_id":\s*"(W[^"]+)"', prompt)))
    return {
        "schema_version": "consistency_review.v1",
        "prompt_version": "consistency_critic.v1",
        "verdicts": [{"work_item_id": i, "verdict": "keep",
                      "issue": "none", "reason": ""} for i in ids],
        "requirement_issues": [], "overall_notes": [],
    }


class MockLLM:
    """프롬프트 내용을 감지해 Prompt A/B/C/D·agent-path 응답을 돌려준다. 큐 주입도 지원."""

    def __init__(self, queue=None, critic_out=None):
        self.queue = list(queue) if queue else None
        self.critic_out = critic_out  # None이면 전원 keep
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        if self.queue is not None:
            return self.queue.pop(0)
        if ("Avatar Task Requirement Converter" in prompt
                or "Planned Requirement Reconstruction Engine" in prompt):
            return copy.deepcopy(REQ_OUT)
        if "Consistency Critic" in prompt:  # Pass D
            return copy.deepcopy(self.critic_out) if self.critic_out \
                else _critic_keep_all(prompt)
        return copy.deepcopy(EFFORT_OUT)


# ---------------------------------------------------------------- 엔진

class TestEngine(unittest.TestCase):
    def test_determinism_same_seed(self):
        items = copy.deepcopy(EFFORT_OUT["work_items"])
        a = engine.compute_effort(items, CATALOG, trials=500, seed=7)
        b = engine.compute_effort(items, CATALOG, trials=500, seed=7)
        self.assertEqual(a["p50_minutes"], b["p50_minutes"])
        self.assertEqual(a["p80_minutes"], b["p80_minutes"])

    def test_p80_gte_p50_gt_zero(self):
        r = engine.compute_effort(copy.deepcopy(EFFORT_OUT["work_items"]),
                                  CATALOG, trials=500, seed=1)
        self.assertGreater(r["p50_minutes"], 0)
        self.assertGreaterEqual(r["p80_minutes"], r["p50_minutes"])

    def test_quality_tier_scaling(self):
        draft = [_item("W-1", "writing.section_draft",
                       {"distribution": "point", "value": 4, "unit": "section"},
                       quality_tier="draft")]
        audit = [_item("W-1", "writing.section_draft",
                       {"distribution": "point", "value": 4, "unit": "section"},
                       quality_tier="audit_grade")]
        r_d = engine.compute_effort(draft, CATALOG, trials=500, seed=3)
        r_a = engine.compute_effort(audit, CATALOG, trials=500, seed=3)
        self.assertGreater(r_a["p50_minutes"], r_d["p50_minutes"])

    def test_parameter_delta_adds_time(self):
        plain = [_item("W-1", "research.source_deep_review",
                       {"distribution": "point", "value": 5, "unit": "source"})]
        param = [_item("W-1", "research.source_deep_review",
                       {"distribution": "point", "value": 5, "unit": "source"},
                       parameters={"source_complexity": "technical"})]
        r_p = engine.compute_effort(plain, CATALOG, trials=500, seed=3)
        r_x = engine.compute_effort(param, CATALOG, trials=500, seed=3)
        self.assertGreater(r_x["p50_minutes"], r_p["p50_minutes"])

    def test_quantity_validation(self):
        self.assertIsNone(engine.validate_quantity(
            {"distribution": "point", "value": 3, "unit": "x"}))
        self.assertIsNotNone(engine.validate_quantity(
            {"distribution": "point", "value": -1, "unit": "x"}))
        self.assertIsNotNone(engine.validate_quantity(
            {"distribution": "triangular", "min": 5, "mode": 3, "max": 8, "unit": "x"}))
        self.assertIsNone(engine.validate_quantity(
            {"distribution": "discrete", "values": [1, 2], "probabilities": [0.5, 0.5],
             "unit": "x"}))

    def test_lightweight_units_exist_and_small(self):
        # 소형 업무 과잉산정 방지 — 경량 단위 6종 존재 + mode ≤ 10분
        for wu_id in ("research.document_skim", "research.quick_lookup",
                      "writing.short_message", "writing.quick_edit",
                      "analysis.quick_calculation", "office.simple_operation"):
            self.assertIn(wu_id, CATALOG["work_units"], wu_id)
            self.assertLessEqual(CATALOG["work_units"][wu_id]["time_model"]["mode"], 10)

    def test_small_task_sane_minutes(self):
        # 회귀: 메일 회신급 소형 업무(훑어읽기 1 + 단문 1)가 한 자릿수~수십분대인지
        items = [
            _item("W-1", "research.document_skim",
                  {"distribution": "point", "value": 1, "unit": "document"}),
            _item("W-2", "writing.short_message",
                  {"distribution": "point", "value": 1, "unit": "message"}),
        ]
        r = engine.compute_effort(items, CATALOG, trials=1000, seed=1)
        self.assertGreater(r["p50_minutes"], 5)
        self.assertLess(r["p80_minutes"], 40)

    def test_forbidden_key_strip(self):
        notes = []
        obj = {"work_items": [{"work_unit_id": "a", "minutes": 5,
                               "nested": {"p50": 1}}], "hours": 2}
        engine.strip_forbidden_keys(obj, notes)
        self.assertNotIn("hours", obj)
        self.assertNotIn("minutes", obj["work_items"][0])
        self.assertNotIn("p50", obj["work_items"][0]["nested"])
        self.assertEqual(len(notes), 3)


# ---------------------------------------------------------------- 검증

class TestValidation(unittest.TestCase):
    def test_unknown_work_unit_goes_unmapped(self):
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"].append(_item("W-BAD", "nonexistent.unit",
                                       {"distribution": "point", "value": 1, "unit": "x"}))
        parsed, notes, fatal = validate_effort_input(raw, CATALOG)
        self.assertFalse(fatal)
        self.assertEqual(len(parsed["work_items"]), 5)
        self.assertEqual(parsed["unmapped_items"][0]["work_item_id"], "W-BAD")

    def test_bad_quantity_goes_unmapped(self):
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"][0]["quantity"] = {"distribution": "point", "value": -3,
                                            "unit": "query"}
        parsed, notes, fatal = validate_effort_input(raw, CATALOG)
        self.assertFalse(fatal)
        self.assertEqual(len(parsed["work_items"]), 4)
        self.assertTrue(any("수량 불량" in u["reason"] for u in parsed["unmapped_items"]))

    def test_sw_engine_scope_guard(self):
        # 회귀: 운영 업무('RCA 자동화')를 SW 구축으로 오해석 — deliverable_type이
        # software_*가 아닌 요구사항에 SW 개발 단위가 붙으면 미산정
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"].append(_item(
            "W-SW", "sw.functional_process",
            {"distribution": "point", "value": 10, "unit": "cfp"}))
        meta = [{"requirement_id": "R-001", "deliverable_type": "document"}]
        parsed, notes, fatal = validate_effort_input(raw, CATALOG,
                                                     requirements_meta=meta)
        self.assertFalse(fatal)
        self.assertTrue(any(u["work_item_id"] == "W-SW"
                            and "오해석" in u["reason"]
                            for u in parsed["unmapped_items"]))

    def test_sw_engine_allowed_for_software_requirement(self):
        # 진짜 SW 개발 요구사항이면 SW 단위 유지
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"] = [_item(
            "W-SW", "sw.functional_process",
            {"distribution": "point", "value": 10, "unit": "cfp"})]
        meta = [{"requirement_id": "R-001", "deliverable_type": "software_feature"}]
        parsed, notes, fatal = validate_effort_input(raw, CATALOG,
                                                     requirements_meta=meta)
        self.assertFalse(fatal)
        self.assertEqual(parsed["work_items"][0]["work_item_id"], "W-SW")
        # 메타 미제공(single 모드·직접 재계산)이면 가드 미적용 — 기존 동작 유지
        raw2 = copy.deepcopy(EFFORT_OUT)
        raw2["work_items"] = [_item(
            "W-SW", "sw.functional_process",
            {"distribution": "point", "value": 10, "unit": "cfp"})]
        parsed2, _, fatal2 = validate_effort_input(raw2, CATALOG)
        self.assertFalse(fatal2)
        self.assertEqual(len(parsed2["work_items"]), 1)

    def test_conflicting_units_deduped(self):
        # 회귀: 같은 요구사항에 short_message + section_draft/edit 중복 계상 시 제거
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"] = [
            _item("W-1", "writing.short_message",
                  {"distribution": "point", "value": 1, "unit": "message"}),
            _item("W-2", "writing.section_draft",
                  {"distribution": "point", "value": 2, "unit": "section"}),
            _item("W-3", "writing.edit_proofread",
                  {"distribution": "point", "value": 1, "unit": "page"}),
        ]
        parsed, notes, fatal = validate_effort_input(raw, CATALOG)
        self.assertFalse(fatal)
        kept = [it["work_item_id"] for it in parsed["work_items"]]
        self.assertEqual(kept, ["W-1"])
        self.assertTrue(any("중복 계상" in n for n in notes))

    def test_unit_mismatch_goes_unmapped(self):
        # 회귀: message 단위 Work Unit에 단어수 200을 넣는 인플레이션 차단
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"].append(_item(
            "W-MISMATCH", "writing.short_message",
            {"distribution": "point", "value": 200, "unit": "word"}))
        parsed, notes, fatal = validate_effort_input(raw, CATALOG)
        self.assertFalse(fatal)
        self.assertTrue(any(u["work_item_id"] == "W-MISMATCH"
                            and "단위 불일치" in u["reason"]
                            for u in parsed["unmapped_items"]))

    def test_forbidden_time_fields_stripped_and_noted(self):
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"][0]["minutes"] = 99
        parsed, notes, fatal = validate_effort_input(raw, CATALOG)
        self.assertFalse(fatal)
        self.assertNotIn("minutes", parsed["work_items"][0])
        self.assertTrue(any("금지 필드" in n for n in notes))

    def test_fatal_on_empty(self):
        _, notes, fatal = validate_effort_input({"schema_version": "effort_engine_input.v1",
                                                 "work_items": []}, CATALOG)
        self.assertTrue(fatal)
        _, notes, fatal = validate_requirements_output({"requirements": []})
        self.assertTrue(fatal)


# ---------------------------------------------------------------- 파이프라인

class TestEstimatorFlow(unittest.TestCase):
    def test_two_pass_estimate(self):
        est = HumanEffortEstimator(MockLLM(), trials=500, seed=42)
        r = est.estimate(SPEC)
        self.assertGreater(r["effort"]["p50_minutes"], 0)
        self.assertGreaterEqual(r["effort"]["p80_minutes"], r["effort"]["p50_minutes"])
        self.assertEqual(r["catalog_version"], CATALOG["catalog_version"])
        self.assertEqual(r["mode"], "two_pass")
        self.assertEqual(len(r["work_items"]), 5)
        self.assertEqual(r["requirements"][0]["requirement_id"], "R-001")

    def test_two_pass_calls_and_no_rate_leak(self):
        llm = MockLLM()
        est = HumanEffortEstimator(llm, trials=200, seed=42)
        est.estimate(SPEC)
        self.assertEqual(len(llm.calls), 2)  # A-avatar + B (critic 기본 OFF)
        for prompt in llm.calls:
            self.assertNotIn("time_model", prompt)
            self.assertNotIn("min_per_unit", prompt)
            self.assertNotIn('"mode": 20', prompt)  # 시간분포 파라미터 미노출

    def test_single_mode(self):
        llm = MockLLM()
        est = HumanEffortEstimator(llm, trials=200, seed=42, mode="single")
        r = est.estimate(SPEC)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(r["mode"], "single")
        self.assertGreater(r["effort"]["p50_minutes"], 0)

    def test_reproducible_same_input(self):
        r1 = HumanEffortEstimator(MockLLM(), trials=500, seed=42).estimate(SPEC)
        r2 = HumanEffortEstimator(MockLLM(), trials=500, seed=42).estimate(SPEC)
        self.assertEqual(r1["effort"], r2["effort"])
        self.assertEqual(r1["estimate_id"], r2["estimate_id"])

    def test_retry_on_invalid_then_valid(self):
        llm = MockLLM(queue=[{"garbage": True}, copy.deepcopy(REQ_OUT),
                             copy.deepcopy(EFFORT_OUT)])
        est = HumanEffortEstimator(llm, trials=200, seed=42)
        r = est.estimate(SPEC)
        self.assertEqual(len(llm.calls), 3)
        self.assertTrue(any("재시도" in n for n in r["notes"]))
        self.assertGreater(r["effort"]["p50_minutes"], 0)

    def test_critic_drops_invented_work(self):
        # Pass D가 오분류 항목(drop) 판정 → 미산정 + review_required
        critic = {
            "schema_version": "consistency_review.v1",
            "verdicts": (
                [{"work_item_id": f"W-00{i}", "verdict": "keep",
                  "issue": "none", "reason": ""} for i in (1, 2, 3, 5)]
                + [{"work_item_id": "W-004", "verdict": "drop",
                    "issue": "invented_requirement",
                    "reason": "지침서에 없는 산출물"}]),
            "requirement_issues": [], "overall_notes": [],
        }
        est = HumanEffortEstimator(MockLLM(critic_out=critic), trials=200, seed=42,
                                   critic=True)
        r = est.estimate(SPEC)
        self.assertEqual(len(r["work_items"]), 4)
        self.assertTrue(any(u["work_item_id"] == "W-004"
                            and "Pass D drop" in u["reason"]
                            for u in r["unscored_items"]))
        self.assertTrue(r["review_required"])
        self.assertTrue(any("W-004" in reason for reason in r["review_reasons"]))

    def test_critic_failure_does_not_block(self):
        # Pass D 2회 실패해도 산정은 진행 + 검토 필요 표시
        llm = MockLLM(queue=[copy.deepcopy(REQ_OUT), copy.deepcopy(EFFORT_OUT),
                             {"garbage": True}, {"garbage": True}])
        est = HumanEffortEstimator(llm, trials=200, seed=42, critic=True)
        r = est.estimate(SPEC)
        self.assertGreater(r["effort"]["p50_minutes"], 0)
        self.assertTrue(r["review_required"])
        self.assertTrue(any("Pass D" in reason for reason in r["review_reasons"]))

    def test_review_not_required_when_clean(self):
        r = HumanEffortEstimator(MockLLM(), trials=200, seed=42).estimate(SPEC)
        self.assertFalse(r["review_required"])
        self.assertEqual(r["review_reasons"], [])

    def test_fail_after_two_invalid(self):
        llm = MockLLM(queue=[{"garbage": True}, {"garbage": True}])
        est = HumanEffortEstimator(llm, trials=200, seed=42)
        with self.assertRaises(ValueError):
            est.estimate(SPEC)

    def test_estimate_from_requirements_shared_stage2(self):
        # 공용 2단계 진입점: 외부 1단계(트랜스크립트 등) 출력 → B+엔진만 실행
        llm = MockLLM()
        est = HumanEffortEstimator(llm, trials=500, seed=42)
        r = est.estimate_from_requirements(copy.deepcopy(REQ_OUT), SPEC)
        self.assertEqual(len(llm.calls), 1)  # Prompt B만
        self.assertEqual(r["mode"], "from_requirements")
        self.assertGreater(r["effort"]["p50_minutes"], 0)
        # 같은 requirements를 아바타 two_pass의 2단계에 넣은 것과 결과 동일해야 함
        r2 = HumanEffortEstimator(MockLLM(), trials=500, seed=42).estimate(SPEC)
        self.assertEqual(r["effort"], r2["effort"])

    def test_estimate_from_requirements_rejects_garbage(self):
        est = HumanEffortEstimator(MockLLM(), trials=200, seed=42)
        with self.assertRaises(ValueError):
            est.estimate_from_requirements({"requirements": []})

    def test_transcript_extractor_module(self):
        from transcript_requirements import (extract_requirements,
                                             build_prompt_a_transcript)
        prompt = build_prompt_a_transcript("사용자: 보고서 만들어줘\nAI: 완료했습니다")
        self.assertIn("<TRANSCRIPT", prompt)
        self.assertIn("Delivered Requirement Reconstruction Engine", prompt)
        self.assertNotIn("time_model", prompt)
        llm = MockLLM(queue=[copy.deepcopy(REQ_OUT)])
        req, notes = extract_requirements(llm, "사용자: 보고서 만들어줘")
        self.assertEqual(req["requirements"][0]["requirement_id"], "R-001")
        # 추출 결과가 공용 2단계로 그대로 이어지는지
        r = HumanEffortEstimator(MockLLM(), trials=200, seed=42) \
            .estimate_from_requirements(req)
        self.assertGreater(r["effort"]["p50_minutes"], 0)

    def test_recalculate_without_llm(self):
        est = HumanEffortEstimator(MockLLM(), trials=500, seed=42)
        r = est.estimate_from_effort_input(copy.deepcopy(EFFORT_OUT), SPEC)
        self.assertEqual(r["mode"], "recalculate")
        self.assertGreater(r["effort"]["p50_minutes"], 0)

    def test_professional_review_warning(self):
        raw = copy.deepcopy(EFFORT_OUT)
        raw["work_items"].append(_item(
            "W-PR", "review.document_clause_review",
            {"distribution": "point", "value": 3, "unit": "clause"}))
        est = HumanEffortEstimator(MockLLM(), trials=200, seed=42)
        r = est.estimate_from_effort_input(raw, SPEC)
        self.assertTrue(any("PROFESSIONAL_REVIEW" in w for w in r["warnings"]))


# ---------------------------------------------------------------- compat


MAIL_SPEC = """업무 제목: 메일 회신 초안 작성
소속 역할: PM
할 일: 첨부 보고서(약 800단어) 검토 후 부서장 승인 요청 회신(200단어 내외) 작성
완료조건: 회신 1건 발송 준비 완료
연결된 스킬: mail-draft, summarize"""

RCA_SPEC = """업무 제목: CP Log KG 및 State Graph 기반 RCA 자동화
소속 역할: 공정 이상분석 엔지니어
할 일: 신규 CP 테스트 로그 이상 발생 시 Knowledge Graph와 State Graph를 조회해 근본원인 후보를 도출하고 RCA 보고서를 작성한다.
업무 상세:
- jira 스킬로 이상 티켓 1건 확인
- RAG 스킬로 관련 로그·과거 사례 조회 (약 5건)
- 원인 후보 2~3개 비교 분석
- RCA 보고서 1건(약 500단어) 작성 및 티켓 업데이트
완료조건: RCA 보고서 1건, 티켓 코멘트 업데이트
연결된 스킬: jira, rag-search, log-analyzer"""


def _live():
    from onprem_llm_sim import OnpremLLM
    from estimator import format_report
    est = HumanEffortEstimator(OnpremLLM())
    result = est.estimate(SPEC)
    print(format_report(result))

    # 인플레이션 회귀: 소형 업무(메일 회신)가 숙련자+일반도구 기준 상식 범위인지
    print("\n--- inflation regression (mail spec) ---")
    r = HumanEffortEstimator(OnpremLLM()).estimate(MAIL_SPEC)
    p50 = r["effort"]["p50_minutes"]
    n_items = len(r["work_items"])
    ok = 5 <= p50 <= 90 and n_items <= 5
    print(f"P50={p50} min, work_items={n_items} "
          f"→ {'PASS' if ok else 'FAIL'} (기대: 5~90 min, ≤5 items)")
    if not ok:
        for c in r["item_contributions"]:
            print(f"  {c['work_item_id']} {c['work_unit_id']}: {c['mean_minutes']} min")
    assert ok, f"소형 업무 인플레이션 회귀 실패: P50={p50}, items={n_items}"

    # 스코프 회귀: '자동화' 제목의 운영 업무가 SW 구축 프로젝트로 오해석되지 않는지
    print("\n--- scope regression (RCA spec) ---")
    r = HumanEffortEstimator(OnpremLLM()).estimate(RCA_SPEC)
    p50 = r["effort"]["p50_minutes"]
    sw_units = [c["work_unit_id"] for c in r["item_contributions"]
                if c["work_unit_id"].startswith("sw.")]
    ok = not sw_units and 10 <= p50 <= 600
    print(f"P50={p50} min, sw_units={sw_units} "
          f"→ {'PASS' if ok else 'FAIL'} (기대: SW 단위 0개, 10~600 min)")
    if not ok:
        for c in r["item_contributions"]:
            print(f"  {c['work_item_id']} {c['work_unit_id']}: {c['mean_minutes']} min")
    assert ok, f"운영 업무 SW 오해석 회귀 실패: P50={p50}, sw={sw_units}"





class TestPrimitiveEffort(unittest.TestCase):
    class _Mock:
        def __init__(self, queue):
            self.queue = list(queue)
            self.calls = []

        def complete_json(self, prompt, max_tokens):
            self.calls.append(prompt)
            return self.queue.pop(0)

    def test_hand_check(self):
        # read 800×0.005=4 + draft 200×0.05=10 + verify 1×3=17
        from primitive_effort import estimate_human_min
        out = {"human": [{"primitive": "read", "count": 800},
                         {"primitive": "draft", "count": 200},
                         {"primitive": "verify", "count": 1}],
               "rationale": "t"}
        r = estimate_human_min(self._Mock([out]), "spec")
        self.assertAlmostEqual(r["human_min"], 17.0, places=2)

    def test_no_rate_leak_and_retry(self):
        from primitive_effort import estimate_human_min, build_prompt
        from agent_effort import load_rates
        prompt = build_prompt("spec", load_rates())
        self.assertNotIn("min_per_unit", prompt)
        self.assertNotIn("0.005", prompt)
        llm = self._Mock([{"garbage": 1},
                          {"human": [{"primitive": "read", "count": 100}]}])
        r = estimate_human_min(llm, "spec")
        self.assertEqual(len(llm.calls), 2)
        self.assertAlmostEqual(r["human_min"], 0.5, places=2)

    def test_bad_items_dropped(self):
        from primitive_effort import validate_llm_output
        from agent_effort import load_rates
        out = {"human": [{"primitive": "nonexistent", "count": 5},
                         {"primitive": "read", "count": -1},
                         {"primitive": "read", "count": 100}]}
        parsed, notes, fatal = validate_llm_output(out, load_rates())
        self.assertFalse(fatal)
        self.assertEqual(len(parsed["human"]), 1)

    def test_record_stats_anchor(self):
        # 구방식도 record_stats를 주면 신방식과 같은 닻이 적용된다:
        # 구조적 읽기 = 정독 실측 600 + 훑기 실측 400×0.05 + 입력 40 = 660
        # (LLM 9999 대체) / 작성 = 실측 500 상한 (LLM 800 절단)
        from primitive_effort import estimate_human_min
        out = {"human": [{"primitive": "read", "count": 9999},
                         {"primitive": "draft", "count": 800}],
               "rationale": "t"}
        stats = {"contributed_docs": 2, "scanned_docs": 1, "waste_docs": 3,
                 "deep_words": 600, "skim_words": 400, "waste_words": 900,
                 "input_words": 40, "reviewed_words": 20000,
                 "artifact_words": 500}
        r = estimate_human_min(self._Mock([out]), "spec", record_stats=stats)
        counts = {b["primitive"]: b["count"] for b in r["breakdown"]}
        self.assertEqual(counts["read"], 660)
        self.assertEqual(counts["draft"], 500)
        self.assertEqual(r["anchors"]["structured_read_words"], 660)
        # read 660×0.005=3.3 + draft 500×0.05=25 = 28.3
        self.assertAlmostEqual(r["human_min"], 28.3, places=2)


class TestRequirementActions(unittest.TestCase):
    class _Mock:
        def __init__(self, queue):
            self.queue = list(queue); self.calls = []

        def complete_json(self, prompt, max_tokens):
            self.calls.append(prompt); return self.queue.pop(0)

    REQ = {"requirements": [{
        "title": "경쟁사 비교 보고서 작성",
        "requested_quantities": [
            {"name": "보고서", "distribution": "point", "value": 2000,
             "unit": "단어", "basis": "explicit", "confidence": 0.9}],
        "acceptance_criteria": ["5개사 포함", "검증 완료", "2000단어 내외"],
    }]}

    def test_anchor_substitution(self):
        from requirement_actions import estimate_actions_from_requirements
        out = {"human": [{"primitive": "read", "count": 9999},
                         {"primitive": "draft", "count": 100},
                         {"primitive": "edit", "count": 100},
                         {"primitive": "verify", "count": 10}],
               "rationale": "t"}
        r = estimate_actions_from_requirements(
            self._Mock([out]), self.REQ,
            record_stats={"reviewed_words": 3000, "input_words": 0,
                          "artifact_words": 8888})
        bd = {b["primitive"]: b for b in r["breakdown"]}
        # read: 실측 3000으로 대체 (LLM 9999 무시)
        self.assertEqual(bd["read"]["count"], 3000)
        # draft+edit: 명시 2000단어가 실측 8888보다 우선, 비율(1:1) 보존
        self.assertEqual(bd["draft"]["count"] + bd["edit"]["count"], 2000)
        # verify: 완료조건 3개로 대체 (LLM 10 무시)
        self.assertEqual(bd["verify"]["count"], 3)
        self.assertTrue(any("닻 적용" in n for n in r["notes"]))
        # 총액 수기검산: read 3000×0.005=15 + (draft1000×0.05+edit1000×0.02)=70 + verify 3×3=9
        self.assertAlmostEqual(r["human_min"], 94.0, places=1)

    def test_write_split_anchor(self):
        # §28: draft/edit 분류를 도구 실측(Write:Edit)으로 통일.
        # 실측 분할 200:300 → LLM이 전부 draft(900)로 찍어도 총량 상한(500)을
        # 실측 비율로 재배분: draft 200 / edit 300.
        from requirement_actions import estimate_actions_from_requirements
        out = {"human": [{"primitive": "draft", "count": 900}]}
        req = {"requirements": [{"title": "수정 작업",
                                 "requested_quantities": [],
                                 "acceptance_criteria": []}]}
        r = estimate_actions_from_requirements(
            self._Mock([out]), req,
            record_stats={"reviewed_words": 0, "input_words": 0,
                          "artifact_words": 500,
                          "out_draft_words": 200, "out_edit_words": 300})
        bd = {b["primitive"]: b for b in r["breakdown"]}
        self.assertEqual(bd["draft"]["count"], 200)
        self.assertEqual(bd["edit"]["count"], 300)   # LLM 누락 → 실측으로 추가
        # 200×0.05 + 300×0.02 = 16.0
        self.assertAlmostEqual(r["human_min"], 16.0, places=1)
        self.assertTrue(any("쓰기 분할" in n for n in r["notes"]))

    def test_verify_added_when_missing(self):
        from requirement_actions import estimate_actions_from_requirements
        out = {"human": [{"primitive": "draft", "count": 500}]}
        r = estimate_actions_from_requirements(self._Mock([out]), self.REQ)
        bd = {b["primitive"]: b for b in r["breakdown"]}
        self.assertEqual(bd["verify"]["count"], 3)  # LLM 누락 → 완료조건 수로 추가
        self.assertEqual(bd["draft"]["count"], 2000)  # 명시 분량으로 대체

    def test_measured_anchor_is_cap_only(self):
        # 실측치 닻은 상한 — LLM이 더 작게 추정하면 끌어올리지 않는다
        from requirement_actions import estimate_actions_from_requirements
        req = {"requirements": [{"title": "검토 보고", "requested_quantities": [],
                                 "acceptance_criteria": ["a"]}]}
        out = {"human": [{"primitive": "read", "count": 500},
                         {"primitive": "draft", "count": 100}]}
        r = estimate_actions_from_requirements(
            self._Mock([out]), req,
            record_stats={"reviewed_words": 9000, "input_words": 0,
                          "artifact_words": 8000})
        bd = {b["primitive"]: b for b in r["breakdown"]}
        self.assertEqual(bd["read"]["count"], 500)    # 상한 이내 → 유지 (AI 과대 미상속)
        self.assertEqual(bd["draft"]["count"], 100)   # 실측 산출물도 상한만
        out2 = {"human": [{"primitive": "read", "count": 20000}]}
        r2 = estimate_actions_from_requirements(
            self._Mock([out2]), req,
            record_stats={"reviewed_words": 9000, "input_words": 0,
                          "artifact_words": 0})
        bd2 = {b["primitive"]: b for b in r2["breakdown"]}
        self.assertEqual(bd2["read"]["count"], 9000)  # 상한 초과 → 절단

    def test_task_derived_reading(self):
        # 할일 수량("출처 10건") × 건당 선별 정독량(300단어) = 사람 읽기 목표
        from requirement_actions import estimate_actions_from_requirements
        req = {"requirements": [{
            "title": "가격 변동 검증",
            "requested_quantities": [
                {"name": "출처", "value": 10, "unit": "출처"}],
            "acceptance_criteria": ["검증 완료"]}]}
        out = {"human": [{"primitive": "read", "count": 80000},
                         {"primitive": "verify", "count": 1}]}
        r = estimate_actions_from_requirements(
            self._Mock([out]), req,
            record_stats={"reviewed_words": 50000, "input_words": 0,
                          "artifact_words": 0})
        bd = {b["primitive"]: b for b in r["breakdown"]}
        # AI는 5만 단어를 읽었지만 사람 목표 = 10건×300 = 3,000단어
        self.assertEqual(bd["read"]["count"], 3000)
        self.assertEqual(r["anchors"]["task_read_words"], 3000)
        # 실측이 task보다 작으면 실측이 상한 (존재하는 자료보다 많이 읽을 수 없음)
        r2 = estimate_actions_from_requirements(
            self._Mock([{"human": [{"primitive": "read", "count": 500}]}]), req,
            record_stats={"reviewed_words": 1000, "input_words": 0,
                          "artifact_words": 0})
        bd2 = {b["primitive"]: b for b in r2["breakdown"]}
        self.assertEqual(bd2["read"]["count"], 1000)

    def test_measured_grade_reading(self):
        # 실측 등급 + 구간·블록 분해(§26): 기여 파일이라도 증거(편집 원문·답변
        # 인용) 닿은 블록만 정독, 나머지 블록·항해 파일은 훑기, 헛읽기 0.
        # 같은 구간 재읽기 중복 제거.
        import tempfile, os, json as _json
        from requirement_actions import (collect_record_stats,
                                         estimate_actions_from_requirements)
        a_body = "alpha " * 200 + "beta " * 1000   # 6블록: alpha 1블록 + beta 5블록
        lines = [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t2", "name": "Read",
                 "input": {"file_path": "b.py"}},
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "a.py"}},
                {"type": "tool_use", "id": "t3", "name": "Read",
                 "input": {"file_path": "c.py"}},
                {"type": "tool_use", "id": "t4", "name": "Read",
                 "input": {"file_path": "a.py"}}]}},   # 같은 구간 재읽기
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t2", "content": "감마 " * 400},
                {"type": "tool_result", "tool_use_id": "t1", "content": a_body},
                {"type": "tool_result", "tool_use_id": "t3", "content": "델타 " * 900},
                {"type": "tool_result", "tool_use_id": "t4", "content": a_body}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "a.py", "old_string": "alpha " * 8,
                           "new_string": "수정 " * 50}},
                {"type": "text", "text": "고쳤다"}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(_json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            rs = collect_record_stats(p)
            # a.py=편집+재방문 → 기여. 블록 분해: alpha 블록(편집 원문과 6단어
            # 조각 겹침)만 정독 200, beta 5블록은 훑기 1000.
            # b.py·c.py=비기여 — 마지막 기여 읽기 a(4번째) 이전 = 항해 중 SKIM.
            self.assertEqual(rs["contributed_docs"], 1)
            self.assertEqual(rs["deep_words"], 200)    # 재읽기 중복 제거 + 블록
            self.assertEqual(rs["skim_words"], 2300)   # a 나머지 1000 + b 400 + c 900
            # 닻: 200 + 2300×(탐색 0.00025/정독 0.005=0.05) = 200+115 = 315
            out = {"human": [{"primitive": "read", "count": 9999}]}
            req = {"requirements": [{"title": "수정", "requested_quantities": [],
                                     "acceptance_criteria": []}]}
            r = estimate_actions_from_requirements(self._Mock([out]), req,
                                                   record_stats=rs)
            bd = {b["primitive"]: b for b in r["breakdown"]}
            self.assertEqual(r["anchors"]["structured_read_words"], 315)
            self.assertEqual(bd["read"]["count"], 315)
        finally:
            os.unlink(p)

    def test_query_read_generalization(self):
        # §27: 파일이 아닌 조회형 읽기(지라 티켓 등 MCP 도구)도 같은 등급 분해.
        # 검색형 도구 = 탐색 신호, 착지 티켓 = 기여, 이후 티켓 = 헛읽기,
        # 실행형(Bash) 대량 출력 = 읽기 아님, 짧은 ack 결과 = 읽기 아님.
        import tempfile, os, json as _json
        from requirement_actions import collect_record_stats
        lines = [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "s1", "name": "mcp__jira__search_issues",
                 "input": {"jql": "project=PROJ"}},
                {"type": "tool_use", "id": "t1", "name": "mcp__jira__get_issue",
                 "input": {"issue": "PROJ-123"}},
                {"type": "tool_use", "id": "t2", "name": "mcp__jira__get_issue",
                 "input": {"issue": "PROJ-999"}},
                {"type": "tool_use", "id": "b1", "name": "Bash",
                 "input": {"command": "pytest"}},
                {"type": "tool_use", "id": "t3", "name": "mcp__jira__get_status",
                 "input": {"issue": "PROJ-777"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "s1", "content": "목록 " * 60},
                {"type": "tool_result", "tool_use_id": "t1", "content": "본문 " * 300},
                {"type": "tool_result", "tool_use_id": "t2", "content": "딴것 " * 100},
                {"type": "tool_result", "tool_use_id": "b1", "content": "로그 " * 500},
                {"type": "tool_result", "tool_use_id": "t3", "content": "ok"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "PROJ-123 티켓 내용 정리했다"}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(_json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            rs = collect_record_stats(p, detail=True)
            # PROJ-123 = 착지(검색 직후 첫 조회) + 답변에 키 언급 → 기여
            # PROJ-999 = 기여 확보 후에만 읽힘 → 헛읽기
            # Bash 500단어 로그 = 실행형 제외 / get_status "ok" = 50단어 미만 제외
            self.assertEqual(rs["contributed_docs"], 1)
            self.assertEqual(rs["waste_docs"], 1)
            self.assertEqual(rs["waste_words"], 100)
            # 기여 티켓도 인용 증거 없는 블록은 훑기 (본문 300 전부)
            self.assertEqual(rs["deep_words"], 0)
            self.assertEqual(rs["skim_words"], 300)
            self.assertTrue(any("PROJ-123" in f for f in rs["files"]["deep"]))
        finally:
            os.unlink(p)

    def test_navigation_structure_decomposition(self):
        # 등급 분류는 되지만 읽기 결과 본문이 기록에 없는 세션(실측 단어 0):
        # 건당 고정치 폴백은 폐지(§24) — 구조 닻 없이 실측 총량 상한만 적용
        import tempfile, os, json as _json
        from requirement_actions import (collect_record_stats,
                                         estimate_actions_from_requirements)
        lines = [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "b.py"}},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "c.py"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "코드 " * 5000}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "a.py", "new_string": "수정 " * 50}},
                {"type": "text", "text": "b.py 의 로직을 참고해 a.py 를 고쳤다"}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(_json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            rs = collect_record_stats(p)
            # a.py=편집됨, b.py=답변에 언급 → 기여 2 / c.py=마지막 기여 읽기
            # 이후에만 읽힘 → 헛읽기(WASTE)
            self.assertEqual(rs["contributed_docs"], 2)
            self.assertEqual(rs["scanned_docs"], 0)
            self.assertEqual(rs["waste_docs"], 1)
            self.assertEqual(rs["deep_words"], 0)   # 결과 본문 미기록 → 실측 0
            req = {"requirements": [{"title": "수정", "requested_quantities": [],
                                     "acceptance_criteria": []}]}
            out = {"human": [{"primitive": "read", "count": 9999},
                             {"primitive": "edit", "count": 50}]}
            r = estimate_actions_from_requirements(self._Mock([out]), req,
                                                   record_stats=rs)
            bd = {b["primitive"]: b for b in r["breakdown"]}
            # 구조 닻 없음(지어내지 않음) — 실측 총량(5000)이 상한으로만 작동
            self.assertNotIn("structured_read_words", r["anchors"])
            self.assertEqual(bd["read"]["count"], 5000)
        finally:
            os.unlink(p)

    def test_navigation_signals_search_stop_and_overlap(self):
        # 신호④ 탐색 종료 후 읽기, 신호⑤ 내용 겹침 — 편집·이름 언급 없이도 기여
        import tempfile, os, json as _json
        from requirement_actions import collect_record_stats
        lines = [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "x.md"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "무관한 내용 " * 100}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t2", "name": "Grep",
                 "input": {"pattern": "retry"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t3", "name": "Read",
                 "input": {"file_path": "y.md"}},
                {"type": "tool_use", "id": "t4", "name": "Read",
                 "input": {"file_path": "z.md"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t3",
                 "content": "설정값 PAYMENT_RETRY_LIMIT 는 7 이다"},
                {"type": "tool_result", "tool_use_id": "t4",
                 "content": "다른 내용 " * 50}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text",
                 "text": "결론: 재시도 한도는 PAYMENT_RETRY_LIMIT 값 7."}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(_json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            rs = collect_record_stats(p)
            # y.md = 탐색 착지(마지막 검색 직후 첫 읽기, 신호④) + 식별자
            # 겹침(신호⑤) → 기여. x.md = 착지 전 읽힘 → 훑기(SKIM).
            # z.md = 마지막 기여 읽기 이후에만 읽힘·무신호 → 헛읽기(WASTE).
            self.assertEqual(rs["contributed_docs"], 1)
            self.assertEqual(rs["scanned_docs"], 1)
            self.assertEqual(rs["waste_docs"], 1)
        finally:
            os.unlink(p)

    def test_internal_artifacts_excluded(self):
        # 세션 내부 부산물(.output, scratchpad, 스크린샷)은 등급 분류 제외
        import tempfile, os, json as _json
        from requirement_actions import collect_record_stats
        lines = [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "r1", "name": "Read",
                 "input": {"file_path": "C:\\proj\\real_doc.md"}},
                {"type": "tool_use", "id": "r2", "name": "Read",
                 "input": {"file_path": "C:\\Users\\x\\AppData\\Local\\Temp\\claude\\s1\\tasks\\abc.output"}},
                {"type": "tool_use", "id": "r3", "name": "Read",
                 "input": {"file_path": "C:\\Users\\x\\Temp\\claude\\s1\\scratchpad\\log.txt"}},
                {"type": "tool_use", "id": "r4", "name": "Read",
                 "input": {"file_path": "C:\\shots\\step1.png"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "real_doc.md 확인 완료"}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(_json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            rs = collect_record_stats(p)
            # real_doc.md 만 분류 대상(언급 → 기여), 나머지 3건은 internal
            self.assertEqual(rs["contributed_docs"], 1)
            self.assertEqual(rs["scanned_docs"], 0)
            self.assertEqual(rs["waste_docs"], 0)
            self.assertEqual(rs["internal_docs"], 3)
        finally:
            os.unlink(p)

    def test_navigation_multiturn_scoping(self):
        # 멀티턴: 신호④는 턴 단위, 분할 이어읽기는 재방문 아님,
        # 같은 구간 재읽기는 재방문, 서브에이전트 기록은 제외
        import tempfile, os, json as _json
        from requirement_actions import collect_record_stats
        lines = [
            # 턴1: 검색 후 A 읽음 → 신호④ 기여
            {"type": "user", "message": {"role": "user", "content": "찾아라"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "s1", "name": "Grep",
                 "input": {"pattern": "x"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "r1", "name": "Read",
                 "input": {"file_path": "A.md"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "턴1 끝"}]}},
            # 턴2: 검색 없음 — 턴1의 검색이 여기로 새면 안 됨
            {"type": "user", "message": {"role": "user", "content": "다음 일"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "r2", "name": "Read",
                 "input": {"file_path": "B.md", "offset": 0}},
                {"type": "tool_use", "id": "r3", "name": "Read",
                 "input": {"file_path": "B.md", "offset": 2000}},
                {"type": "tool_use", "id": "r4", "name": "Read",
                 "input": {"file_path": "D.md"}},
                {"type": "tool_use", "id": "r5", "name": "Read",
                 "input": {"file_path": "D.md"}}]}},
            # 서브에이전트 기록 — 집계 제외
            {"type": "assistant", "isSidechain": True,
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "r6", "name": "Read",
                  "input": {"file_path": "E.md"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "턴2 끝"}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(_json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            rs = collect_record_stats(p)
            # A=턴1 탐색 착지(④), D=같은 구간 2회(③) → 기여 2.
            # B=offset 다른 분할 이어읽기, D 기여 확보 전 → 훑기(SKIM).
            # E=서브에이전트 → 미집계.
            self.assertEqual(rs["contributed_docs"], 2)
            self.assertEqual(rs["scanned_docs"], 1)
            self.assertEqual(rs["waste_docs"], 0)
        finally:
            os.unlink(p)

    def test_no_rate_leak(self):
        from requirement_actions import build_prompt, build_prompt_single
        from agent_effort import load_rates
        prompt = build_prompt(self.REQ, load_rates())
        self.assertNotIn("min_per_unit", prompt)
        self.assertNotIn("0.005", prompt)
        single = build_prompt_single("세션 요약", load_rates())
        self.assertNotIn("min_per_unit", single)

    def test_single_call_mode(self):
        from requirement_actions import estimate_actions_single
        out = {"todos": [{"title": "보고서",
                          "quantities": [{"name": "분량", "value": 2000, "unit": "단어"}],
                          "acceptance_criteria": ["a", "b", "c"]}],
               "human": [{"primitive": "draft", "count": 500},
                         {"primitive": "verify", "count": 9}],
               "rationale": "t"}
        r = estimate_actions_single(self._Mock([out]), "세션 요약")
        bd = {b["primitive"]: b for b in r["breakdown"]}
        self.assertEqual(bd["draft"]["count"], 2000)   # 내부 할일 명시 분량 닻
        self.assertEqual(bd["verify"]["count"], 3)     # 완료조건 3개 닻
        self.assertEqual(r["todos"], ["보고서"])




if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--live" in sys.argv:
        sys.argv.remove("--live")
        unittest.main(exit=False, verbosity=1)
        print("\n--- live proxy test ---")
        _live()
    else:
        unittest.main(verbosity=1)
