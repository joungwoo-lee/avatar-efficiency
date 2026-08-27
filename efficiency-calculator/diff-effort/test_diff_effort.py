# -*- coding: utf-8 -*-
"""diff-effort 단위 테스트."""
import unittest

from diff_effort import (BANDS, diff_effort, diff_effort_band,
                         effective_ratio, mix_factor, rates)


class TestRates(unittest.TestCase):
    def test_mid_band_values(self):
        r = rates("mid")
        self.assertAlmostEqual(r["new_min_per_line"], 2.264, places=3)
        self.assertAlmostEqual(r["delete_min_per_line"], 0.300, places=3)

    def test_delete_rate_is_band_independent(self):
        # 삭제는 인스펙션 속도 고정 앵커라 밴드를 따라가지 않는다
        vals = {rates(b)["delete_min_per_line"] for b in BANDS}
        self.assertEqual(len(vals), 1)

    def test_band_order(self):
        # 느릴수록 줄당 분이 커야 한다
        f = rates("fast")["new_min_per_line"]
        m = rates("mid")["new_min_per_line"]
        s = rates("slow")["new_min_per_line"]
        self.assertLess(f, m)
        self.assertLess(m, s)

    def test_bad_band(self):
        with self.assertRaises(ValueError):
            rates("nope")


class TestMixFactor(unittest.TestCase):
    def test_all_code_is_one(self):
        self.assertAlmostEqual(mix_factor(1, 0, 0), 1.0)

    def test_measured_composition(self):
        # 0.44 + 0.315x0.625 + 0.244x0.125, 정규화 후
        self.assertAlmostEqual(mix_factor(0.44, 0.315, 0.244), 0.6680,
                               places=4)

    def test_normalizes(self):
        self.assertAlmostEqual(mix_factor(44, 31.5, 24.4),
                               mix_factor(0.44, 0.315, 0.244), places=6)

    def test_data_only_is_cheapest(self):
        self.assertAlmostEqual(mix_factor(0, 0, 1), 0.125)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            mix_factor(0, 0, 0)
        with self.assertRaises(ValueError):
            mix_factor(-1, 1, 0)


class TestEffectiveRatio(unittest.TestCase):
    def test_default_is_one(self):
        self.assertAlmostEqual(effective_ratio(), 1.0)

    def test_multiplies_axes(self):
        self.assertAlmostEqual(effective_ratio(0.25, 0.10), 0.675)

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            effective_ratio(1.0, 0.0)
        with self.assertRaises(ValueError):
            effective_ratio(-0.1, 0.0)


class TestDiffEffort(unittest.TestCase):
    def test_pure_add(self):
        r = diff_effort(100, 0)
        self.assertAlmostEqual(r["minutes"], 226.4, places=1)

    def test_replacement_pairs_removed(self):
        # +320/-180 → 순삭제 0, 교체 쌍 180
        r = diff_effort(320, 180)
        self.assertEqual(r["breakdown"]["delete"]["lines"], 0)
        self.assertAlmostEqual(r["replaced_pairs"], 180, places=1)
        self.assertAlmostEqual(r["minutes"], 724.5, places=1)

    def test_net_deletion_charged(self):
        # +20/-400 → 순삭제 380 x 0.30
        r = diff_effort(20, 400)
        self.assertAlmostEqual(r["breakdown"]["delete"]["lines"], 380,
                               places=1)
        self.assertAlmostEqual(r["minutes"], 45.3 + 114.0, places=1)

    def test_mix_scales_both_terms(self):
        base = diff_effort(1000, 2000)["minutes"]
        mixed = diff_effort(1000, 2000, mix=0.5)["minutes"]
        self.assertAlmostEqual(mixed, base * 0.5, places=1)

    def test_eff_ratio_scales_lines(self):
        # 유효 라인 비율은 추가·삭제 양쪽에 걸린다
        r = diff_effort(1000, 0, eff_ratio=0.5)
        self.assertAlmostEqual(r["breakdown"]["write"]["lines"], 500,
                               places=1)
        self.assertAlmostEqual(r["minutes"],
                               diff_effort(500, 0)["minutes"], places=1)

    def test_zero(self):
        self.assertEqual(diff_effort(0, 0)["minutes"], 0.0)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            diff_effort(-1, 0)

    def test_bad_factors_rejected(self):
        with self.assertRaises(ValueError):
            diff_effort(1, 1, mix=0)
        with self.assertRaises(ValueError):
            diff_effort(1, 1, eff_ratio=0)
        with self.assertRaises(ValueError):
            diff_effort(1, 1, eff_ratio=1.5)


class TestBand(unittest.TestCase):
    def test_band_range(self):
        b = diff_effort_band(100, 0)
        lo, hi = b["range_minutes"]
        self.assertLess(lo, b["mid_minutes"])
        self.assertGreater(hi, b["mid_minutes"])
        self.assertEqual(set(b["by_band"]), set(BANDS))

    def test_band_passes_factors(self):
        b = diff_effort_band(1000, 0, mix=0.5, eff_ratio=0.5)
        self.assertAlmostEqual(b["mid_minutes"],
                               diff_effort(1000, 0)["minutes"] * 0.25,
                               places=1)


if __name__ == "__main__":
    unittest.main()
