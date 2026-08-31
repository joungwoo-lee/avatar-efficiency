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
    # 타임스탬프는 §64 초소형 게이트(세션 러닝타임 5분 이하 제외)를 넘기기
    # 위해 필요하다 — 첫 기록(09:00)부터 마지막(09:08)까지 8분.
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

    def test_think_includes_subagent_report_and_thinking(self):
        # §68: 서브 보고문 전량 + 서브의 전략 생각 토큰이 think 행에 들어간다
        # (draft 아님). 양 모드 동일 → ON ≤ OFF 불변.
        from record_actions_code_api import measure, collect_strategy_thinking
        T = "2026-08-31T00:%02d:00.000Z"
        def rec(t, content, ts, sub=False, usage=None):
            m = {"role": t, "id": f"m{ts}{int(sub)}", "content": content}
            if usage:
                m["usage"] = usage
            r = {"type": t, "timestamp": ts, "message": m}
            if sub:
                r["isSidechain"] = True
            return r
        think_usage = {"output_tokens_details": {"thinking_tokens": 400}}
        main = [rec("user", [{"type": "text", "text": "plan it"}], T % 0),
                rec("assistant", [{"type": "tool_use", "id": "ag", "name": "Agent",
                                   "input": {"prompt": "plan"}}], T % 1),
                rec("user", [{"type": "tool_result", "tool_use_id": "ag",
                              "content": "ok"}], T % 9),
                rec("assistant", [{"type": "text", "text": "done"}], T % 10)]
        sub = [rec("user", [{"type": "text", "text": "plan"}], T % 2, sub=True),
               rec("assistant", [{"type": "thinking", "thinking": "hmm"},
                                 {"type": "text", "text": "plan " * 200}],
                   T % 3, sub=True, usage=think_usage)]
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "s.jsonl"); sp = os.path.join(d, "agent-s.jsonl")
            with open(mp, "w", encoding="utf-8") as f:
                f.write("\n".join(json.dumps(r) for r in main) + "\n")
            with open(sp, "w", encoding="utf-8") as f:
                f.write("\n".join(json.dumps(r) for r in sub) + "\n")
            st = collect_strategy_thinking(mp, [sp])
            self.assertEqual(st["sub_tokens"], 400)
            self.assertEqual(st["tokens"], 400)       # 메인 첫 응답엔 생각 없음
            r_on = measure(mp, force=True, subagent_paths=[sp])
            r_off = measure(mp, force=True, subagent_paths=[sp],
                            humanize_rw=False, humanize_act=False)
        for r in (r_on, r_off):
            th = [b for b in r["human"]["breakdown"] if b["primitive"] == "think"]
            self.assertEqual(len(th), 1)
            # 400토큰×0.75 = 300단어 + 서브 보고 200단어 = 500
            self.assertEqual(th[0]["count"], 500)
            self.assertEqual(th[0]["detail"]["sub_report_words"], 200)
            self.assertEqual(r["human"]["think"]["sub_report_words"], 200)
            # 보고문이 draft로 새지 않는다
            self.assertFalse(any(b["primitive"] == "draft"
                                 and b["count"] >= 200
                                 for b in r["human"]["breakdown"]))
        self.assertGreaterEqual(r_off["human"]["min"], r_on["human"]["min"])

    def test_query_read_full_deep_and_search_turn_floor(self):
        # §70: (a) 기여 판정된 조회형(셸 sed -n) 결과는 블록 분해 없이 전량 정독
        #      (b) 검색 건수 하한 = 검색한 지시 턴 수 (세션당 1이 아님)
        import record_actions_code_api  # noqa: F401
        from requirement_actions import collect_record_stats
        from record_actions_code_api import build_actions
        from agent_effort import load_rates
        body = "word " * 900   # 5블록 — 증거 없는 블록은 종전엔 훑기
        def turn(i, cmd_search, cmd_read):
            return [
                {"type": "user", "message": {"role": "user",
                                             "content": f"지시 {i} " * 30}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": f"g{i}", "name": "Bash",
                     "input": {"command": cmd_search}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"g{i}",
                     "content": "src/mod.py:12: needle"}]}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": f"r{i}", "name": "Bash",
                     "input": {"command": cmd_read}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"r{i}", "content": body}]}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": f"확인 {i}"}]}},
            ]
        lines = (turn(1, "grep -n needle src/mod.py", "sed -n 1,80p src/mod.py")
                 + turn(2, "grep -n other src/mod.py", "sed -n 200,280p src/mod.py")
                 + turn(3, "grep -n third src/mod.py", "sed -n 400,480p src/mod.py"))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            rs = collect_record_stats(p, detail=True)
        # 각 턴의 sed -n은 검색 직후 첫 읽기 = 착지(④) → 기여. 조회형이라 전량 정독.
        self.assertEqual(rs["search_calls"], 3)
        self.assertEqual(rs["search_turns"], 3)
        self.assertEqual(rs["contributed_docs"], 3)
        self.assertEqual(rs["deep_words"], 900 * 3)
        self.assertEqual(rs["skim_words"], 0)
        # 검색 건수: 착지-기여 3 = 턴 3 → 3건 (종전 규칙도 3; 하한 검증은 아래)
        rs2 = dict(rs); rs2["search_landing_docs"] = 0   # 착지가 기여 안 된 경우 가정
        acts = {a["primitive"]: a for a in build_actions(rs2, load_rates())}
        self.assertEqual(acts["search"]["count"], 3)       # 세션당 1 아님, 턴당 1

    def test_answer_narration_and_search_output(self):
        # §73: (7) 파일 산출물 있어도 마무리 답변은 draft(doc) (8) 진행 나레이션은
        # think 요율 (12) 검색 결과 판독은 rw ON 읽기에 앞 200 정독·나머지 훑기.
        import record_actions_code_api  # noqa: F401
        from requirement_actions import collect_record_stats
        from record_actions_code_api import measure
        lines = [
            {"type": "user", "message": {"role": "user", "content": "지시 " * 10}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "먼저 찾아보겠습니다 " * 20},        # 나레이션 2×20=40
                {"type": "tool_use", "id": "g1", "name": "Grep",
                 "input": {"pattern": "needle"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "g1", "content": "hit " * 500}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "w1", "name": "Write",
                 "input": {"file_path": "a.py", "content": "code " * 100}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "w1", "content": "ok"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "완료 보고 " * 25}]}},                # 마무리 50
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            rs = collect_record_stats(p, subagent_paths=[])
            self.assertEqual(rs["answer_words"], 50)
            self.assertEqual(rs["narration_words"], 40)
            self.assertEqual(rs["search_out_deep_words"], 200)
            self.assertEqual(rs["search_out_skim_words"], 300)
            r_on = measure(p, force=True, subagent_paths=[])
            r_off = measure(p, force=True, subagent_paths=[],
                            humanize_rw=False, humanize_act=False)
        bd = {b["primitive"]: b for b in r_on["human"]["breakdown"]}
        # (7) 파일 100단어(code) + 마무리 답변 50단어(doc) 둘 다 draft
        self.assertEqual(bd["draft"]["detail"], {"code": 100, "doc": 50})
        # (8) 나레이션 40단어 → think
        self.assertEqual(bd["think"]["detail"]["narration_words"], 40)
        # (12) rw ON 읽기 = 지시 10 + 검색 결과 정독 200 + 훑기 300×(0.00222/0.005)
        self.assertAlmostEqual(bd["read"]["count"], 10 + 200 + 300 * 0.444, places=0)
        bd0 = {b["primitive"]: b for b in r_off["human"]["breakdown"]}
        self.assertEqual(bd0["draft"]["detail"], {"code": 100, "doc": 50})
        # OFF 읽기는 reviewed 전량(검색 결과 500 + "ok" 1) + 지시 10 — 가산 없음
        self.assertEqual(bd0["read"]["count"], 511)
        self.assertGreaterEqual(r_off["human"]["min"], r_on["human"]["min"])

    def test_range_read_full_deep_and_contributed_floor(self):
        # §75: (a) Read(offset/limit)로만 읽은 기여 파일은 전량 정독(§70 조회형과
        # 동일 행위) (b) 통째 읽은 기여 파일은 증거 블록 없어도 최소 200단어 정독.
        import record_actions_code_api  # noqa: F401
        from requirement_actions import collect_record_stats
        body = "w " * 1000   # 증거 없는 5블록
        lines = [
            {"type": "user", "message": {"role": "user", "content": "지시 " * 10}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "g", "name": "Grep", "input": {"pattern": "x"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "g", "content": "a.py b.py"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "r1", "name": "Read",
                 "input": {"file_path": "a.py", "offset": 100, "limit": 80}},   # 범위 → 착지·기여
                {"type": "tool_use", "id": "r2", "name": "Read",
                 "input": {"file_path": "b.py"}}]}},                          # 통째
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "r1", "content": body},
                {"type": "tool_result", "tool_use_id": "r2", "content": body}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "a.py 와 b.py 확인함"}]}},          # ② 이름 언급 → 둘 다 기여
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            rs = collect_record_stats(p, subagent_paths=[], detail=True)
        self.assertEqual(rs["contributed_docs"], 2)
        self.assertEqual(rs["files"]["deep_split"]["a.py"], [1000, 0])   # 범위 읽기 전량 정독
        self.assertEqual(rs["files"]["deep_split"]["b.py"], [200, 800])  # 통째: 바닥 200
        self.assertEqual(rs["deep_words"], 1200)
        self.assertEqual(rs["skim_words"], 800)

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
            # §64 게이트 우회 (합성 픽스처는 타임스탬프 없음)
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
            # §64 게이트는 이 테스트 대상이 아니다 — 합성 픽스처는 러닝타임이
            # 5분 이하라 제외되므로 force로 우회
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
        # §48·§69: 무효 실행 상쇄 — 쓰기 순계의 "실패한 편집 제외"(§31) 이식.
        # 실패 판정은 환경·타이핑 실수·거부 서명이 있을 때만(§69). 종료코드≠0
        # (테스트 실패 로그)은 숙련자도 똑같이 짜서 돌리는 정상 작업 → 생존.
        #   npx tset 2회 "command not found"(무효, 신원 탈락)
        #   pytest 실패(is_error지만 테스트 실패 로그 → 생존)→성공
        #   make build 성공 → 순계 2(pytest·build; npx 신원 탈락). exec_calls는 5 그대로.
        import record_actions_code_api  # noqa: F401 (sys.path 세팅)
        from requirement_actions import collect_record_stats
        cnf = "bash: npx: command not found"
        tf = "FAILED tests/test_a.py::test_x - AssertionError " + "log " * 30
        runs = [("npx tset", True, cnf), ("npx tset", True, cnf),
                ("pytest tests/", True, tf), ("pytest tests/", False, "ok"),
                ("make build", False, "ok")]
        lines = [{"type": "user",
                  "message": {"role": "user", "content": "작업 지시 " * 60}}]
        for i, (c, err, out) in enumerate(runs):
            lines += [
                {"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "tool_use", "id": f"e{i}", "name": "Bash",
                              "input": {"command": c}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"e{i}",
                     "is_error": err, "content": out}]}},
            ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            rs = collect_record_stats(p)
        self.assertEqual(rs["exec_calls"], 5)      # 로레코드 불변
        self.assertEqual(rs["exec_net_calls"], 2)  # pytest+build (npx는 탈락)
        # compose 순계: 무효 npx 탈락, pytest 첫 실패 호출의 명령문은 계상
        self.assertEqual(rs["exec_compose_words"], 2 + 2)   # "pytest tests/" + "make build"
        self.assertEqual(rs["exec_compose_words_gross"], 2 * 5)

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
