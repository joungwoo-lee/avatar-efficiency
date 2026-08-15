# -*- coding: utf-8 -*-
"""counterfactual-api 오프라인 테스트 — integ-spec §2/§6 계약 검증 (mock LLM)."""
import copy
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "human-effort", _ROOT / "agent-effort", Path(__file__).parent):
    sys.path.insert(0, str(_p))

from test_estimator import REQ_OUT, EFFORT_OUT, SPEC  # noqa: E402 (human-effort)
from compat import CounterfactualEstimator  # noqa: E402

AGENT_OUT = {
    "agent": [{"primitive": "read", "count": 800},
              {"primitive": "draft", "count": 200},
              {"primitive": "verify", "count": 1}],
    "hitl": [{"primitive": "instruct", "count": 1},
             {"primitive": "review", "count": 200},
             {"primitive": "approve", "count": 1}],
    "ai_io": {"input_words": 900, "output_words": 250},
    "rationale": "AI가 초안 생성, 사람은 지시·검토·승인만 수행",
}

SPEC_KEYS = ("error", "human_min", "agent_min", "agent_human_min", "agent_ai_min",
             "saved_min", "speedup", "human_breakdown", "agent_breakdown",
             "rationale", "confidence", "confidence_notes")


class MockLLM:
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, max_tokens):
        self.calls.append(prompt)
        if "Avatar Task Requirement Converter" in prompt:
            return copy.deepcopy(REQ_OUT)
        if "실행 공수 산정" in prompt:  # agent_effort 분모 프롬프트
            return copy.deepcopy(AGENT_OUT)
        return copy.deepcopy(EFFORT_OUT)


class TestCompat(unittest.TestCase):
    def test_contract_and_math(self):
        ce = CounterfactualEstimator(llm=MockLLM())
        r = ce.estimate_task("월간 경쟁사 동향", "정기 보고", "애널리스트",
                             ["research-web"], "경쟁사 5곳 조사 후 보고서")
        for k in SPEC_KEYS:
            self.assertIn(k, r)
        self.assertIsNone(r["error"])
        self.assertGreater(r["human_min"], 0)
        self.assertGreaterEqual(r["human_p80_min"], r["human_min"])
        self.assertAlmostEqual(r["agent_ai_min"], 1.69, places=2)
        self.assertAlmostEqual(r["agent_human_min"], 3.9, places=2)
        self.assertAlmostEqual(
            r["agent_min"], r["agent_human_min"] + r["agent_ai_min"], places=2)
        self.assertAlmostEqual(r["saved_min"], r["human_min"] - r["agent_min"], places=2)
        self.assertAlmostEqual(r["speedup"], round(r["human_min"] / r["agent_min"], 2))
        self.assertIn("ai_io", r["agent_breakdown"])
        self.assertIsInstance(r["confidence"], str)
        self.assertIsInstance(r["confidence_notes"], list)

    def test_call_count_and_no_rate_leak(self):
        llm = MockLLM()
        CounterfactualEstimator(llm=llm).estimate_task("t", "c", "r", [], "d")
        self.assertEqual(len(llm.calls), 3)  # A-avatar + B + agent_effort
        for prompt in llm.calls:
            self.assertNotIn("min_per_unit", prompt)
            self.assertNotIn("time_model", prompt)

    def test_error_path_all_keys_null(self):
        class Boom:
            def complete_json(self, p, m):
                raise RuntimeError("down")
        r = CounterfactualEstimator(llm=Boom()).estimate_task("t", "c", "r", [], "d")
        for k in SPEC_KEYS:
            self.assertIn(k, r)
        self.assertIsNotNone(r["error"])
        for k in ("human_min", "agent_min", "agent_human_min", "agent_ai_min",
                  "saved_min", "speedup"):
            self.assertIsNone(r[k])

    def test_none_inputs_tolerated(self):
        r = CounterfactualEstimator(llm=MockLLM()).estimate_task(
            None, None, None, None, None)
        self.assertIsNone(r["error"])
        self.assertGreater(r["human_min"], 0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
