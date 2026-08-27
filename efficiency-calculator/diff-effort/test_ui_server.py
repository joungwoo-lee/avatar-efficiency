# -*- coding: utf-8 -*-
"""ui_server 단위 테스트 — 실제 HTTP 로 띄워서 두드린다.

UI 는 계산을 하지 않는다. 그래서 여기서 확인하는 건 두 가지다.
    (1) 탐색·저장·에러 처리가 경로를 제대로 다루는가
    (2) UI 가 낸 값이 csv_report.py 가 낸 값과 같은가 (CLI 와 안 갈리는가)
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import csv_report as CR
import ui_server as UI

HEADER = ("employee_id,total_cost,lines_added,lines_removed,"
          "cli_active_sec,user_active_sec\n")
SAMPLE = HEADER + (
    "oseok.kim,10638.70,179887,25046,842715,37005\n"
    "jane.doe,1200.50,20000,31000,90000,12000\n"
)


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


class ServerCase(unittest.TestCase):
    """서버를 한 번 띄워 전 테스트가 같이 쓴다."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), UI.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.th = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.th.start()
        cls.tmp = tempfile.mkdtemp(prefix="diff-effort-ui-")
        cls.csv = _write(os.path.join(cls.tmp, "usage.csv"), SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def get(self, endpoint, **q):
        if q:
            endpoint += "?" + urlencode(q)
        with urlopen(self.url(endpoint)) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, path, body):
        req = Request(self.url(path), method="POST",
                      data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
        with urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))

    def post_err(self, path, body):
        """오류를 기대한다 -> (status, message)."""
        req = Request(self.url(path), method="POST",
                      data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req):
                self.fail("오류가 나야 한다: %s" % path)
        except HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))["error"]


class TestStatic(ServerCase):

    def test_index_is_served(self):
        with urlopen(self.url("/")) as r:
            body = r.read().decode("utf-8")
        self.assertEqual(r.status, 200)
        self.assertIn("diff-effort", body)

    def test_meta_lists_required_columns(self):
        m = self.get("/api/meta")
        self.assertEqual(tuple(m["required"]), CR.REQUIRED)
        self.assertIn(m["default_band"], m["bands"])

    def test_unknown_path_is_404(self):
        try:
            with urlopen(self.url("/nope")):
                self.fail("404 여야 한다")
        except HTTPError as e:
            self.assertEqual(e.code, 404)


class TestBrowse(ServerCase):

    def test_browse_lists_csv_files(self):
        d = self.get("/api/browse", path=self.tmp, kind="csv")
        self.assertEqual(d["path"], os.path.abspath(self.tmp))
        self.assertIn("usage.csv", [f["name"] for f in d["files"]])

    def test_dir_kind_hides_files(self):
        d = self.get("/api/browse", path=self.tmp, kind="dir")
        self.assertEqual(d["files"], [])

    def test_empty_path_gives_roots(self):
        d = self.get("/api/browse", path="")
        self.assertTrue(d["dirs"])
        self.assertIsNone(d["up"])

    def test_missing_dir_is_error(self):
        try:
            with urlopen(self.url("/api/browse?path=" +
                                  os.path.join(self.tmp, "nope-xyz"))):
                self.fail("오류여야 한다")
        except HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_this_repo_is_flagged(self):
        """이 저장소의 부모를 훑으면 저장소가 git 으로 찍혀야 한다."""
        here = UI._HERE
        root = here
        while root and not UI.is_repo(root):
            up = os.path.dirname(root)
            if up == root:
                self.skipTest("git 저장소 밖에서 돌고 있다")
            root = up
        d = self.get("/api/browse", path=os.path.dirname(root), kind="dir")
        hit = [x for x in d["dirs"] if x["path"] == root]
        self.assertTrue(hit and hit[0]["repo"])


class TestReport(ServerCase):

    def test_matches_csv_report(self):
        """UI 결과 == csv_report 결과. 갈리면 안 된다."""
        res = self.post("/api/report", {"csv_path": self.csv,
                                        "no_config": True})
        rows = CR.analyze_csv(self.csv)
        CR.sort_rows(rows, "effort_min", False)
        self.assertEqual([r["employee_id"] for r in res["rows"]],
                         [r["employee_id"] for r in rows])
        self.assertAlmostEqual(res["rows"][0]["effort_min"],
                               rows[0]["effort_min"], places=6)
        self.assertEqual(res["total"]["employee_id"],
                         CR.totals(rows)["employee_id"])
        self.assertTrue(res["uncorrected"])
        self.assertIn("[가정]", res["assumptions"])

    def test_sort_and_band_are_applied(self):
        asc = self.post("/api/report", {"csv_path": self.csv, "asc": True,
                                        "sort": "employee_id",
                                        "no_config": True})
        self.assertEqual([r["employee_id"] for r in asc["rows"]],
                         ["jane.doe", "oseok.kim"])
        fast = self.post("/api/report", {"csv_path": self.csv,
                                         "band": "fast", "no_config": True})
        mid = self.post("/api/report", {"csv_path": self.csv,
                                        "no_config": True})
        self.assertLess(fast["total"]["effort_min"],
                        mid["total"]["effort_min"])

    def test_inline_ratios_turn_off_the_warning(self):
        res = self.post("/api/report", {"csv_path": self.csv,
                                        "no_config": True,
                                        "mix": "0.5,0.4,0.1",
                                        "comment_ratio": 0.24})
        self.assertFalse(res["uncorrected"])
        plain = self.post("/api/report", {"csv_path": self.csv,
                                          "no_config": True})
        self.assertLess(res["total"]["effort_min"],
                        plain["total"]["effort_min"])

    def test_missing_columns_are_named(self):
        bad = _write(os.path.join(self.tmp, "bad.csv"),
                     "employee_id,lines_added\na,1\n")
        code, err = self.post_err("/api/report", {"csv_path": bad})
        self.assertEqual(code, 400)
        self.assertIn("lines_removed", err)

    def test_missing_file_is_error(self):
        code, err = self.post_err("/api/report", {
            "csv_path": os.path.join(self.tmp, "nope.csv")})
        self.assertEqual(code, 400)
        self.assertIn("없다", err)


class TestSave(ServerCase):

    def test_save_writes_report_csv(self):
        self.post("/api/report", {"csv_path": self.csv, "no_config": True})
        out = os.path.join(self.tmp, "report")          # 확장자 없이 줘도
        r = self.post("/api/save", {"out": out})
        self.assertTrue(r["saved_to"].endswith("report.csv"))
        with open(r["saved_to"], encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("employee_id", text.splitlines()[0])
        self.assertIn("TOTAL(n=2)", text)

    def test_save_to_missing_folder_is_error(self):
        self.post("/api/report", {"csv_path": self.csv, "no_config": True})
        code, err = self.post_err("/api/save", {
            "out": os.path.join(self.tmp, "nope-dir", "r.csv")})
        self.assertEqual(code, 400)
        self.assertIn("폴더가 없다", err)

    def test_save_without_path_is_error(self):
        self.post("/api/report", {"csv_path": self.csv, "no_config": True})
        code, _ = self.post_err("/api/save", {"out": "  "})
        self.assertEqual(code, 400)


class TestMeasure(ServerCase):

    def _git_repo(self):
        if not shutil.which("git"):
            self.skipTest("git 이 없다")
        repo = tempfile.mkdtemp(prefix="diff-effort-repo-")
        run = lambda *a: subprocess.run(["git", "-C", repo] + list(a),
                                        capture_output=True, check=True)
        run("init", "-q")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        _write(os.path.join(repo, "a.py"), "# c\n\nx = 1\ny = 2\n")
        _write(os.path.join(repo, "b.md"), "# doc\n\ntext\n")
        run("add", "-A")
        run("commit", "-q", "-m", "init")
        return repo

    def test_measure_writes_config_and_reports(self):
        repo = self._git_repo()
        out = os.path.join(self.tmp, "ratios-test.json")
        try:
            r = self.post("/api/measure", {"repos": [repo], "out": out,
                                           "no_cloc": True})
            self.assertEqual(r["saved_to"], out)
            cfg = r["config"]
            self.assertAlmostEqual(sum(cfg["mix"].values()), 1.0, places=3)
            self.assertGreater(cfg["mix"]["code"], 0)
            self.assertGreater(cfg["comment_ratio"], 0)
            self.assertEqual(cfg["measured"]["repos"], [os.path.abspath(repo)])
            self.assertIn("[구성비]", r["text"])
            # 저장된 파일을 리포트가 그대로 집어 쓴다
            got = self.get("/api/ratios", path=out)
            self.assertEqual(got["config"]["mix"], cfg["mix"])
            res = self.post("/api/report", {"csv_path": self.csv,
                                            "config": out})
            self.assertFalse(res["uncorrected"])
            self.assertEqual(res["config_path"], out)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_non_repo_is_rejected(self):
        code, err = self.post_err("/api/measure", {"repos": [self.tmp]})
        self.assertEqual(code, 400)
        self.assertIn("git 저장소가 아니다", err)

    def test_no_repo_is_rejected(self):
        code, err = self.post_err("/api/measure", {"repos": []})
        self.assertEqual(code, 400)
        self.assertIn("하나 이상", err)


class TestSuggestOut(unittest.TestCase):

    def test_suggest_sits_next_to_input(self):
        out = UI.suggest_out(os.path.join("C:" + os.sep, "x", "usage.csv"))
        self.assertTrue(out.endswith("usage_report.csv"))

    def test_suggest_without_input(self):
        self.assertTrue(UI.suggest_out("").endswith("report.csv"))


if __name__ == "__main__":
    unittest.main()
