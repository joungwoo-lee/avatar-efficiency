# -*- coding: utf-8 -*-
"""OBHE 단위 테스트: python test_obhe.py"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_builder
import rate_engine
from sim_llm import SimLLM


def _card():
    return rate_engine.load_rate_card()


class TestTimeEquation(unittest.TestCase):
    def test_base_rate(self):
        # verify_claim: claim당 3분 (§8 예시)
        row = rate_engine.price_row({"action": "verify_claim", "quantity": 10}, _card())
        self.assertAlmostEqual(row["p50_min"], 30.0)
        self.assertAlmostEqual(row["p80_min"], 42.0)  # p80_factor_default 1.4

    def test_driver_add(self):
        # 다중출처 driver +4분 → claim당 7분
        row = rate_engine.price_row(
            {"action": "verify_claim", "quantity": 10, "drivers": ["multi_source_needed"]}, _card())
        self.assertAlmostEqual(row["p50_min"], 70.0)

    def test_unknown_action(self):
        with self.assertRaises(rate_engine.RateCardError):
            rate_engine.price_row({"action": "nonexistent", "quantity": 1}, _card())

    def test_unknown_driver(self):
        with self.assertRaises(rate_engine.RateCardError):
            rate_engine.price_row(
                {"action": "verify_claim", "quantity": 1, "drivers": ["bogus"]}, _card())


class TestLedgerPricing(unittest.TestCase):
    def test_rework_applied_to_scope_only(self):
        card = _card()
        rows = [
            {"action": "write_section", "quantity": 3},   # H5 → rework 대상
            {"action": "verify_claim", "quantity": 10},   # H7 → 제외
        ]
        priced = rate_engine.price_ledger(rows, card)
        ratio = card["expected_rework"]["ratio"]
        self.assertAlmostEqual(priced["rework_p50_min"], ratio * 60.0)  # 3x20분만 대상
        self.assertAlmostEqual(priced["total_p50_min"], 90.0 + ratio * 60.0)

    def test_missing_verification_warns(self):
        priced = rate_engine.price_ledger([{"action": "write_section", "quantity": 1}], _card())
        self.assertTrue(any("H7" in w for w in priced["warnings"]))

    def test_verification_present_no_warning(self):
        priced = rate_engine.price_ledger(
            [{"action": "write_section", "quantity": 1},
             {"action": "review_final", "quantity": 1}], _card())
        self.assertEqual(priced["warnings"], [])


class TestReport(unittest.TestCase):
    def test_sample_ledger_metrics(self):
        data = json.loads(
            (Path(__file__).parent / "examples" / "sample_ledger.json").read_text(encoding="utf-8"))
        report = rate_engine.build_report(
            data["reference_ledger"], _card(),
            replication_ledger=data["replication_ledger"], ai_actual_hours=4.0)
        self.assertGreater(report["rhe_p80_hours"], report["rhe_p50_hours"])
        self.assertGreater(report["hre_p50_hours"], report["rhe_p50_hours"])
        self.assertGreater(report["output_inflation"], 1.0)
        # 겉보기 효율(HRE/AI) > 현실화 효율(RHE/AI) — §19 과장 구조
        self.assertGreater(report["naive_efficiency"], report["realized_efficiency"])

    def test_confidence_worst_of_three(self):
        report = rate_engine.build_report(
            [{"action": "review_final", "quantity": 1}], _card(),
            outcome_confidence="A", path_confidence="B")
        # rate card seed confidence C → 전체 C
        self.assertEqual(report["confidence"], "C")


class TestRestorePaths(unittest.TestCase):
    def test_end_to_end_with_sim(self):
        artifact = "# 보고서\n\n## 분석\n시장 성장률 12% 전망.\n\n| a | b |\n| 1 | 2 |\n"
        restored = ledger_builder.restore_paths(artifact, SimLLM(), _card())
        self.assertTrue(restored["reference_ledger"])
        self.assertTrue(restored["replication_ledger"])
        # 프롬프트에 요율 필드가 노출되지 않아야 한다 (§11)
        prompt = ledger_builder.build_prompt(artifact, _card())
        self.assertNotIn("base_min", prompt)
        self.assertNotIn("add_min", prompt)
        self.assertNotIn("분/단위", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
