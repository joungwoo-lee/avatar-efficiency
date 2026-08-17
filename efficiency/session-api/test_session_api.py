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
    lines = [
        {"type": "user", "sessionId": "s-1",
         "message": {"role": "user", "content": "경쟁사 5곳 조사해서 보고서 써줘"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "조사하겠습니다 " * 20},
            {"type": "tool_use", "name": "WebSearch", "input": {}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "결과 " * 200}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
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
        self.assertAlmostEqual(a1["machine_min"], 0.56, places=2)

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
            r_off = measure(p, humanize=False)
            r_again = measure(p)
        self.assertEqual(r_on["human"]["method"], "record-actions-code")
        self.assertTrue(r_on["human"]["humanize"])
        self.assertGreater(r_on["human"]["min"], 0)
        self.assertIsNotNone(r_on["speedup"])
        # 대조군은 검토 전량 정독·번복 미소거라 휴먼화본 이상이어야 함
        self.assertGreaterEqual(r_off["human"]["min"], r_on["human"]["min"])
        # 결정론: 같은 입력 → 같은 결과
        self.assertEqual(r_again["human"]["min"], r_on["human"]["min"])

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
