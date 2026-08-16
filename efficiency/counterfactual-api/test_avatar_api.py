# -*- coding: utf-8 -*-
"""avatar_api(사전 조합 입구) 테스트 — 명령한 조합대로 부품이 연결되는지 (mock)."""
import copy
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (Path(__file__).parent, _ROOT / "human-effort"):
    sys.path.insert(0, str(_p))

from test_estimator import REQ_OUT, EFFORT_OUT  # noqa: E402 (mock 데이터)
from avatar_api import estimate_avatar  # noqa: E402


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
        if "한 번에 내부적으로" in prompt:  # req-actions 단일호출
            return {"todos": [{"title": "보고서",
                               "quantities": [{"name": "분량", "value": 2000,
                                               "unit": "단어"}],
                               "acceptance_criteria": ["a"]}],
                    "human": [{"primitive": "draft", "count": 100}],
                    "rationale": "s"}
        if "행동 분해 엔진" in prompt:  # req-actions
            return {"human": [{"primitive": "draft", "count": 500},
                              {"primitive": "verify", "count": 2}],
                    "rationale": "ra"}
        if "Avatar Task Requirement Converter" in prompt:
            return copy.deepcopy(REQ_OUT)
        if "실행 공수 산정" in prompt:  # agent-llm
            return {"agent": [{"primitive": "draft", "count": 200}],
                    "hitl": [{"primitive": "instruct", "count": 1}],
                    "ai_io": {}, "rationale": "a"}
        return copy.deepcopy(EFFORT_OUT)  # Prompt B


CARD = "업무 제목: 보고서 작성\n업무 상세: 경쟁사 5곳 조사 후 2000단어 보고서"


class TestAvatarCombos(unittest.TestCase):
    def test_default_merged_one_call(self):
        llm = MockLLM()
        r = estimate_avatar(llm, CARD)
        self.assertEqual(len(llm.calls), 1)          # 호출 병합
        self.assertEqual(r["human"]["method"], "req-actions")   # 방법론은 기존 것
        self.assertEqual(r["agent"]["method"], "agent-llm")
        self.assertTrue(r["human"]["merged_call"])
        self.assertAlmostEqual(r["human"]["min"], 17.0, places=1)
        self.assertIsNotNone(r["speedup"])

    def test_workunit_combo(self):
        llm = MockLLM()
        r = estimate_avatar(llm, CARD, human="workunit", calls="staged")
        self.assertEqual(r["human"]["method"], "workunit")
        self.assertIsNotNone(r["human"]["p80_min"])
        self.assertEqual(r["agent"]["method"], "agent-llm")

    def test_req_actions_staged(self):
        llm = MockLLM()
        r = estimate_avatar(llm, CARD, human="req-actions", agent="agent-llm",
                            calls="staged")
        self.assertEqual(r["human"]["method"], "req-actions")
        self.assertEqual(r["agent"]["method"], "agent-llm")
        self.assertGreater(r["human"]["min"], 0)

    def test_req_actions_single_not_merged_pair(self):
        # workunit 분자 + single: 병합 대상 아님 — 각자 호출
        llm = MockLLM()
        r = estimate_avatar(llm, CARD, human="workunit", calls="single")
        self.assertEqual(r["human"]["method"], "workunit")
        self.assertGreater(len(llm.calls), 1)

    def test_invalid_combo_rejected(self):
        with self.assertRaises(ValueError):
            estimate_avatar(MockLLM(), CARD, agent="record", calls="staged")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
