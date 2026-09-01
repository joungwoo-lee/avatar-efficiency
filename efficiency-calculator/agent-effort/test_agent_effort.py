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
        # §77: 파일 확인은 유형 무관 확인 시점당 1건(로그·상한), 보고=결론만 정독
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
            # §77 파일 확인(유형 무관, 확인 시점 1회): 구간 쓴 단어
            #   500+250+1 = 751 → 0.5×ln(1+7.51) = 1.071
            #   + 결론 100×0.005 + 진행 100×0.00222 (§71 분자 동속)
            #   = 1.071 + 0.5 + 0.222 = 1.793
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 1.793,
                                   places=2)
            self.assertEqual(m["automation_saved_min"], 0.0)
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

    def test_file_check_log_cap(self):
        # §77: 파일 확인 = min(2.0, 0.5×ln(1 + 구간 쓴 단어/100)) — 규모가
        # 커져도 상한 2.0분. (테스트 실패 상태 = 검증 제외 없음, §78)
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes

        def session(words, test_output="2 failed, 3 passed"):
            lines = [
                {"type": "user", "message": {"role": "user", "content": "고쳐줘"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "a.py", "new_string": "x " * words}},
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

        # 200단어 → 0.5×ln(3) = 0.549 / 1,000 → 0.5×ln(11) = 1.199
        self.assertAlmostEqual(session(200)["breakdown"]["hitl"]["review"],
                               0.549, places=2)
        self.assertAlmostEqual(session(1000)["breakdown"]["hitl"]["review"],
                               1.199, places=2)
        # 20,000단어 → 상한 2.0
        self.assertAlmostEqual(session(20000)["breakdown"]["hitl"]["review"],
                               2.0, places=2)
        # §78: 테스트 통과 → 그 이전에 쓴 코드 파일은 확인 대상 제외 → 0,
        # 줄어든 만큼 automation_saved_min
        m = session(1000, "12 passed in 1.2s")
        self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 0.0, places=2)
        self.assertAlmostEqual(m["automation_saved_min"], 1.2, places=2)

    def test_code_review_turn_billing(self):
        # §50·§77: 파일 확인은 확인 시점(턴)당 1회 — 같은 변경을 7파일로
        # 쪼개도 확인비가 7배가 되지 않는다(구간 단어 합만 본다)
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
            # §77: 확인 시점(세션 끝) 1회, 구간 70단어 → 0.5×ln(1.7) = 0.265 → 0.27
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 0.27,
                                   places=2)
        finally:
            os.unlink(p)

    def test_code_check_per_real_turn(self):
        # §50·§77: 실질 지시 턴(5단어+)이 확인 시점 — 파일 쓰기가 있는 구간마다
        # 파일 확인 1회. 2구간 = 2회. 짧은 이어가기 턴은 확인 시점 아님.
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
            # §77: 확인 2회 × 0.5×ln(1.1) = 2×0.0477 = 0.095 → 0.10 (반올림)
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 0.10,
                                   places=2)
        finally:
            os.unlink(p)

    def test_verified_files_excluded_only(self):
        # §78: 통과 테스트 **이전**에 쓴 코드 파일만 제외. 테스트 뒤 다시 고친
        # 파일(dirty)과 코드 아닌 파일은 확인 대상에 남는다.
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
        lines = [
            {"type": "user", "message": {"role": "user", "content": "고쳐줘"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "a.py", "new_string": "x " * 500}},
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "out.csv", "content": "a,b " * 100}},
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "pytest tests/"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "12 passed in 1.2s"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "b.py", "new_string": "z " * 100}}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            c = parse_actions(p)
            ev = c["code_check_events"][0]
            self.assertEqual(ev["verified_files"], 1)          # a.py만
            self.assertEqual(ev["words_raw"], 700)
            self.assertEqual(ev["words"], 200)                 # csv 100 + b.py 100
            m = actual_effort_minutes(c)
            # 0.5×ln(3) = 0.549 / 제외 전 0.5×ln(8) = 1.040 → saved 0.49
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 0.549,
                                   places=2)
            self.assertAlmostEqual(m["automation_saved_min"], 0.49, places=2)
        finally:
            os.unlink(p)

    def test_file_check_counts_non_code_files(self):
        # §77: 코드가 아닌 파일(데이터·문서)만 만든 구간도 파일 확인 1건 —
        # 사람은 결과물을 본다. 100단어 → 0.5×ln(2) = 0.347
        import json, tempfile, os
        from transcript_actual import parse_actions, actual_effort_minutes
        lines = [
            {"type": "user", "message": {"role": "user", "content": "표 만들어"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "data.csv", "content": "a,b " * 100}}]}},
        ]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        try:
            c = parse_actions(p)
            self.assertEqual(len(c["code_check_events"]), 1)
            self.assertEqual(c["code_check_events"][0]["words"], 100)
            self.assertEqual(c["code_check_events"][0]["files"], 0)  # 코드 0
            m = actual_effort_minutes(c)
            self.assertAlmostEqual(m["breakdown"]["hitl"]["review"], 0.347,
                                   places=2)
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
            #        + 파일 확인 0.5×ln(1+0/100) = 0, 내용물 0단어)
            #        + 교정 0 (§77 폐지) = 1.2 + 0.1 = 1.3
            self.assertAlmostEqual(m["machine_min"], 0.39, places=2)
            self.assertAlmostEqual(m["hitl_min"], 1.3, places=2)
            self.assertNotIn("correct", m["breakdown"]["hitl"])
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
