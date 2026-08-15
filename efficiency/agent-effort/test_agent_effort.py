# -*- coding: utf-8 -*-
"""agent-effort 오프라인 테스트 (mock LLM)."""
import sys
import unittest

from agent_effort import (estimate_agent_min, speedup, load_rates,
                          build_prompt, validate_llm_output)

MOCK_OUT = {
    "agent": [{"primitive": "read", "count": 800},
              {"primitive": "draft", "count": 200},
              {"primitive": "verify", "count": 1}],
    "hitl": [{"primitive": "instruct", "count": 1},
             {"primitive": "review", "count": 200},
             {"primitive": "approve", "count": 1}],
    "ai_io": {"input_words": 900, "output_words": 250},
    "rationale": "test",
}


class MockLLM:
    def __init__(self, queue=None):
        self.queue = list(queue) if queue else [dict(MOCK_OUT)]
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        return self.queue.pop(0)


class TestAgentEffort(unittest.TestCase):
    def test_math_hand_check(self):
        # 기계: read 800×0.0005 + draft 200×0.002 + verify 1×0.5 = 1.3
        # ai_io: 900×0.00002 + 250×0.0015 = 0.39 → agent_ai = 1.69
        # hitl: instruct 1×1.7(실측 평균) + 200×0.006 + 1.0 = 3.9 → agent_min = 5.59
        r = estimate_agent_min(MockLLM(), "spec")
        self.assertAlmostEqual(r["agent_ai_min"], 1.69, places=2)
        self.assertAlmostEqual(r["agent_human_min"], 3.9, places=2)
        self.assertAlmostEqual(r["agent_min"], 5.59, places=2)

    def test_speedup_definition(self):
        # 사람이 AI 없이 100분, AI 써서 10분 → 효율 10배
        self.assertEqual(speedup(100, 10), 10.0)
        self.assertIsNone(speedup(100, 0))

    def test_no_rate_leak_in_prompt(self):
        prompt = build_prompt("spec", load_rates())
        self.assertNotIn("min_per_unit", prompt)
        self.assertNotIn("0.0005", prompt)
        self.assertNotIn("3.0", prompt)

    def test_invalid_then_retry(self):
        llm = MockLLM(queue=[{"garbage": 1}, dict(MOCK_OUT)])
        r = estimate_agent_min(llm, "spec")
        self.assertEqual(len(llm.calls), 2)
        self.assertGreater(r["agent_min"], 0)

    def test_bad_items_dropped(self):
        out = {"agent": [{"primitive": "nonexistent", "count": 5},
                         {"primitive": "read", "count": -1},
                         {"primitive": "read", "count": 100}],
               "hitl": [], "ai_io": {}}
        parsed, notes, fatal = validate_llm_output(out, load_rates())
        self.assertFalse(fatal)
        self.assertEqual(len(parsed["agent"]), 1)
        self.assertTrue(any("hitl 비어" in n for n in notes))




class TestTranscriptActual(unittest.TestCase):
    def test_deterministic_hand_check(self):
        # 실측 분모: 트랜스크립트 → 기계/HITL 동작 × 요율 (LLM 미사용)
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
        lines = [
            {"type": "user", "message": {"role": "user", "content": "보고서 만들어줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "네 만들겠습니다 " * 10},
                {"type": "tool_use", "name": "Write", "input": {"file_path": "a.md"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "ok " * 100}]}},
            {"type": "user", "message": {"role": "user", "content": "[Request interrupted by user]"}},
            {"type": "user", "message": {"role": "user", "content": "제목 바꿔줘"}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            c = parse_actions(p)
            self.assertEqual(c["tool_calls"], 1)
            self.assertEqual(c["user_instructions"], 2)
            self.assertEqual(c["interrupts"], 1)
            m = actual_effort_minutes(c)
            # machine = 1×0.3 + 100×0.0005 + 20×0.002 = 0.39
            # hitl(보정 모델) = 2건×(0.5+0.05×2단어) + 20×0.006 + 1×4.0 = 5.32
            self.assertAlmostEqual(m["machine_min"], 0.39, places=2)
            self.assertAlmostEqual(m["hitl_min"], 5.32, places=2)
            self.assertEqual(m["total_min"],
                             actual_effort_minutes(parse_actions(p))["total_min"])
        finally:
            os.unlink(p)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
