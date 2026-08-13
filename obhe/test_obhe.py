# -*- coding: utf-8 -*-
"""OBHE 단위·통합 테스트: python test_obhe.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate
import gitstate
import rate_engine
import trajectory
import workload
from sim_llm import SimLLM


def _rates():
    return rate_engine.load_rates()


def _jsonl_line(tool, tool_input):
    return json.dumps({
        "type": "assistant", "sessionId": "s-test", "cwd": "IGNORED",
        "timestamp": "2026-08-13T10:00:00Z",
        "message": {"content": [{"type": "tool_use", "name": tool, "input": tool_input}]},
    })


class TestTrajectory(unittest.TestCase):
    def test_direct_and_bash_paths(self):
        lines = [
            json.dumps({"type": "user", "sessionId": "s-test",
                        "message": {"role": "user", "content": "auth 버그 고쳐줘"}}),
            _jsonl_line("Edit", {"file_path": "src/auth.ts", "old_string": "a", "new_string": "b"}),
            _jsonl_line("Write", {"file_path": "src/token.ts", "content": "x"}),
            _jsonl_line("Bash", {"command": "python gen.py > out/report.txt; git add -A"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text("\n".join(lines), encoding="utf-8")
            sess = trajectory.parse_trajectory(f)
        self.assertEqual(sess["session_id"], "s-test")
        self.assertEqual(sess["direct_paths"], {"src/auth.ts", "src/token.ts"})
        self.assertIn("out/report.txt", sess["bash_candidate_paths"])
        self.assertEqual(sess["task_requests"], ["auth 버그 고쳐줘"])
        self.assertTrue(sess["git_commands"])

    def test_bash_candidates_filter_devnull(self):
        self.assertEqual(trajectory.bash_candidate_paths("ls > /dev/null 2>&1"), set())


class TestClassify(unittest.TestCase):
    def test_attribution_and_transient(self):
        changed = {"src/auth.ts": "M", "src/new.ts": "A", "out/report.txt": "A"}
        artifacts, transient, _ = gitstate.classify(
            {"src/auth.ts", "src/proto.ts"}, {"out/report.txt"}, changed, repo=".")
        by = {a["path"]: a for a in artifacts}
        self.assertEqual(by["src/auth.ts"]["attribution"], "DIRECT_NET")
        self.assertEqual(by["out/report.txt"]["attribution"], "BASH_NET")
        self.assertEqual(by["src/new.ts"]["attribution"], "GIT_NET")
        self.assertEqual(transient, ["src/proto.ts"])  # 건드렸지만 최종 diff에 없음


class TestRateEngine(unittest.TestCase):
    def test_price_and_complexity(self):
        rows = [{"action": "verify", "workload_unit": "assertion", "workload": 10,
                 "complexity": "high", "evidence": "", "shared": False,
                 "action_id": "A1", "outcome_id": "O1"}]
        priced = rate_engine.price_ledger(rows, _rates())
        # assertion p50 2분 x 10 x high 1.5 = 30분
        self.assertAlmostEqual(priced["rows"][0]["p50_min"], 30.0)
        self.assertAlmostEqual(priced["total_p50_min"], 30.0 * 1.12)  # rework 12%

    def test_missing_verify_warns(self):
        rows = [{"action": "construct", "workload_unit": "function_point", "workload": 1,
                 "complexity": "normal", "evidence": "", "shared": False,
                 "action_id": "A1", "outcome_id": "O1"}]
        self.assertTrue(rate_engine.price_ledger(rows, _rates())["warnings"])

    def test_unrecoverable_not_approved(self):
        man = {"job_id": "j", "recovery": "PARTIAL"}
        report = rate_engine.build_report(man, {
            "action_ledger": [], "completed_outcomes": [],
            "excluded_outputs": [], "measurement_required": []}, _rates())
        self.assertFalse(report["auto_approved"])


class TestWorkloadClean(unittest.TestCase):
    def test_invalid_rows_demoted(self):
        rows = [
            {"action": "construct", "workload_unit": "function_point", "workload": 2},
            {"action": "hallucinated", "workload_unit": "banana", "workload": 5},
        ]
        valid, demoted = workload._clean_ledger(rows, _rates())
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(demoted), 1)

    def test_prompt_hides_rates(self):
        man = {"job_id": "j", "task_requests": [], "artifacts": [],
               "excluded_transient_paths": [], "unresolved": [],
               "base_state": "a", "end_state": "b", "recovery": "EXACT",
               "recovery_note": "", "sessions": [], "repository": "."}
        prompt = workload.build_prompt(man, _rates())
        self.assertNotIn("p50_min", prompt)
        self.assertNotIn("p80_min", prompt)


class TestEndToEnd(unittest.TestCase):
    def test_git_repo_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)

            def git(*a):
                subprocess.run(["git", "-C", str(repo), *a], check=True,
                               capture_output=True, text=True)

            git("init", "-q")
            git("config", "user.email", "t@t")
            git("config", "user.name", "t")
            (repo / "src").mkdir()
            (repo / "src" / "auth.py").write_text("def login():\n    pass\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-qm", "base")
            base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            # 작업: auth 수정 + 테스트 신규 + 버렸다 지운 프로토타입(최종에 없음)
            (repo / "src" / "auth.py").write_text(
                "def login():\n    return True\n\ndef refresh():\n    return 1\n", encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_auth.py").write_text(
                "def test_login():\n    assert True\n", encoding="utf-8")

            traj = repo / "t.jsonl"
            traj.write_text("\n".join([
                json.dumps({"type": "user", "sessionId": "s1",
                            "message": {"role": "user", "content": "로그인 고치고 테스트 추가"}}),
                _jsonl_line("Edit", {"file_path": str(repo / "src" / "auth.py")}),
                _jsonl_line("Write", {"file_path": str(repo / "tests" / "test_auth.py")}),
                _jsonl_line("Write", {"file_path": str(repo / "src" / "proto.py")}),  # transient
            ]), encoding="utf-8")

            man = estimate.build_local_manifest([str(traj)], str(repo), base, None)
            self.assertEqual(man["recovery"], "HIGH_CONFIDENCE")
            paths = {a["path"]: a for a in man["artifacts"]}
            self.assertIn("src/auth.py", paths)
            self.assertIn("tests/test_auth.py", paths)
            self.assertEqual(paths["src/auth.py"]["attribution"], "DIRECT_NET")
            self.assertIn("src/proto.py", man["excluded_transient_paths"])

            rates = _rates()
            est = workload.estimate_workload(man, SimLLM(), rates)
            report = rate_engine.build_report(man, est, rates, ai_actual_hours=0.5)
            self.assertGreater(report["rhe_p50_hours"], 0)
            self.assertGreater(report["rhe_p80_hours"], report["rhe_p50_hours"])
            self.assertTrue(report["auto_approved"])

    def test_no_base_is_unrecoverable(self):
        with tempfile.TemporaryDirectory() as d:
            traj = Path(d) / "t.jsonl"
            traj.write_text(json.dumps({"type": "user", "sessionId": "s1",
                                        "message": {"role": "user", "content": "x"}}),
                            encoding="utf-8")
            man = estimate.build_local_manifest([str(traj)], d, None, None)
            self.assertEqual(man["recovery"], "UNRECOVERABLE")
            self.assertEqual(man["artifacts"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
