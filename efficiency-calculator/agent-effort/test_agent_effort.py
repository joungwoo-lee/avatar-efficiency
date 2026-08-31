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
            # §50 턴 확인 + §63 코드/문서 요율 분리:
            #   동작 확인 1회 2.0 + 코드 500×0.005 + 문서 250×0.0025
            #   + 문서·기타 파일당 표본 확인 2×0.5
            #   + 결론 100×0.005 + 진행 100×0.00222 (§71 분자 동속)
            #   = 2 + 2.5 + 0.625 + 1 + 0.5 + 0.222 = 6.847
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 6.847,
                                   places=2)
            # §52 기계 draft = (답변 200 + 파일 본문 500+250+1)×0.002
            #                = 1.902, execute 3×0.3 → machine 2.80
            self.assertAlmostEqual(m["machine_min"], 2.80, places=2)
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

        # 충분한 테스트(12 passed, 기대 2파일×3=6) → ratio 1 → 에피소드
        # 기본비 2.0→0.3 (§49: 강등은 파일당이 아니라 에피소드 기본비에 적용)
        m = session("============ 12 passed in 1.2s ============")
        self.assertAlmostEqual(m["automation_saved_min"], 1.7, places=2)
        # 형식 테스트(1 passed) → ratio 1/6 → 할인 미미 (saved = 1.7×1/6)
        m = session("1 passed in 0.1s")
        self.assertAlmostEqual(m["automation_saved_min"], 0.28, places=2)
        # 실패 상태로 종료 → 강등 0
        m = session("2 failed, 3 passed")
        self.assertEqual(m["automation_saved_min"], 0.0)

    def test_code_review_turn_billing(self):
        # §50: 코드 동작 확인은 확인 시점(턴)당 1회 — 같은 변경을 7파일로
        # 쪼개도 확인비가 7배가 되지 않고, 파일 수는 훑기 단어로만 반영
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
        lines = [
            {"type": "user", "message": {"role": "user", "content": "만들어줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": f"m{i}.py", "content": "x " * 10}}
                for i in range(7)]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            m = actual_effort_minutes(parse_actions(p))
            # 검토 = 확인 시점(세션 끝) 1회 2.0 + 코드 70단어×0.005 = 2.35
            # (§63 코드 요율 0.002 → 0.005)
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 2.35,
                                   places=2)
        finally:
            os.unlink(p)

    def test_code_check_per_real_turn(self):
        # §50: 실질 지시 턴(5단어+)이 확인 시점 — 코드 변경이 있는 구간마다
        # 동작 확인 1회. 2구간 = 2회. 짧은 이어가기 턴은 확인 시점 아님.
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes

        def turn(fp):
            return {"type": "assistant", "message": {
                "role": "assistant", "content": [
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": fp, "new_string": "x " * 10}}]}}
        lines = [
            {"type": "user", "message": {"role": "user",
             "content": "이 버그 원인 찾아서 고쳐줘"}},
            turn("a.py"),
            {"type": "user", "message": {"role": "user",
             "content": "좋아 이제 b 모듈도 같은 방식으로 고쳐"}},  # 확인 시점
            turn("b.py"),
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            c = parse_actions(p)
            self.assertEqual(len(c["code_check_events"]), 2)  # 턴 + 세션 끝
            m = actual_effort_minutes(c)
            # 검토 = 동작 확인 2회×2.0 + 코드 20단어×0.005 = 4.10 (§63)
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 4.10,
                                   places=2)
        finally:
            os.unlink(p)

    def test_demotion_excludes_files_edited_after_test(self):
        # §49: 마지막 테스트 결과 이후 수정된 파일은 검증 분율에서 제외 —
        # 테스트 후 2파일 중 1파일을 더 고치면 강등 폭이 절반
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
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
                 "content": "12 passed in 1.2s"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "b.py", "new_string": "z " * 10}}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            m = actual_effort_minutes(parse_actions(p))
            # ratio 1 × 검증분율 1/2 → eff = 2.0 − 1.7×0.5 = 1.15,
            # saved = 0.85 (전판 검증이었으면 1.7)
            self.assertAlmostEqual(m["automation_saved_min"], 0.85, places=2)
        finally:
            os.unlink(p)

    def test_conclusion_promotion_threshold(self):
        # §49: 5단어 미만 짧은 이어가기 지시는 직전 답변을 결론으로 승격하지
        # 않는다 — 중간 보고가 정독 과금되는 오차 방지. 세션 마지막 답변은
        # 문턱과 무관하게 결론.
        import json, tempfile, os
        from transcript_actual import parse_actions
        lines = [
            {"type": "user", "message": {"role": "user", "content": "이 문제 원인 분석해서 보고해줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "진행 " * 100}]}},
            {"type": "user", "message": {"role": "user", "content": "계속해"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "결론 " * 40}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            c = parse_actions(p)
            # "계속해"(1단어)는 승격 안 함 → 진행 100단어는 훑기로 남고,
            # 마지막 답변 40단어만 결론
            self.assertEqual(c["conclusion_words"], 40)
            # 5단어 이상 지시였다면 100단어가 결론으로 승격됐을 것
        finally:
            os.unlink(p)

    def test_conclusion_deep_read_cap(self):
        # §51: 결론 정독은 건별 300단어 상한 — 초과분은 훑기로 강등
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
        lines = [
            {"type": "user", "message": {"role": "user", "content": "이 주제 심층 분석 보고서 작성해줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "결론 " * 500}]}},   # 결론 500단어
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            m = actual_effort_minutes(parse_actions(p))
            # 검토 = 정독 200×0.005 + 초과 훑기 300×0.00222 = 1.0 + 0.666 = 1.666 (§71·§74 상한 200)
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 1.666,
                                   places=2)
        finally:
            os.unlink(p)

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
            # §49: interrupt 직후 첫 지시("제목 바꿔줘") = 교정성 지시 표시
            self.assertEqual(c["corrective_instructions"], 1)
            m = actual_effort_minutes(c)
            # machine = 1×0.3 + 100×0.0005 + 20×0.002 = 0.39
            # hitl = 지시 2건×(0.5+0.05×2단어) + 검토(결론 20단어×정독 0.005 §71
            #        + 문서 파일 표본 확인 0.5, 내용물 0단어)
            #        + 교정 1×4.0 = 1.2 + 0.6 + 4.0 = 5.8
            self.assertAlmostEqual(m["machine_min"], 0.39, places=2)
            self.assertAlmostEqual(m["hitl_min"], 5.8, places=2)
            self.assertEqual(m["total_min"],
                             actual_effort_minutes(parse_actions(p))["total_min"])
        finally:
            os.unlink(p)


    def test_ai_wall_never_exceeds_span(self):
        import json, tempfile, os
        from transcript_actual import parse_actions
        # §65: 방치 구간이 AI 시간으로 흡수되면 안 된다.
        # 실제 보고 사례 — 9.1일 열린 세션에서 ai_wall_min이 8.3일로 잡혔다.
        # 턴 끝 도장 없이 며칠 뒤 tool_result가 도착한 경우.
        T = "2026-08-%02dT09:%02d:00.000Z"
        lines = [
            {"type": "user", "timestamp": T % (3, 0),
             "message": {"role": "user", "content": "긴 작업 시켜둔다 " * 20}},
            {"type": "assistant", "timestamp": T % (3, 1),
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t1", "name": "Bash",
                  "input": {"command": "long-running"}}]}},
            # 10일 뒤에 결과가 도착 — 그 사이는 방치다
            {"type": "user", "timestamp": T % (13, 1),
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1",
                  "content": "done " * 30}]}},
            {"type": "assistant", "timestamp": T % (13, 3),
             "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "끝났습니다 " * 20}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + chr(10))
        try:
            c = parse_actions(p)
            span = c["session_span_min"]
            self.assertGreater(span, 14000)        # 약 10일
            # 간격 상한 10분 → 도착 간격 10일이 10분으로 잘린다
            # 총 AI 시간 = 1분(지시→첫 응답) + 10분(상한) + 2분 = 13분
            self.assertLess(c["ai_wall_min"], 15)
            # 불변식: AI 시간은 세션 러닝타임을 넘을 수 없다
            self.assertLessEqual(c["ai_wall_min"], span)
        finally:
            os.unlink(p)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
