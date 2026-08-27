# -*- coding: utf-8 -*-
"""csv_report 단위 테스트 (임시 CSV 생성)."""
import io
import os
import tempfile
import unittest

from csv_report import analyze_csv, analyze_row, sort_rows, totals

HEADER = ("employee_id,total_cost,lines_added,lines_removed,"
          "cli_active_sec,user_active_sec\n")

SAMPLE = HEADER + (
    "oseok.kim,10638.70,179887,25046,842715,37005\n"
    "jane.doe,1200.50,20000,31000,90000,12000\n"
    "zero.user,0,0,0,0,0\n"
)


def _tmp_csv(text):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


class TestAnalyzeRow(unittest.TestCase):
    def test_metrics(self):
        row = {"employee_id": "a", "lines_added": "179887",
               "lines_removed": "25046", "cli_active_sec": "842715",
               "user_active_sec": "37005", "total_cost": "10638.70"}
        r = analyze_row(row)
        self.assertAlmostEqual(r["effort_min"], 407291.3, places=1)
        # x_user = 407291.3 / (37005/60)
        self.assertAlmostEqual(r["x_user"], 407291.3 / (37005 / 60.0), places=3)
        self.assertAlmostEqual(r["x_total"],
                               407291.3 / ((842715 + 37005) / 60.0), places=3)
        self.assertAlmostEqual(r["min_per_usd"], 407291.3 / 10638.70, places=3)

    def test_zero_denominators_are_none(self):
        row = {"employee_id": "z", "lines_added": "0", "lines_removed": "0",
               "cli_active_sec": "0", "user_active_sec": "0",
               "total_cost": "0"}
        r = analyze_row(row)
        self.assertIsNone(r["x_total"])
        self.assertIsNone(r["x_user"])
        self.assertIsNone(r["min_per_usd"])

    def test_dirty_cells(self):
        row = {"employee_id": " a ", "lines_added": '"1,000"',
               "lines_removed": "", "cli_active_sec": "60",
               "user_active_sec": "60", "total_cost": "abc"}
        r = analyze_row(row)
        self.assertEqual(r["employee_id"], "a")
        self.assertEqual(r["lines_added"], 1000)
        self.assertEqual(r["lines_removed"], 0)
        self.assertIsNone(r["min_per_usd"])  # total_cost 파싱 실패 -> 0


class TestAnalyzeCsv(unittest.TestCase):
    def setUp(self):
        self.path = _tmp_csv(SAMPLE)

    def tearDown(self):
        os.unlink(self.path)

    def test_row_count_and_order(self):
        rows = analyze_csv(self.path)
        self.assertEqual([r["employee_id"] for r in rows],
                         ["oseok.kim", "jane.doe", "zero.user"])

    def test_missing_column(self):
        bad = _tmp_csv("employee_id,lines_added\na,1\n")
        try:
            with self.assertRaises(ValueError):
                analyze_csv(bad)
        finally:
            os.unlink(bad)

    def test_blank_id_skipped(self):
        p = _tmp_csv(SAMPLE + ",0,0,0,0,0\n")
        try:
            self.assertEqual(len(analyze_csv(p)), 3)
        finally:
            os.unlink(p)

    def test_band_changes_result(self):
        mid = analyze_csv(self.path, "mid")[0]["effort_min"]
        slow = analyze_csv(self.path, "slow")[0]["effort_min"]
        self.assertGreater(slow, mid)


class TestTotalsAndSort(unittest.TestCase):
    def setUp(self):
        self.path = _tmp_csv(SAMPLE)
        self.rows = analyze_csv(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_totals_ratio_is_sum_over_sum(self):
        t = totals(self.rows)
        s_min = sum(r["effort_min"] for r in self.rows)
        s_user = sum(r["user_active_sec"] for r in self.rows)
        self.assertAlmostEqual(t["x_user"], s_min / (s_user / 60.0), places=3)

    def test_sort_puts_none_last_both_directions(self):
        desc = sort_rows(list(self.rows), "x_user", asc=False)
        self.assertEqual(desc[-1]["employee_id"], "zero.user")
        asc = sort_rows(list(self.rows), "x_user", asc=True)
        self.assertEqual(asc[-1]["employee_id"], "zero.user")

    def test_sort_by_id(self):
        r = sort_rows(list(self.rows), "employee_id", asc=True)
        self.assertEqual(r[0]["employee_id"], "jane.doe")


if __name__ == "__main__":
    unittest.main()
