# -*- coding: utf-8 -*-
"""measure_ratios 순수 함수 테스트 (git 호출 없음)."""
import unittest

from measure_ratios import (_resolve_rename, count_comment_blank,
                            is_generated, path_kind)


class TestPathKind(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(path_kind("src/a.py"), "code")
        self.assertEqual(path_kind("docs/README.md"), "doc")
        self.assertEqual(path_kind("conf/app.yaml"), "data")
        self.assertEqual(path_kind("bin/tool"), "other")

    def test_case_insensitive(self):
        self.assertEqual(path_kind("A.PY"), "code")


class TestGenerated(unittest.TestCase):
    def test_lock_and_vendor(self):
        for p in ("package-lock.json", "web/node_modules/x/a.js",
                  "dist/app.js", "a/__snapshots__/x.snap",
                  "static/app.min.js", "db/migrations/001.sql",
                  "go.sum", "src/x.pb.go"):
            self.assertTrue(is_generated(p), p)

    def test_normal_paths_not_generated(self):
        for p in ("src/app.js", "docs/build-guide.md", "lib/outbox.py",
                  "package.json"):
            self.assertFalse(is_generated(p), p)

    def test_windows_separator(self):
        self.assertTrue(is_generated(r"web\node_modules\x\a.js"))


class TestResolveRename(unittest.TestCase):
    def test_brace_form(self):
        self.assertEqual(_resolve_rename("src/{old => new}/a.py"),
                         "src/new/a.py")

    def test_plain_form(self):
        self.assertEqual(_resolve_rename("old.py => new.py"), "new.py")

    def test_untouched(self):
        self.assertEqual(_resolve_rename("src/a.py"), "src/a.py")


class TestCommentCounter(unittest.TestCase):
    def test_hash_style(self):
        text = "# c\n\nx = 1\n# c2\ny = 2\n"
        total, noncode = count_comment_blank(text, "hash")
        self.assertEqual((total, noncode), (5, 3))

    def test_python_docstring_block(self):
        text = '"""\ndoc\n"""\nx = 1\n'
        total, noncode = count_comment_blank(text, "hash")
        self.assertEqual((total, noncode), (4, 3))

    def test_slash_block(self):
        text = "/*\n * a\n */\nint x;\n// b\n"
        total, noncode = count_comment_blank(text, "slash")
        self.assertEqual((total, noncode), (5, 4))

    def test_dash_style(self):
        text = "-- c\nSELECT 1;\n"
        self.assertEqual(count_comment_blank(text, "dash"), (2, 1))

    def test_code_only(self):
        self.assertEqual(count_comment_blank("a\nb\nc\n", "hash"), (3, 0))


if __name__ == "__main__":
    unittest.main()
