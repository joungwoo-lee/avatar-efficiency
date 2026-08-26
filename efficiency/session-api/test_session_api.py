# -*- coding: utf-8 -*-
"""session-api 오프라인 테스트 (mock LLM + 합성 트랜스크립트)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "human-effort", _ROOT / "agent-effort", Path(__file__).parent):
    sys.path.insert(0, str(_p))

from test_estimator import REQ_OUT  # noqa: E402 (human-effort mock 데이터)
from session_api import (measure_session, measure_sessions,  # noqa: E402
                         measure_agent_actual, JsonRetryLLM)

# 행동 분해 응답 (req-actions·record-actions 공용 스키마)
ACTIONS_OUT = {"human": [{"primitive": "read", "count": 1000},
                         {"primitive": "draft", "count": 500},
                         {"primitive": "verify", "count": 1}],
               "rationale": "mock"}
# 단일호출 응답: 내부 할일 정리 + 행동 분해
SINGLE_OUT = dict(ACTIONS_OUT, todos=[
    {"title": "경쟁사 비교 보고서",
     "quantities": [{"name": "보고서", "value": 2000, "unit": "단어"}],
     "acceptance_criteria": ["5개사 포함"]}])


class MockLLM:
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        if "Delivered Requirement Reconstruction Engine" in prompt:  # §23 추출기
            import copy
            return copy.deepcopy(REQ_OUT)
        if "한 번에 내부적으로" in prompt:                # 단일호출(할일+행동)
            return json.loads(json.dumps(SINGLE_OUT))
        return json.loads(json.dumps(ACTIONS_OUT))       # 행동 분해만


def _make_jsonl(dirpath):
    # 타임스탬프는 §64 초소형 게이트(AI 실행 5분 이하 제외)를 넘기기 위해
    # 필요하다 — AI 구간이 지시(00:00)부터 마지막 응답(00:08)까지 8분.
    T = "2026-08-20T09:%02d:00.000Z"
    lines = [
        {"type": "user", "sessionId": "s-1", "timestamp": T % 0,
         "message": {"role": "user", "content": "경쟁사 5곳 조사해서 보고서 써줘"}},
        {"type": "assistant", "timestamp": T % 1,
         "message": {"role": "assistant", "content": [
            {"type": "text", "text": "조사하겠습니다 " * 20},
            {"type": "tool_use", "name": "WebSearch", "input": {}}]}},
        {"type": "user", "timestamp": T % 4, "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "결과 " * 200}]}},
        {"type": "assistant", "timestamp": T % 8,
         "message": {"role": "assistant", "content": [
            {"type": "text", "text": "보고서 완성했습니다 " * 30}]}},
    ]
    p = os.path.join(dirpath, "sess.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    return p


class TestSessionApi(unittest.TestCase):
    def test_measure_session_single_default(self):
        # 기본: req-actions + 단일호출 — 세션당 LLM 1회
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            llm = MockLLM()
            r = measure_session(llm, p)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(r["human"]["method"], "req-actions")
        self.assertGreater(r["human"]["min"], 0)
        self.assertGreater(r["agent"]["total_min"], 0)
        self.assertGreater(r["agent"]["hitl_min"], 0)   # 지시 1건 반영
        self.assertIsNotNone(r["speedup"])
        self.assertAlmostEqual(
            r["speedup"], round(r["human"]["min"] / r["agent"]["total_min"], 2))
        self.assertEqual(r["session_id"], "s-1")
        # 닻(§30): 할일 명시 2000단어라도 실측 산출물(대화 보고 60단어)이
        # 천장 — 명시 채널은 LLM 경유라 위조 가능, 실측 초과분은 절단
        counts = {b["primitive"]: b["count"] for b in r["human"]["breakdown"]}
        self.assertEqual(counts["draft"], 60)
        self.assertEqual(r["human"]["anchors"]["out_words_kind"], "measured")
        self.assertEqual(r["human"]["todos"], ["경쟁사 비교 보고서"])

    def test_measure_session_staged(self):
        # staged: 할일 추출 + 행동 분해 = LLM 2회, 단계별 감사 가능
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            llm = MockLLM()
            r = measure_session(llm, p, calls="staged")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(r["human"]["method"], "req-actions")
        self.assertGreater(r["human"]["min"], 0)

    def test_measure_session_record_actions(self):
        # 교차확인 기준선: 할일 안 거침, LLM 1회, 같은 닻 적용
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            llm = MockLLM()
            r = measure_session(llm, p, human="record-actions")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(r["human"]["method"], "record-actions")
        self.assertGreater(r["human"]["min"], 0)
        self.assertIn("anchors", r["human"])

    def test_workunit_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            with self.assertRaises(ValueError):
                measure_session(MockLLM(), p, human="workunit")

    def test_actual_only_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            a1 = measure_agent_actual(p)
            a2 = measure_agent_actual(p)
        self.assertEqual(a1["total_min"], a2["total_min"])
        # 수기검산: 기계 = execute 1×0.3 + read 200×0.0005 + draft 80×0.002 = 0.56
        # §62 기계시간 = 턴 실측: 지시(09:00) → 마지막 AI 기록(09:08) = 8분
        # (구 요율 계산이면 0.56이었다 — 타임스탬프가 있으면 실측 우선)
        self.assertAlmostEqual(a1["machine_min"], 8.0, places=2)

    def test_batch_isolates_failures(self):
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            rows = measure_sessions(MockLLM(), [p, os.path.join(d, "없는파일.jsonl")])
        self.assertNotIn("error", rows[0])
        self.assertIn("error", rows[1])

    def test_trivial_session_excluded(self):
        # 초소형(핑퐁) 세션은 LLM 호출 없이 측정에서 제외
        lines = [
            {"type": "user", "message": {"role": "user", "content": "핑"}},
            {"type": "assistant", "message": {"role": "assistant",
                                              "content": [{"type": "text", "text": "퐁"}]}},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "tiny.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            llm = MockLLM()
            r = measure_session(llm, p)
            self.assertTrue(r.get("excluded"))
            self.assertEqual(len(llm.calls), 0)      # LLM 비용 0
            r2 = measure_session(llm, p, force=True) # 강제 측정은 가능
            self.assertNotIn("excluded", r2)

    def test_req_actions_api_wrapper(self):
        # 방식별 전용 API ①: req_actions_api.measure = req-actions 고정
        from req_actions_api import measure
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            llm = MockLLM()
            r = measure(llm, p)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(r["human"]["method"], "req-actions")

    def test_record_actions_api_wrapper(self):
        # 방식별 전용 API ②: record_actions_api.measure = record-actions 고정
        from record_actions_api import measure
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            llm = MockLLM()
            r = measure(llm, p)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(r["human"]["method"], "record-actions")

    def test_record_actions_code_api(self):
        # 방식별 전용 API ③(§32): LLM 0회 — 코드 실측만으로 분자 구성.
        # humanize=False(대조군)는 읽기 등급·쓰기 순계를 끈 옛 자 — 항상 이상.
        from record_actions_code_api import measure
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            r_on = measure(p)
            r_off = measure(p, humanize_rw=False)
            r_again = measure(p)
        self.assertEqual(r_on["human"]["method"], "record-actions-code")
        self.assertTrue(r_on["human"]["humanize_rw"])
        self.assertTrue(r_on["human"]["humanize_act"])
        self.assertFalse(r_off["human"]["humanize_rw"])
        self.assertGreater(r_on["human"]["min"], 0)
        self.assertIsNotNone(r_on["speedup"])
        # 대조군은 검토 전량 정독·번복 미소거라 휴먼화본 이상이어야 함
        self.assertGreaterEqual(r_off["human"]["min"], r_on["human"]["min"])
        # 결정론: 같은 입력 → 같은 결과
        self.assertEqual(r_again["human"]["min"], r_on["human"]["min"])

    def test_rawrecord_mode(self):
        # §39: rawrecord = 궤적 재연 — 행동 횟수를 세션 기록 그대로.
        # Bash 6회 세션: 기본 자는 execute 1건, rawrecord는 6건.
        from record_actions_code_api import measure
        lines = [{"type": "user",
                  "message": {"role": "user", "content": "작업 지시 " * 60}}]
        for i in range(6):
            lines += [
                {"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash",
                              "input": {"command": "run"}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"b{i}",
                     "content": "ok " * 30}]}},
            ]
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": "완료 보고 " * 30}]}})
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            # §64 게이트 우회 (합성 픽스처는 AI 실행 0분)
            base = measure(p, force=True)
            raw = measure(p, humanize_act=False, humanize_rw=False, force=True)
            legacy = measure(p, humanize="rawrecord", force=True)  # 구 인터페이스
        bd_base = {b["primitive"]: b["count"] for b in base["human"]["breakdown"]}
        bd_raw = {b["primitive"]: b["count"] for b in raw["human"]["breakdown"]}
        self.assertEqual(bd_base["execute"], 1)   # 순계: 같은 명령 6회 = 신원 1건
        self.assertEqual(bd_raw["execute"], 6)    # 궤적 재연: 기록 그대로
        # §43: 마무리 verify는 두 모드 공통 — 소형 세션에서 천장<바닥 역전 방지
        self.assertEqual(bd_base.get("verify"), 1)
        self.assertEqual(bd_raw.get("verify"), 1)
        self.assertFalse(raw["human"]["humanize_act"])
        self.assertEqual(raw["human"]["humanize"], "rawrecord")  # 호환 표현
        self.assertEqual(legacy["human"]["min"], raw["human"]["min"])
        self.assertGreater(raw["human"]["min"], base["human"]["min"])

    def test_act_net_counts(self):
        # §46: act ON = 행동 순계 — 실행은 명령 신원당 1건. 서로 다른 명령
        # 2종(각각 반복 포함, 총 5회) → execute 2건. 로레코드는 5건 그대로.
        from record_actions_code_api import measure
        cmds = ["pytest tests/", "pytest tests/", "pytest tests/",
                "git diff", "git diff"]
        lines = [{"type": "user",
                  "message": {"role": "user", "content": "작업 지시 " * 60}}]
        for i, c in enumerate(cmds):
            lines += [
                {"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "tool_use", "id": f"c{i}", "name": "Bash",
                              "input": {"command": c}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"c{i}",
                     "content": "ok " * 30}]}},
            ]
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": "완료 보고 " * 30}]}})
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            # §64 게이트는 이 테스트 대상이 아니다 — 합성 픽스처는 AI 실행
            # 시간이 5분 이하라 제외되므로 force로 우회
            base = measure(p, force=True)
            raw = measure(p, humanize_rw=False, humanize_act=False, force=True)
        bd_base = {b["primitive"]: b["count"] for b in base["human"]["breakdown"]}
        bd_raw = {b["primitive"]: b["count"] for b in raw["human"]["breakdown"]}
        self.assertEqual(bd_base["execute"], 2)   # 신원 2개(pytest, git diff)
        self.assertEqual(bd_raw["execute"], 5)    # 로레코드: 호출 수 그대로
        self.assertLessEqual(bd_base["execute"], bd_raw["execute"])  # 단조성

    def test_shell_reclassify(self):
        # §47: 셸 명령 재분류 — grep류=검색, sed -n류=읽기, 나머지=실행.
        import record_actions_code_api  # noqa: F401 (sys.path 세팅)
        from requirement_actions import (classify_shell_command,
                                         collect_record_stats)
        cases = {"grep -n foo a.py": "search",
                 "cd /x && grep -rn bar . | head -5": "search",
                 "grep x || true": "search",
                 "sed -n 10,40p mod.py": "read",
                 "PYTHONIOENCODING=utf-8 cat f.md | wc -l": "read",
                 "sed -i s/a/b/ f.py": "exec",
                 "pytest tests/": "exec",
                 "cat > out.txt <<EOF": "exec",
                 "grep x && git commit -m m": "exec",
                 "echo done": "exec",
                 "grep x 2>&1 | head": "search"}
        for cmd, want in cases.items():
            self.assertEqual(classify_shell_command(cmd), want, cmd)
        # 통합: 셸 grep(검색 신호) → 직후 셸 sed -n 60단어(조회형 읽기 착지)
        lines = [
            {"type": "user",
             "message": {"role": "user", "content": "작업 지시 " * 60}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "g1", "name": "Bash",
                 "input": {"command": "grep -n needle src/mod.py"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "g1",
                 "content": "src/mod.py:3: needle"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "r1", "name": "Bash",
                 "input": {"command": "sed -n 1,80p src/mod.py"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "r1",
                 "content": "본문 " * 60}]}},
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "text", "text": "완료 보고 " * 30}]}},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            rs = collect_record_stats(p)
        self.assertEqual(rs["search_calls"], 1)       # grep = 검색 축
        self.assertEqual(rs["exec_calls"], 0)         # 실행 축 비움
        self.assertEqual(rs["contributed_docs"], 1)   # sed 착지 = 기여 조회
        self.assertEqual(rs["search_landing_docs"], 1)

    def test_failed_exec_cancelled(self):
        # §48: 실패 실행 상쇄 — 쓰기 순계의 "실패한 편집 제외"(§31) 이식.
        # npm test 2회 전부 실패(신원 탈락) + pytest 실패→성공(신원 생존)
        # + build 성공 → 순계 2. 로레코드 exec_calls는 5 그대로.
        import record_actions_code_api  # noqa: F401 (sys.path 세팅)
        from requirement_actions import collect_record_stats
        runs = [("npm test", True), ("npm test", True), ("pytest tests/", True),
                ("pytest tests/", False), ("make build", False)]
        lines = [{"type": "user",
                  "message": {"role": "user", "content": "작업 지시 " * 60}}]
        for i, (c, err) in enumerate(runs):
            lines += [
                {"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "tool_use", "id": f"e{i}", "name": "Bash",
                              "input": {"command": c}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"e{i}",
                     "is_error": err, "content": "log " * 30}]}},
            ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            rs = collect_record_stats(p)
        self.assertEqual(rs["exec_calls"], 5)      # 로레코드 불변
        self.assertEqual(rs["exec_net_calls"], 2)  # pytest(성공 有)+build

    def test_suspect_output_channel(self):
        # §38: 미등록 도구 입력에 글 60단어가 실려 나갔고 응답은 ack,
        # 잡힌 산출물 0 → 쓰기 툴 포맷 미등록 의심 자백 (§33 사고의 서명).
        # 운영성 세션(실행만 하고 산출물 없음)은 오탐하지 않아야 한다.
        from record_actions_code_api import measure
        base = [{"type": "user",
                 "message": {"role": "user", "content": "작업 지시 " * 60}}]
        write_like = base + [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "w1", "name": "mcp__jira__add_comment",
                 "input": {"issue": "PROJ-1", "body": "분석 결과 " * 30}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "w1",
                 "content": "comment added"}]}},
        ]
        ops_only = base
        for i in range(6):  # 실행만 6회 — 산출물 없음 = 정당한 무산출 세션
            ops_only = ops_only + [
                {"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash",
                              "input": {"command": "do-something"}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"b{i}",
                     "content": "ok " * 30}]}},
            ]
        with tempfile.TemporaryDirectory() as d:
            paths = {}
            for name, lines in (("w.jsonl", write_like), ("o.jsonl", ops_only)):
                p = os.path.join(d, name)
                with open(p, "w", encoding="utf-8") as f:
                    for ln in lines:
                        f.write(json.dumps(ln, ensure_ascii=False) + "\n")
                paths[name] = p
            r_w = measure(paths["w.jsonl"], force=True)
            r_o = measure(paths["o.jsonl"], force=True)
            normal = measure(_make_jsonl(d), force=True)
        self.assertTrue(r_w["suspect_output_channel"])
        self.assertIn("쓰기 툴 포맷 미등록 의심", r_w["notes"][0])
        self.assertIn("mcp__jira__add_comment", r_w["notes"][0])  # 도구명 명시
        self.assertFalse(r_o["suspect_output_channel"])   # 운영성 세션 미표시
        self.assertFalse(normal["suspect_output_channel"])

    @unittest.skipUnless(os.environ.get("AE_LIVE_HAIKU") == "1",
                         "실호출(과금)은 AE_LIVE_HAIKU=1일 때만")
    def test_claude_cli_llm_haiku(self):
        # 실LLM 꽂기 예시: 클로드 코드를 서브프로세스로 하이쿠 모델 호출.
        # llm 자리는 complete_json(prompt, max_tokens)->dict 객체면 뭐든 된다 —
        # ClaudeCliLLM이 그 계약을 `claude -p --model haiku`로 구현(어댑터
        # 본체는 claude_cli_llm.py). 비용이 들므로 AE_LIVE_HAIKU=1일 때만 실행.
        from claude_cli_llm import ClaudeCliLLM
        llm = JsonRetryLLM(ClaudeCliLLM())          # 기본 모델 haiku
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            r = measure_session(llm, p, force=True)
        self.assertGreater(r["human"]["min"], 0)
        self.assertIsNotNone(r["speedup"])

    def test_json_retry_wrapper(self):
        class Flaky:
            def __init__(self):
                self.n = 0

            def complete_json(self, prompt, max_tokens):
                self.n += 1
                if self.n < 3:
                    raise ValueError("bad json")
                return {"ok": 1}
        self.assertEqual(JsonRetryLLM(Flaky(), retries=2)
                         .complete_json("p", 10), {"ok": 1})


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
