# -*- coding: utf-8 -*-
"""조합 층 테스트 — 명령한 조합대로 부품이 연결되는지 (mock LLM)."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "human-effort"))

from api import estimate_avatar, measure_session  # noqa: E402
from test_estimator import REQ_OUT, EFFORT_OUT  # noqa: E402


class MockLLM:
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        if "두 실행경로" in prompt:  # paths (§3 동시 분해)
            return {"human": [{"primitive": "read", "count": 800},
                              {"primitive": "draft", "count": 200},
                              {"primitive": "verify", "count": 1}],
                    "agent": [{"primitive": "read", "count": 800},
                              {"primitive": "draft", "count": 200}],
                    "hitl": [{"primitive": "instruct", "count": 1},
                             {"primitive": "review", "count": 200}],
                    "ai_io": {"input_words": 900, "output_words": 250},
                    "rationale": "r"}
        if "행동 분해 엔진" in prompt:  # req-actions
            return {"human": [{"primitive": "draft", "count": 500},
                              {"primitive": "verify", "count": 2}],
                    "rationale": "ra"}
        if ("Avatar Task Requirement Converter" in prompt
                or "Delivered Requirement Reconstruction Engine" in prompt):
            return copy.deepcopy(REQ_OUT)
        if "업무 에포트 산정" in prompt and "AI 에이전트 실행" not in prompt \
                and "human" in prompt:  # record-actions (primitive)
            return {"human": [{"primitive": "read", "count": 100},
                              {"primitive": "draft", "count": 50}],
                    "rationale": "p"}
        if "실행 공수 산정" in prompt:  # agent-llm
            return {"agent": [{"primitive": "draft", "count": 200}],
                    "hitl": [{"primitive": "instruct", "count": 1}],
                    "ai_io": {}, "rationale": "a"}
        return copy.deepcopy(EFFORT_OUT)  # Prompt B


CARD = "업무 제목: 보고서 작성\n업무 상세: 경쟁사 5곳 조사 후 2000단어 보고서"


def _session_file(d):
    lines = [
        {"type": "user", "message": {"role": "user",
                                     "content": "경쟁사 5곳 조사해서 보고서 " * 20}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "완료 " * 60},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "r.md", "content": "내용 " * 200}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "자료 " * 300}]}},
    ]
    p = os.path.join(d, "s.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    return p


class TestAvatarCombos(unittest.TestCase):
    def test_default_paths_one_call(self):
        llm = MockLLM()
        r = estimate_avatar(llm, CARD)
        self.assertEqual(len(llm.calls), 1)
        self.assertAlmostEqual(r["human"]["min"], 17.0, places=1)
        self.assertGreater(r["agent"]["total_min"], 0)
        self.assertIsNotNone(r["speedup"])

    def test_workunit_combo(self):
        llm = MockLLM()
        r = estimate_avatar(llm, CARD, human="workunit")
        self.assertEqual(r["human"]["method"], "workunit")
        self.assertIsNotNone(r["human"]["p80_min"])
        self.assertEqual(r["agent"]["method"], "paths")

    def test_req_actions_with_agent_llm(self):
        llm = MockLLM()
        r = estimate_avatar(llm, CARD, human="req-actions", agent="agent-llm")
        self.assertEqual(r["human"]["method"], "req-actions")
        self.assertEqual(r["agent"]["method"], "agent-llm")
        self.assertGreater(r["human"]["min"], 0)

    def test_invalid_combo_rejected(self):
        with self.assertRaises(ValueError):
            estimate_avatar(MockLLM(), CARD, agent="record")


class TestSessionCombos(unittest.TestCase):
    def test_default_workunit(self):
        with tempfile.TemporaryDirectory() as d:
            r = measure_session(MockLLM(), _session_file(d))
        self.assertEqual(r["human"]["method"], "workunit")
        self.assertEqual(r["agent"]["method"], "record")
        self.assertGreater(r["speedup"], 0)

    def test_req_actions(self):
        with tempfile.TemporaryDirectory() as d:
            r = measure_session(MockLLM(), _session_file(d), human="req-actions")
        self.assertEqual(r["human"]["method"], "req-actions")
        self.assertIn("anchors", r["human"])

    def test_record_actions(self):
        with tempfile.TemporaryDirectory() as d:
            r = measure_session(MockLLM(), _session_file(d), human="record-actions")
        self.assertEqual(r["human"]["method"], "record-actions")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
