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
        # hitl: 3.0 + 200×0.006 + 1.0 = 5.2 → agent_min = 6.89
        r = estimate_agent_min(MockLLM(), "spec")
        self.assertAlmostEqual(r["agent_ai_min"], 1.69, places=2)
        self.assertAlmostEqual(r["agent_human_min"], 5.2, places=2)
        self.assertAlmostEqual(r["agent_min"], 6.89, places=2)

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


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
