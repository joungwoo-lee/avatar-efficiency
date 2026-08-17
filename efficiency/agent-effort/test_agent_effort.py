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
    def test_type_based_review(self):
        # 검토 방식은 산출물이 정한다: 코드=동작 확인, 문서=정독, 보고=결론만 정독
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
        lines = [
            {"type": "user", "message": {"role": "user", "content": "작업해줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "진행 보고 " * 50},   # 진행 100단어 = 훑기
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "app.py", "content": "코드 " * 500}},
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "report.md", "content": "내용 " * 250}},
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "conf.json", "content": "{}"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "결론 " * 100}]}},    # 결론 100단어 = 정독
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            m = actual_effort_minutes(parse_actions(p))
            # 검토 = 코드 1파일×2.0(실행 확인) + 코드 500단어×0.002(diff 훑기)
            #      + 문서 250단어×0.008(정독) + 기타 1파일×0.5(표본 확인)
            #      + 결론 100×0.008 + 진행 100×0.002 = 2+1+2+0.5+0.8+0.2 = 6.5
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 6.5,
                                   places=2)
        finally:
            os.unlink(p)

    def test_structured_output_counted(self):
        # §34: JSON 보고(StructuredOutput 입력)는 답변 텍스트와 동급 —
        # AI 쓰기(draft)·사람 검토(결론 정독)에 계상. 텍스트 150 + 숫자 1.
        import json, tempfile, os
        from transcript_actual import parse_actions
        lines = [
            {"type": "user", "message": {"role": "user", "content": "분석해줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "StructuredOutput",
                 "input": {"summary": "결과 " * 150, "count": 3}}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            c = parse_actions(p)
            self.assertEqual(c["assistant_words"], 151)   # 쓰기 계상
            self.assertEqual(c["conclusion_words"], 151)  # 결론(정독 검토) 계상
            self.assertEqual(c["tool_calls"], 1)
        finally:
            os.unlink(p)

    def test_automation_discount(self):
        # 검증 위임 강등: 통과 테스트 규모에 비례, 형식 테스트는 할인 미미
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes

        def session(test_output):
            lines = [
                {"type": "user", "message": {"role": "user", "content": "고쳐줘"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "a.py", "new_string": "x " * 100}},
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "b.py", "new_string": "y " * 100}},
                    {"type": "tool_use", "id": "t1", "name": "Bash",
                     "input": {"command": "pytest tests/"}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1",
                     "content": test_output}]}},
            ]
            fd, p = tempfile.mkstemp(suffix=".jsonl")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            try:
                return actual_effort_minutes(parse_actions(p))
            finally:
                os.unlink(p)

        # 충분한 테스트(12 passed, 기대 2파일×3=6) → ratio 1 → 파일당 0.3
        m = session("============ 12 passed in 1.2s ============")
        self.assertAlmostEqual(m["automation_saved_min"], 3.4, places=2)
        # 형식 테스트(1 passed) → ratio 1/6 → 할인 미미 (saved = 3.4×1/6)
        m = session("1 passed in 0.1s")
        self.assertAlmostEqual(m["automation_saved_min"], 0.57, places=2)
        # 실패 상태로 종료 → 강등 0
        m = session("2 failed, 3 passed")
        self.assertEqual(m["automation_saved_min"], 0.0)

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
            # hitl = 지시 2건×(0.5+0.05×2단어) + 검토(결론 20단어×정독 0.008,
            #        문서 산출물 0단어) + 교정 1×4.0 = 1.2 + 0.16 + 4.0 = 5.36
            self.assertAlmostEqual(m["machine_min"], 0.39, places=2)
            self.assertAlmostEqual(m["hitl_min"], 5.36, places=2)
            self.assertEqual(m["total_min"],
                             actual_effort_minutes(parse_actions(p))["total_min"])
        finally:
            os.unlink(p)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
