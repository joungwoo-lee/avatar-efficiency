# -*- coding: utf-8 -*-
"""session-api 오프라인 테스트 (mock LLM + 합성 트랜스크립트)."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "human-effort", _ROOT / "agent-effort", Path(__file__).parent):
    sys.path.insert(0, str(_p))

from test_estimator import REQ_OUT, EFFORT_OUT  # noqa: E402 (human-effort mock 데이터)
from session_api import (measure_session, measure_sessions,  # noqa: E402
                         measure_agent_actual, JsonRetryLLM)


class MockLLM:
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        if "Delivered Requirement Reconstruction Engine" in prompt:  # §23 추출기
            return copy.deepcopy(REQ_OUT)
        return copy.deepcopy(EFFORT_OUT)  # Prompt B


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
    def test_measure_session_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            p = _make_jsonl(d)
            llm = MockLLM()
            r = measure_session(llm, p)
        self.assertEqual(len(llm.calls), 2)  # §23 추출 + Prompt B
        self.assertGreater(r["human"]["p50_min"], 0)
        self.assertGreater(r["agent"]["total_min"], 0)
        self.assertGreater(r["agent"]["hitl_min"], 0)   # 지시 1건 반영
        self.assertIsNotNone(r["speedup"])
        self.assertAlmostEqual(
            r["speedup"], round(r["human"]["p50_min"] / r["agent"]["total_min"], 2))
        self.assertEqual(r["session_id"], "s-1")
        self.assertEqual(r["human"]["requirements"][0][0], "R-001")

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
