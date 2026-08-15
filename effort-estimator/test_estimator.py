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

import engine
from estimator import (HumanEffortEstimator, DEFAULT_CATALOG_PATH,
                       validate_effort_input, validate_requirements_output)
from compat import CounterfactualEstimator

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


class MockLLM:
    """프롬프트 내용을 감지해 Prompt A/B/C 응답을 돌려준다. 큐 주입도 지원."""

    def __init__(self, queue=None):
        self.queue = list(queue) if queue else None
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        if self.queue is not None:
            return self.queue.pop(0)
        if "Planned Requirement Reconstruction Engine" in prompt:
            return copy.deepcopy(REQ_OUT)
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
        self.assertEqual(len(llm.calls), 2)
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

    def test_fail_after_two_invalid(self):
        llm = MockLLM(queue=[{"garbage": True}, {"garbage": True}])
        est = HumanEffortEstimator(llm, trials=200, seed=42)
        with self.assertRaises(ValueError):
            est.estimate(SPEC)

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

class TestCompat(unittest.TestCase):
    def test_estimate_task_contract(self):
        ce = CounterfactualEstimator(llm=MockLLM())
        r = ce.estimate_task("월간 경쟁사 동향", "정기 보고", "애널리스트",
                             ["research-web"], "경쟁사 5곳 조사 후 보고서")
        self.assertIsNone(r["error"])
        self.assertGreater(r["human_min"], 0)
        self.assertGreaterEqual(r["human_p80_min"], r["human_min"])
        self.assertIsNone(r["agent_min"])
        self.assertIn("research.source_search", r["human_breakdown"])

    def test_error_path(self):
        class Boom:
            def complete_json(self, p, m):
                raise RuntimeError("down")
        r = CounterfactualEstimator(llm=Boom()).estimate_task("t", "c", "r", [], "d")
        self.assertIsNotNone(r["error"])
        self.assertIsNone(r["human_min"])


def _live():
    from onprem_llm_sim import OnpremLLM
    from estimator import format_report
    est = HumanEffortEstimator(OnpremLLM())
    result = est.estimate(SPEC)
    print(format_report(result))


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
