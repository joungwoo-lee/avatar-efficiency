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

    def test_powershell_tool_and_cmdlets(self):
        # Windows 세션은 PowerShell 툴 사용 — 실측 trajectory에서 확인된 형식
        lines = [_jsonl_line("PowerShell", {"command":
                 'Get-Content a.txt | Out-File -FilePath out\\report.txt; '
                 'Set-Content config.json "x"; git push'})]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text("\n".join(lines), encoding="utf-8")
            sess = trajectory.parse_trajectory(f)
        self.assertIn("out\\report.txt", sess["bash_candidate_paths"])
        self.assertIn("config.json", sess["bash_candidate_paths"])
        self.assertEqual(len(sess["git_commands"]), 1)

    def test_powershell_nul_filtered(self):
        self.assertNotIn("nul", trajectory.bash_candidate_paths("cmd > nul"))


class TestAnswerArtifact(unittest.TestCase):
    """리뷰·답변 세션 (§5.4): 파일 산출물 0건이면 최종 답변이 산출물."""

    def _review_traj(self, d, with_edit=False):
        target = Path(d) / "auth.py"
        target.write_text("def f():\n    pass\n" * 10, encoding="utf-8")
        recs = [
            json.dumps({"type": "user", "sessionId": "s1",
                        "message": {"role": "user", "content": "auth.py 코드 리뷰해줘"}}),
            json.dumps({"type": "assistant", "sessionId": "s1", "cwd": d,
                        "timestamp": "2026-08-14T10:00:00Z",
                        "message": {"content": [{"type": "tool_use", "name": "Read",
                                                 "input": {"file_path": str(target)}}]}}),
            json.dumps({"type": "assistant", "sessionId": "s1", "cwd": d,
                        "timestamp": "2026-08-14T10:01:00Z",
                        "message": {"content": [{"type": "tool_use", "name": "Grep",
                                                 "input": {"pattern": "def "}}]}}),
        ]
        if with_edit:
            recs.append(json.dumps({
                "type": "assistant", "sessionId": "s1", "cwd": d,
                "timestamp": "2026-08-14T10:02:00Z",
                "message": {"content": [{"type": "tool_use", "name": "Edit",
                                         "input": {"file_path": str(target),
                                                   "old_string": "pass",
                                                   "new_string": "return 1"}}]}}))
        recs.append(json.dumps({
            "type": "assistant", "sessionId": "s1", "cwd": d,
            "timestamp": "2026-08-14T10:03:00Z",
            "message": {"content": [{"type": "text",
                                     "text": "리뷰 결과: 결함 2건 발견. 예외 처리 누락, 반환값 미검증."}]}}))
        f = Path(d) / "t.jsonl"
        f.write_text("\n".join(recs), encoding="utf-8")
        return f

    def test_parser_extracts_answer_and_reads(self):
        with tempfile.TemporaryDirectory() as d:
            sess = trajectory.parse_trajectory(self._review_traj(d))
        self.assertIn("리뷰 결과", sess["final_answer"])
        self.assertEqual(len(sess["read_paths"]), 1)
        self.assertEqual(sess["search_count"], 1)
        self.assertEqual(sess["file_ops"], [])

    def test_review_session_gets_answer_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            groups = trajectory.group_by_artifacts(
                [trajectory.parse_trajectory(self._review_traj(d))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
        self.assertEqual(man["recovery"], "HIGH_CONFIDENCE")
        art = man["artifacts"][0]
        self.assertEqual(art["type"], "answer")
        self.assertIn("리뷰 결과", art["content"])
        self.assertEqual(art["review_evidence"]["files_read"], 1)
        self.assertGreater(art["review_evidence"]["read_loc_total"], 0)
        self.assertEqual(art["review_evidence"]["search_count"], 1)

    def test_mixed_session_default_no_answer(self):
        # 편집이 있으면 기본은 파일 산출물만 — 답변 노이즈 안 붙음
        with tempfile.TemporaryDirectory() as d:
            groups = trajectory.group_by_artifacts(
                [trajectory.parse_trajectory(self._review_traj(d, with_edit=True))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
        self.assertFalse(any(a.get("type") == "answer" for a in man["artifacts"]))

    def test_mixed_session_optin_appends_answer(self):
        with tempfile.TemporaryDirectory() as d:
            groups = trajectory.group_by_artifacts(
                [trajectory.parse_trajectory(self._review_traj(d, with_edit=True))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None,
                                                include_answers=True)
        types = [a.get("type") for a in man["artifacts"]]
        self.assertIn("answer", types)
        self.assertGreater(len(man["artifacts"]), 1)

    def test_answer_rules_only_when_answer_present(self):
        base = {"job_id": "j", "task_requests": [], "grouping_evidence": [],
                "excluded_transient_paths": [], "unresolved": [], "sessions": [],
                "repository": ".", "base_state": "b", "end_state": "e",
                "recovery": "EXACT", "recovery_note": ""}
        p1 = workload.build_prompt({**base, "artifacts": [
            {"path": "a.py", "status": "M", "attribution": "DIRECT_NET", "confidence": 0.99}]},
            _rates())
        self.assertNotIn("review_evidence", p1)
        p2 = workload.build_prompt({**base, "artifacts": [
            {"path": "(대화 답변)", "type": "answer", "status": "A",
             "attribution": "TRANSCRIPT", "confidence": 0.95, "content": "x",
             "review_evidence": {"files_read": 1, "read_loc_total": 10, "search_count": 0}}]},
            _rates())
        self.assertIn("독립 결과", p2)
        self.assertIn("실측치", p2)

    def test_answer_e2e_with_sim(self):
        with tempfile.TemporaryDirectory() as d:
            groups = trajectory.group_by_artifacts(
                [trajectory.parse_trajectory(self._review_traj(d))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            rates = _rates()
            est = workload.estimate_workload(man, SimLLM(), rates)
            report = rate_engine.build_report(man, est, rates)
        self.assertGreater(report["rhe_p50_hours"], 0)
        self.assertTrue(report["auto_approved"])


class TestLLMFactory(unittest.TestCase):
    def test_sim_and_dynamic_load(self):
        import llm as llm_mod
        self.assertTrue(callable(llm_mod.make_llm("sim").complete_json))
        obj = llm_mod.make_llm("sim_llm:SimLLM")  # 모듈경로:클래스명 동적 로드
        self.assertTrue(callable(obj.complete_json))

    def test_unknown_backend_raises(self):
        import llm as llm_mod
        with self.assertRaises(ValueError):
            llm_mod.make_llm("nonsense")


class _FlakyLLM:
    """1회 실패 후 성공 — 재시도 검증용."""

    def __init__(self, good):
        self.calls = 0
        self.good = good

    def complete_json(self, prompt, max_tokens):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("일시 오류")
        return self.good


class TestRetry(unittest.TestCase):
    def _manifest(self):
        return {"job_id": "j", "task_requests": ["x"], "grouping_evidence": [],
                "artifacts": [{"path": "a.py", "status": "M", "attribution": "DIRECT_NET",
                               "confidence": 0.99}],
                "excluded_transient_paths": [], "unresolved": [], "sessions": [],
                "repository": ".", "base_state": "b", "end_state": "e",
                "recovery": "EXACT", "recovery_note": ""}

    def test_retry_then_success(self):
        good = {"completed_outcomes": [], "excluded_outputs": [], "measurement_required": [],
                "action_ledger": [{"action": "construct", "workload_unit": "function_point",
                                   "workload": 1}]}
        llm = _FlakyLLM(good)
        est = workload.estimate_workload(self._manifest(), llm, _rates(), retries=1)
        self.assertEqual(llm.calls, 2)
        self.assertEqual(len(est["action_ledger"]), 1)

    def test_exhausted_raises(self):
        class Dead:
            def complete_json(self, p, max_tokens):
                raise RuntimeError("down")
        with self.assertRaises(RuntimeError):
            workload.estimate_workload(self._manifest(), Dead(), _rates(), retries=1)

    def test_long_request_truncated(self):
        import manifest as manifest_mod
        sess = _fake_session("s1", set())
        sess["task_requests"] = ["가" * 9000]
        man = manifest_mod.build_manifest(
            "j", [sess], ".", {"base": "b", "end": "e", "recovery": "EXACT", "note": ""},
            [], [], [])
        self.assertLessEqual(len(man["task_requests"][0]), 1500)


def _fake_session(sid, paths, ts="2026-08-13T10:00:00Z", cwd="C:/proj"):
    return {"file": f"{sid}.jsonl", "session_id": sid, "cwd": cwd,
            "timestamps": [ts], "task_requests": [],
            "direct_paths": set(paths), "bash_candidate_paths": set(),
            "git_commands": []}


class TestGrouping(unittest.TestCase):
    def test_overlap_merges_and_disjoint_separates(self):
        s1 = _fake_session("s1", {"C:/proj/src/auth.ts", "C:/proj/src/token.ts"})
        s2 = _fake_session("s2", {"C:/proj/src/auth.ts", "C:/proj/tests/auth.test.ts"},
                           ts="2026-08-13T11:00:00Z")
        s3 = _fake_session("s3", {"C:/proj/docs/readme.md"}, ts="2026-08-13T12:00:00Z")
        groups = trajectory.group_by_artifacts([s1, s2, s3])
        self.assertEqual(len(groups), 2)
        ids = [{s["session_id"] for s in g["sessions"]} for g in groups]
        self.assertIn({"s1", "s2"}, ids)
        self.assertIn({"s3"}, ids)
        merged = groups[ids.index({"s1", "s2"})]
        self.assertTrue(merged["grouping_evidence"])
        self.assertIn("auth.ts", merged["grouping_evidence"][0]["common_paths"][0])

    def test_transitive_chain(self):
        s1 = _fake_session("s1", {"C:/p/a.py"})
        s2 = _fake_session("s2", {"C:/p/a.py", "C:/p/b.py"}, ts="2026-08-13T11:00:00Z")
        s3 = _fake_session("s3", {"C:/p/b.py"}, ts="2026-08-13T12:00:00Z")
        groups = trajectory.group_by_artifacts([s1, s2, s3])
        self.assertEqual(len(groups), 1)  # s1∩s2, s2∩s3 → s1·s3도 한 그룹
        self.assertEqual([s["session_id"] for s in groups[0]["sessions"]], ["s1", "s2", "s3"])

    def test_min_common_threshold(self):
        s1 = _fake_session("s1", {"C:/p/readme.md", "C:/p/a.py"})
        s2 = _fake_session("s2", {"C:/p/readme.md", "C:/p/b.py"})
        self.assertEqual(len(trajectory.group_by_artifacts([s1, s2], min_common=2)), 2)
        self.assertEqual(len(trajectory.group_by_artifacts([s1, s2], min_common=1)), 1)

    def test_relative_paths_normalized_with_cwd(self):
        # 같은 상대경로라도 cwd가 다르면 절대경로가 달라 병합되지 않는다
        s1 = _fake_session("s1", {"src/a.py"}, cwd="C:/proj1")
        s2 = _fake_session("s2", {"src/a.py"}, cwd="C:/proj2")
        self.assertEqual(len(trajectory.group_by_artifacts([s1, s2])), 2)

    def test_pathless_session_is_own_group(self):
        s1 = _fake_session("s1", {"C:/p/a.py"})
        s2 = _fake_session("s2", set())
        self.assertEqual(len(trajectory.group_by_artifacts([s1, s2])), 2)


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

            sessions = [trajectory.parse_trajectory(str(traj))]
            groups = trajectory.group_by_artifacts(sessions)
            self.assertEqual(len(groups), 1)
            man = estimate.build_group_manifest("job-1", groups[0], str(repo), base, None)
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

    def test_no_evidence_is_unrecoverable(self):
        with tempfile.TemporaryDirectory() as d:
            traj = Path(d) / "t.jsonl"
            traj.write_text(json.dumps({"type": "user", "sessionId": "s1",
                                        "message": {"role": "user", "content": "x"}}),
                            encoding="utf-8")
            groups = trajectory.group_by_artifacts([trajectory.parse_trajectory(str(traj))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            self.assertEqual(man["recovery"], "UNRECOVERABLE")
            self.assertEqual(man["artifacts"], [])


class TestNoGit(unittest.TestCase):
    """Git 없는 프로젝트 (§7): trajectory 기록 + 현재 파일 대조."""

    def _traj_line(self, tool, inp, cwd):
        return json.dumps({"type": "assistant", "sessionId": "s1", "cwd": cwd,
                           "timestamp": "2026-08-13T10:00:00Z",
                           "message": {"content": [{"type": "tool_use",
                                                    "name": tool, "input": inp}]}})

    def test_write_verified_high_confidence(self):
        with tempfile.TemporaryDirectory() as d:
            content = "# 보고서\n1페이지 수정본\n"
            (Path(d) / "deck.md").write_text(content, encoding="utf-8")
            traj = Path(d) / "t.jsonl"
            traj.write_text(self._traj_line(
                "Write", {"file_path": str(Path(d) / "deck.md"), "content": content}, d),
                encoding="utf-8")
            groups = trajectory.group_by_artifacts([trajectory.parse_trajectory(str(traj))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            self.assertEqual(man["recovery"], "HIGH_CONFIDENCE")
            self.assertEqual(man["artifacts"][0]["confidence"], 0.95)
            self.assertIn("current_file_match", man["artifacts"][0]["evidence_sources"])

    def test_edit_only_counts_the_change_not_whole_file(self):
        # 기존 문서 1군데 수정 — 전체 파일이 아니라 old/new 기록만 diff로 남는다
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "deck.md").write_text(
                "페이지1 원본\n페이지2 수정본\n페이지3 원본\n" + "기존내용\n" * 50,
                encoding="utf-8")
            traj = Path(d) / "t.jsonl"
            traj.write_text(self._traj_line(
                "Edit", {"file_path": str(Path(d) / "deck.md"),
                         "old_string": "페이지2 원본", "new_string": "페이지2 수정본"}, d),
                encoding="utf-8")
            groups = trajectory.group_by_artifacts([trajectory.parse_trajectory(str(traj))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            art = man["artifacts"][0]
            self.assertEqual(art["status"], "M")  # 신규 작성 아님
            self.assertIn("페이지2", art["diff"])
            self.assertNotIn("기존내용", art["diff"])  # 전체 파일이 산출물로 잡히지 않음
            self.assertEqual(man["recovery"], "HIGH_CONFIDENCE")

    def test_mismatch_is_partial(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.md").write_text("세션 이후 다른 내용", encoding="utf-8")
            traj = Path(d) / "t.jsonl"
            traj.write_text(self._traj_line(
                "Write", {"file_path": str(Path(d) / "a.md"), "content": "세션 당시 내용"}, d),
                encoding="utf-8")
            groups = trajectory.group_by_artifacts([trajectory.parse_trajectory(str(traj))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            self.assertEqual(man["recovery"], "PARTIAL")
            self.assertEqual(man["artifacts"][0]["confidence"], 0.5)

    def test_deleted_file_is_transient(self):
        with tempfile.TemporaryDirectory() as d:
            traj = Path(d) / "t.jsonl"
            traj.write_text(self._traj_line(
                "Write", {"file_path": str(Path(d) / "proto.md"), "content": "x"}, d),
                encoding="utf-8")
            groups = trajectory.group_by_artifacts([trajectory.parse_trajectory(str(traj))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            self.assertIn("proto.md", man["excluded_transient_paths"])
            self.assertEqual(man["recovery"], "UNRECOVERABLE")  # 남은 산출물 없음

    def test_no_git_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            content = "def f():\n    return 1\n"
            (Path(d) / "m.py").write_text(content, encoding="utf-8")
            traj = Path(d) / "t.jsonl"
            traj.write_text(self._traj_line(
                "Write", {"file_path": str(Path(d) / "m.py"), "content": content}, d),
                encoding="utf-8")
            groups = trajectory.group_by_artifacts([trajectory.parse_trajectory(str(traj))])
            man = estimate.build_group_manifest("job-1", groups[0], d, None, None)
            rates = _rates()
            est = workload.estimate_workload(man, SimLLM(), rates)
            report = rate_engine.build_report(man, est, rates)
            self.assertGreater(report["rhe_p50_hours"], 0)
            self.assertTrue(report["auto_approved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
