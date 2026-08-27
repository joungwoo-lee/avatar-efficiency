# -*- coding: utf-8 -*-
"""diff-effort 단위 테스트."""
import unittest

from diff_effort import BANDS, diff_effort, diff_effort_band, rates


class TestRates(unittest.TestCase):
    def test_mid_band_values(self):
        r = rates("mid")
        self.assertAlmostEqual(r["new_min_per_line"], 2.264, places=3)
        self.assertAlmostEqual(r["delete_min_per_line"], 1.313, places=3)

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


class TestDiffEffort(unittest.TestCase):
    def test_pure_add(self):
        r = diff_effort(100, 0)
        self.assertAlmostEqual(r["minutes"], 226.4, places=1)

    def test_replacement_pairs_removed(self):
        # +320/-180 → 순삭제 0, 교체 쌍 180
        r = diff_effort(320, 180)
        self.assertEqual(r["breakdown"]["delete"]["lines"], 0)
        self.assertEqual(r["replaced_pairs"], 180)
        self.assertAlmostEqual(r["minutes"], 724.5, places=1)

    def test_net_deletion_charged(self):
        # +20/-400 → 순삭제 380
        r = diff_effort(20, 400)
        self.assertEqual(r["breakdown"]["delete"]["lines"], 380)
        self.assertAlmostEqual(r["minutes"], 544.3, places=1)

    def test_whole_file_scrap(self):
        r = diff_effort(0, 1200, file_deleted_lines=1200)
        self.assertEqual(r["breakdown"]["delete"]["lines"], 0)
        self.assertAlmostEqual(r["minutes"], 30.0, places=1)

    def test_scrap_excluded_from_pair_removal(self):
        # 파일 통째 삭제분은 추가와 쌍을 이루지 않는다
        r = diff_effort(50, 100, file_deleted_lines=100)
        self.assertEqual(r["breakdown"]["scrap"]["lines"], 100)
        self.assertEqual(r["breakdown"]["delete"]["lines"], 0)

    def test_zero(self):
        self.assertEqual(diff_effort(0, 0)["minutes"], 0.0)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            diff_effort(-1, 0)

    def test_scrap_exceeds_deleted(self):
        with self.assertRaises(ValueError):
            diff_effort(0, 10, file_deleted_lines=11)


class TestBand(unittest.TestCase):
    def test_band_range(self):
        b = diff_effort_band(100, 0)
        lo, hi = b["range_minutes"]
        self.assertLess(lo, b["mid_minutes"])
        self.assertGreater(hi, b["mid_minutes"])
        self.assertEqual(set(b["by_band"]), set(BANDS))


if __name__ == "__main__":
    unittest.main()
