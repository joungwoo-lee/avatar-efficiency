# -*- coding: utf-8 -*-
"""session-translator 오프라인 테스트 (§96) — 손으로 만든 작은 기록으로 대응 규칙을 고정한다.

실제 기록 모양은 Codex CLI 0.162.1·OpenCode 2.0.29가 남긴 기록에서 따왔다(개인 정보 없음).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (_HERE, _ROOT / "session-api", _ROOT / "agent-effort",
           _ROOT / "human-effort" / "requirement-actions"):
    sys.path.insert(0, str(_p))

from session_translator import (convert, detect_format,  # noqa: E402
                              hunks_from_unified_diff, parse_apply_patch,
                              file_ops_to_tools, list_sessions, translate_session,
                              find_opencode_db, find_codex_home, ro_uri)
import opencode_translator  # noqa: E402

T0 = 1792040000.0          # 기준 시각(초)


def iso(sec):
    from session_translator import iso as _iso
    return _iso(sec)


def ms(sec):
    return int(sec * 1000)


def rec(t, typ, payload):
    return {"timestamp": iso(T0 + t), "type": typ, "payload": payload}


def ev(t, payload):
    return rec(t, "event_msg", payload)


def ri(t, payload):
    return rec(t, "response_item", payload)


def item(t0, t1, it):
    return ev(t1, {"type": "item_completed", "started_at_ms": ms(T0 + t0),
                   "completed_at_ms": ms(T0 + t1), "item": it})


def usage(t, rid, out, reasoning=0):
    return rec(t, "token_usage_record", {
        "response_id": rid,
        "usage": {"output_tokens": out, "reasoning_output_tokens": reasoning}})


ENC = "gAAAAAB" + "x" * 60


def codex_parent(thread_child):
    return [
        rec(0, "session_meta", {"id": "parent-1", "source": "cli", "cwd": "C:/w"}),
        ev(0.1, {"type": "task_started"}),
        ri(0.2, {"type": "message", "role": "developer",
                 "content": [{"type": "input_text", "text": "<permissions instructions>"}]}),
        ri(0.3, {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "# AGENTS.md instructions\n규칙"}]}),
        rec(0.4, "turn_context", {"approval_policy": "never", "model": "gpt-x"}),
        ri(0.5, {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "calc.py 고치고 실행해"}]}),
        item(0.5, 0.5, {"type": "UserMessage", "content": [{"type": "text",
                                                            "text": "calc.py 고치고 실행해"}]}),
        ri(1.0, {"type": "reasoning", "summary": [], "encrypted_content": "zz"}),
        ri(2.0, {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "계획: 읽기 수정 실행"}]}),
        ri(3.0, {"type": "custom_tool_call", "name": "exec", "call_id": "c1",
                 "input": 'text(await tools.exec_command({cmd:"cat calc.py"}));\n'
                          'text(await tools.apply_patch("..."));'}),
        usage(3.1, "resp_1", 120, 40),
        item(3.2, 3.4, {"type": "CommandExecution", "process_id": "11",
                        "command": ["powershell.exe", "-Command", "cat calc.py"],
                        "status": "completed", "exit_code": 0,
                        "aggregated_output": "def add(a, b):\n    return a - b\n"}),
        item(3.5, 3.5, {"type": "FileChange", "status": "completed", "changes": {
            "C:/w/calc.py": {"type": "update", "move_path": None,
                             "unified_diff": "@@ -1,2 +1,2 @@\n def add(a, b):\r\n-    return a - b\r\n+    return a + b\r\n"},
            "C:/w/new.md": {"type": "add", "content": "새 파일 내용\n"},
            "C:/w/old.txt": {"type": "delete", "content": "x"}}}),
        ri(3.6, {"type": "custom_tool_call_output", "call_id": "c1", "output": [
            {"type": "input_text", "text": "Script completed\nWall time 0.4 seconds\nOutput:\n"},
            {"type": "input_text", "text": "def add(a, b):\n    return a - b\n"},
            {"type": "input_text", "text": "{}"}]}),
        # 배경 실행: 셀 결과에 session_id만, 실제 종료는 나중 항목
        ri(4.0, {"type": "custom_tool_call", "name": "exec", "call_id": "c2",
                 "input": 'text(await tools.exec_command({cmd:"python long.py",yield_time_ms:1000}));'}),
        usage(4.1, "resp_2", 30, 0),
        ri(5.2, {"type": "custom_tool_call_output", "call_id": "c2", "output": [
            {"type": "input_text", "text": "Script completed\nWall time 1.0 seconds\nOutput:\n"},
            {"type": "input_text", "text": '{"chunk_id":"a","session_id":77,"output":""}'}]}),
        item(4.2, 30.0, {"type": "CommandExecution", "process_id": "77",
                         "command": ["powershell.exe", "-Command", "python long.py"],
                         "status": "completed", "exit_code": 0,
                         "aggregated_output": "long done\n"}),
        # 서브에이전트(다중 에이전트 v2 — 지시문 암호화)
        ri(31.0, {"type": "function_call", "name": "spawn_agent", "call_id": "s1",
                  "arguments": json.dumps({"task_name": "count", "message": ENC})}),
        usage(31.1, "resp_3", 60, 0),
        item(31.2, 31.2, {"type": "SubAgentActivity", "kind": "started", "id": "s1",
                          "agent_thread_id": thread_child, "agent_path": "/root/count"}),
        ri(31.3, {"type": "function_call_output", "call_id": "s1",
                  "output": '{"task_name":"/root/count"}'}),
        ri(32.0, {"type": "function_call", "name": "wait_agent", "call_id": "w1",
                  "arguments": '{"timeout_ms":60000}'}),
        usage(32.1, "resp_4", 10, 0),
        item(40.0, 40.0, {"type": "SubAgentActivity", "kind": "completed",
                          "agent_thread_id": thread_child, "agent_path": "/root/count"}),
        ri(40.1, {"type": "function_call_output", "call_id": "w1",
                  "output": '{"message":"Wait completed.","timed_out":false}'}),
        ri(40.2, {"type": "agent_message", "author": "/root/count", "recipient": "/root",
                  "content": [{"type": "input_text", "text":
                               "Message Type: FINAL_ANSWER\nTask name: /root\nSender: /root/count\nPayload:\n37행"}]}),
        ri(41.0, {"type": "message", "role": "assistant",
                  "content": [{"type": "output_text", "text": "완료. 결과 37행."}]}),
        usage(41.1, "resp_5", 20, 0),
        ev(41.2, {"type": "task_complete", "duration_ms": 40900}),
    ]


def codex_child(thread_child):
    return [
        rec(31.2, "session_meta", {"id": thread_child, "agent_path": "/root/count",
                                    "subagent_history_start_ordinal": "2",
                                    "source": {"subagent": {"thread_spawn": {
                                        "parent_thread_id": "parent-1"}}}}),
        # 부모 대화 사본(fork) — 버린다
        ri(31.2, {"type": "message", "role": "user",
                  "content": [{"type": "input_text", "text": "calc.py 고치고 실행해"}]}),
        ri(31.3, {"type": "agent_message", "author": "/root", "recipient": "/root/count",
                  "content": [{"type": "input_text", "text":
                               "Message Type: NEW_TASK\nTask name: /root/count\nSender: /root\nPayload:\n"},
                              {"type": "encrypted_content", "encrypted_content": "q"}]}),
        ri(32.0, {"type": "reasoning", "summary": []}),
        ri(33.0, {"type": "message", "role": "assistant",
                  "content": [{"type": "output_text", "text": "37행"}]}),
        usage(33.1, "resp_c1", 15, 5),
        ev(33.2, {"type": "task_complete", "duration_ms": 2000}),
    ]


def guardian(parent):
    return [rec(1, "session_meta", {"id": "g-1", "source": {"subagent": {
        "other": "guardian", "thread_spawn": {"parent_thread_id": parent}}}})]


def write_jsonl(path, recs):
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def tool_uses(recs):
    return [b for r in recs if r["type"] == "assistant"
            for b in r["message"]["content"] if b["type"] == "tool_use"]


def results(recs):
    return {b["tool_use_id"]: (b, r) for r in recs if r["type"] == "user"
            for b in r["message"]["content"] if b.get("type") == "tool_result"}


class PatchTest(unittest.TestCase):
    def test_unified_diff_hunks(self):
        h = hunks_from_unified_diff("@@ -1,3 +1,3 @@\n a\r\n-b\r\n+c\r\n d\r\n")
        self.assertEqual(h, [("a\nb\nd", "a\nc\nd")])

    def test_apply_patch_ops(self):
        ops = parse_apply_patch(
            "*** Begin Patch\n*** Add File: n.md\n+x\n+y\n*** Update File: a.py\n"
            "*** Move to: b.py\n@@\n k\n-1\n+2\n*** Delete File: z.txt\n*** End Patch")
        tools = file_ops_to_tools(ops)
        self.assertEqual([t[0] for t in tools], ["Write", "Bash", "MultiEdit", "Bash"])
        self.assertEqual(tools[0][1]["content"], "x\ny")
        self.assertEqual(tools[2][1]["file_path"], "b.py")
        self.assertEqual(tools[2][1]["edits"], [{"old_string": "k\n1", "new_string": "k\n2"}])
        self.assertEqual(tools[3][1]["command"], 'rm "z.txt"')


class CodexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "sessions")
        os.makedirs(self.root)
        self.child = "child-1"
        self.parent_path = os.path.join(self.root, "rollout-p.jsonl")
        write_jsonl(self.parent_path, codex_parent(self.child))
        write_jsonl(os.path.join(self.root, "rollout-c.jsonl"), codex_child(self.child))
        write_jsonl(os.path.join(self.root, "rollout-g.jsonl"), guardian("parent-1"))
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conv(self):
        return convert(self.parent_path, out_dir=self.out)

    def test_detect(self):
        self.assertEqual(detect_format(self.parent_path), "codex")

    def test_user_and_meta(self):
        recs = load(self.conv()["main"])
        users = [r for r in recs if r["type"] == "user"
                 and r["message"]["content"][0]["type"] == "text"]
        real = [r for r in users if not r.get("isMeta")]
        self.assertEqual([r["message"]["content"][0]["text"] for r in real],
                         ["calc.py 고치고 실행해"])
        self.assertTrue(any(r.get("isMeta") for r in users))
        self.assertEqual(real[0]["permissionMode"], "bypassPermissions")

    def test_cell_items_become_tools(self):
        recs = load(self.conv()["main"])
        names = [b["name"] for b in tool_uses(recs)]
        for n in ("Bash", "MultiEdit", "Write", "Agent", "TaskOutput"):
            self.assertIn(n, names)
        res = results(recs)
        cat = next(b for b in tool_uses(recs) if b["input"].get("command") == "cat calc.py")
        self.assertIn("return a - b", res[cat["id"]][0]["content"])
        me = next(b for b in tool_uses(recs) if b["name"] == "MultiEdit")
        self.assertEqual(me["input"]["edits"][0]["new_string"],
                         "def add(a, b):\n    return a + b")
        self.assertTrue(any(b["input"].get("command") == 'rm "C:/w/old.txt"'
                            for b in tool_uses(recs)))

    def test_thinking_tokens_and_turn(self):
        recs = load(self.conv()["main"])
        first = next(r for r in recs if r["type"] == "assistant")
        self.assertEqual(first["message"]["content"][0]["type"], "thinking")
        self.assertEqual(first["message"]["usage"]["output_tokens_details"]["thinking_tokens"], 40)
        td = [r for r in recs if r.get("subtype") == "turn_duration"]
        self.assertEqual(td[0]["durationMs"], 40900)

    def test_background_exec(self):
        recs = load(self.conv()["main"])
        bg = next(b for b in tool_uses(recs) if b["input"].get("run_in_background"))
        b, r = results(recs)[bg["id"]]
        self.assertIn("running in background with ID: 77", b["content"])
        self.assertEqual(r["toolUseResult"]["backgroundTaskId"], "77")
        q = [r for r in recs if r["type"] == "queue-operation" and "<task-id>77<" in r["content"]]
        self.assertEqual(len(q), 1)
        from transcript_actual import parse_actions
        jobs = parse_actions(self.conv()["main"])["bg_exec_jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertAlmostEqual(jobs[0]["end"] - jobs[0]["start"], 25.8, places=1)

    def test_subagent_files_and_encrypted_estimate(self):
        res = self.conv()
        self.assertEqual(len(res["subagents"]), 1)      # guardian 제외
        sub = load(res["subagents"][0])
        self.assertTrue(all(r.get("isSidechain") for r in sub))
        texts = [r["message"]["content"][0]["text"] for r in sub
                 if r["type"] == "user" and r["message"]["content"][0]["type"] == "text"]
        self.assertNotIn("calc.py 고치고 실행해", texts)  # fork 사본은 버림
        main = load(res["main"])
        agent = next(b for b in tool_uses(main) if b["name"] == "Agent")
        n_parent = len(agent["input"]["prompt"].split())
        self.assertGreater(n_parent, 0)
        prompt = [r["message"]["content"][0]["text"] for r in sub
                  if r["type"] == "user" and not r.get("isMeta")
                  and r["message"]["content"][0]["type"] == "text"][0]
        self.assertEqual(len(prompt.split()), n_parent)   # 부모와 같은 추정 단어 수
        self.assertTrue(any("암호화" in n for n in res["notes"]))
        wait = next(b for b in tool_uses(main) if b["name"] == "TaskOutput")
        self.assertIn("37행", results(main)[wait["id"]][0]["content"])

    def test_imported_copy_excluded(self):
        # Codex가 Claude Code 세션을 가져와 자기 rollout으로 다시 쓴 사본 — 잴 일이 없다
        with open(os.path.join(self.tmp, "external_agent_session_imports.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"records": [{"imported_thread_id": "parent-1",
                                    "imported_at": T0 + 100}]}, fh)
        res = self.conv()
        self.assertIn("가져온 세션 사본", res["excluded"])
        self.assertIsNone(res["main"])
        with translate_session(self.parent_path, os.path.join(self.tmp, "work")) as t:
            self.assertIsNone(t.main)
            self.assertIn("가져온 세션 사본", t.excluded)

    def test_list_sessions_top_level_only(self):
        # 자식·guardian은 최상위 목록에서 빠지고 부모를 번역할 때 함께 들어간다
        rows = list_sessions("codex", root=self.tmp)
        self.assertEqual([os.path.normcase(r["src"]) for r in rows],
                         [os.path.normcase(self.parent_path)])
        self.assertEqual(rows[0]["agent"], "codex")

    def test_list_sessions_since_and_seen(self):
        # 스레드 목록이 없으면 기록의 마지막 사건 시각(T0+41.2) — 파일 수정 시각은 안 본다
        os.utime(self.parent_path, (T0 + 99999, T0 + 99999))
        rows = list_sessions("codex", root=self.tmp)
        self.assertAlmostEqual(rows[0]["updated_at"], T0 + 41.2, places=1)
        self.assertEqual(len(list_sessions("codex", root=self.tmp, since=T0)), 1)
        self.assertEqual(list_sessions("codex", root=self.tmp, since=T0 + 100), [])
        seen = {rows[0]["src"]: rows[0]["updated_at"]}   # 지난번에 처리한 뒤 안 바뀜
        self.assertEqual(list_sessions("codex", root=self.tmp, seen=seen), [])

    def test_list_sessions_uses_codex_thread_list(self):
        # Codex 스레드 목록(state_N.sqlite)의 갱신 시각이 있으면 그것을 쓴다
        import sqlite3
        tid = "11111111-2222-3333-4444-555555555555"
        named = os.path.join(self.root, f"rollout-2026-10-15T00-00-00-{tid}.jsonl")
        os.replace(self.parent_path, named)
        con = sqlite3.connect(os.path.join(self.tmp, "state_5.sqlite"))
        con.execute("create table threads (id text, updated_at_ms integer)")
        con.execute("insert into threads values (?, ?)", (tid, int((T0 + 700) * 1000)))
        con.commit()
        con.close()
        rows = list_sessions("codex", root=self.tmp)
        self.assertAlmostEqual(rows[0]["updated_at"], T0 + 700, places=1)
        seen = {rows[0]["src"]: T0 + 500}           # 그 뒤로 바뀜 → 다시 나온다
        self.assertEqual(len(list_sessions("codex", root=self.tmp, seen=seen)), 1)

    def test_translate_session_one_at_a_time(self):
        work = os.path.join(self.tmp, "state", "translate")
        with translate_session(self.parent_path, work) as t:
            folder = t.folder
            # 측정기가 원하는 모양: 폴더 안에 이 세션 파일만
            self.assertTrue(folder.startswith(work))
            self.assertEqual(os.path.dirname(t.main), folder)
            self.assertEqual(len(t.subagents), 1)
            self.assertTrue(t.subagents[0].startswith(os.path.join(folder, "")))
            # 파일 수정 시각 = 기록의 마지막 사건 시각 (측정기의 "진행 중" 제외에 안 걸리게)
            self.assertAlmostEqual(os.path.getmtime(t.main), T0 + 41.2, places=0)
            from record_actions_code_api_all_sessions import collect
            rows, n_excl, n_err = collect(folder)[:3]
            self.assertEqual((len(rows) + n_excl, n_err), (1, 0))   # 폴더째 넣어도 1세션
        self.assertFalse(os.path.exists(folder))      # 블록이 끝나면 지운다

    def test_translate_session_cleans_up_on_error(self):
        work = os.path.join(self.tmp, "work")
        with self.assertRaises(RuntimeError):
            with translate_session(self.parent_path, work) as t:
                folder = t.folder
                raise RuntimeError("측정 실패")
        self.assertFalse(os.path.exists(folder))

    def test_work_dir_required(self):
        with self.assertRaises(ValueError):
            convert(self.parent_path, None)
        with self.assertRaises(ValueError):
            translate_session(self.parent_path, None)

    def test_measure_end_to_end(self):
        # 번역 → 기존 측정기(변경 없음)에 Claude 기록으로 넣는다
        from record_actions_code_api import measure
        res = self.conv()
        r = measure(res["main"], subagent_paths=res["subagents"], force=True)
        self.assertEqual(r["agent"]["subagent_files"], 1)
        self.assertFalse(r["suspect_output_channel"])
        self.assertGreater(r["human"]["min"], 0)


def opencode_export(child_id):
    def tool(tid, name, inp, content, t0, t1, status="completed", meta=None):
        return {"type": "tool", "id": tid, "name": name,
                "state": {"status": status, "input": inp,
                          "content": [{"type": "text", "text": content}],
                          "metadata": meta or {}},
                "time": {"created": ms(T0 + t0), "ran": ms(T0 + t0) + 5,
                         "completed": ms(T0 + t1)}}
    return {"info": {"id": "ses_main"}, "messages": [
        {"id": "u1", "type": "user", "time": {"created": ms(T0)}, "text": "고쳐줘"},
        {"id": "a1", "type": "assistant", "time": {"created": ms(T0 + 1), "completed": ms(T0 + 9)},
         "tokens": {"reasoning": 30}, "model": {"id": "m"}, "content": [
             {"type": "reasoning", "text": "", "time": {"created": ms(T0 + 1.5), "completed": ms(T0 + 2)}},
             {"type": "text", "text": "읽을게요."},
             tool("t1", "read", {"path": "C:/w/a.py", "offset": 40, "limit": 21},
                  "Read file a.py, lines 40-60\n40: x", 3, 3.2),
             tool("t2", "edit", {"path": "C:/w/a.py", "oldString": "a - b", "newString": "a + b"},
                  "Edited", 4, 4.1),
             tool("t3", "shell", {"command": "python long.py", "background": True}, "", 5, 5.1,
                  meta={"status": "running", "shellID": "sh_1"}),
             tool("t4", "subagent", {"prompt": "행 수 세", "description": "count", "agent": "general"},
                  "<subagent>37</subagent>", 6, 8.5, meta={"sessionID": child_id}),
         ]},
        {"id": "s1", "type": "synthetic", "time": {"created": ms(T0 + 40)},
         "metadata": {"source": "shell", "shellID": "sh_1", "state": "completed"}, "text": "done"},
        {"id": "a2", "type": "assistant", "time": {"created": ms(T0 + 41), "completed": ms(T0 + 42)},
         "tokens": {}, "error": {"type": "aborted", "message": "Aborted"}, "content": [
             {"type": "text", "text": "중단"}]},
        {"id": "i1", "type": "idle", "time": {"created": ms(T0 + 43)}},
    ]}


class OpenCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "ses_main.json")
        with open(self.src, "w", encoding="utf-8") as fh:
            json.dump(opencode_export("ses_child"), fh, ensure_ascii=False)
        child = {"info": {"id": "ses_child"}, "messages": [
            {"id": "cu", "type": "user", "time": {"created": ms(T0 + 6.1)}, "text": "행 수 세"},
            {"id": "ca", "type": "assistant", "time": {"created": ms(T0 + 7), "completed": ms(T0 + 8)},
             "tokens": {"reasoning": 3}, "content": [{"type": "text", "text": "37"}]}]}
        with open(os.path.join(self.tmp, "ses_child.json"), "w", encoding="utf-8") as fh:
            json.dump(child, fh, ensure_ascii=False)
        # 셸 출력 파일 — 실제 종료 시각(25초 뒤) 근거
        self.shell = os.path.join(self.tmp, "shell", "proj")
        os.makedirs(self.shell)
        out = os.path.join(self.shell, "sh_1.out")
        open(out, "w").write("done\n")
        os.utime(out, (T0 + 30, T0 + 30))
        self.old_shell = opencode_translator.SHELL_DIR
        opencode_translator.SHELL_DIR = os.path.join(self.tmp, "shell")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        opencode_translator.SHELL_DIR = self.old_shell
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conv(self):
        return convert(self.src, out_dir=self.out,
                       opencode_db=os.path.join(self.tmp, "none.db"))

    def test_detect(self):
        self.assertEqual(detect_format(self.src), "opencode")
        self.assertEqual(detect_format("opencode:ses_x"), "opencode")

    def test_tools(self):
        recs = load(self.conv()["main"])
        uses = {b["name"]: b for b in tool_uses(recs)}
        self.assertEqual(uses["Read"]["input"], {"file_path": "C:/w/a.py", "offset": 40, "limit": 21})
        self.assertEqual(uses["Edit"]["input"]["new_string"], "a + b")
        self.assertTrue(uses["Bash"]["input"]["run_in_background"])
        b, r = results(recs)[uses["Agent"]["id"]]
        self.assertEqual(r["toolUseResult"]["agentId"], "ses_child")
        self.assertEqual(r["toolUseResult"]["totalDurationMs"], 2495)

    def test_background_and_interrupt_and_turn(self):
        recs = load(self.conv()["main"])
        q = [r for r in recs if r["type"] == "queue-operation"]
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["timestamp"], iso(T0 + 30))
        texts = [r["message"]["content"][0].get("text", "") for r in recs if r["type"] == "user"]
        self.assertTrue(any(t.startswith("<task-notification>") for t in texts))
        self.assertIn("[Request interrupted by user]", texts)
        td = [r for r in recs if r.get("subtype") == "turn_duration"]
        self.assertEqual(td[0]["durationMs"], 43000)
        from transcript_actual import parse_actions
        jobs = parse_actions(self.conv()["main"])["bg_exec_jobs"]
        self.assertAlmostEqual(jobs[0]["end"] - jobs[0]["start"], 25.0, places=1)

    def test_child_from_sibling_export(self):
        res = self.conv()
        self.assertEqual(len(res["subagents"]), 1)
        sub = load(res["subagents"][0])
        self.assertTrue(all(r.get("isSidechain") for r in sub))

    def test_measure_end_to_end(self):
        from record_actions_code_api import measure
        res = self.conv()
        r = measure(res["main"], subagent_paths=res["subagents"], force=True)
        self.assertEqual(r["agent"]["subagent_files"], 1)
        self.assertGreater(r["human"]["min"], 0)


class ClaudePassThroughTest(unittest.TestCase):
    def test_claude_unchanged(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.jsonl")
            write_jsonl(p, [{"type": "user", "timestamp": iso(T0),
                             "message": {"role": "user", "content": "hi"}}])
            self.assertEqual(detect_format(p), "claude")
            res = convert(p, os.path.join(tmp, "out"))
            self.assertEqual(res["main"], p)              # 원본 경로 그대로, 번역 안 함
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class LocationTest(unittest.TestCase):
    """경로 찾기 — URI 인코딩, 환경변수, 사람이 정한 위치가 없으면 바로 오류."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = {k: os.environ.get(k) for k in ("OPENCODE_DB", "XDG_DATA_HOME", "CODEX_HOME")}
        for k in self.env:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_db(self, folder):
        import sqlite3
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, "opencode.db")
        con = sqlite3.connect(p)
        con.execute("create table session_v2 (id text, parent_id text, time_updated integer)")
        con.execute("insert into session_v2 values ('ses_a', null, ?)", (int(T0 * 1000),))
        con.commit()
        con.close()
        return p

    def test_uri_encodes_special_chars(self):
        u = ro_uri(os.path.join(self.tmp, "a?b#c d", "opencode.db"))
        self.assertTrue(u.startswith("file:///"))
        body = u[:-len("?mode=ro")]
        self.assertTrue(u.endswith("?mode=ro"))
        for raw, enc in (("?", "%3F"), ("#", "%23"), (" ", "%20")):
            self.assertIn(enc, body)
            self.assertNotIn(raw, body)

    def test_db_in_folder_with_hash_opens(self):
        db = self.make_db(os.path.join(self.tmp, "x#y z"))   # Windows는 ?를 이름에 못 쓴다
        rows = list_sessions("opencode", root=db)
        self.assertEqual([r["src"] for r in rows], ["opencode:ses_a"])

    def test_opencode_db_env_and_xdg(self):
        db = self.make_db(os.path.join(self.tmp, "custom"))
        os.environ["OPENCODE_DB"] = db
        self.assertEqual(find_opencode_db(), str(Path(db).resolve()))
        os.environ.pop("OPENCODE_DB")
        xdg_db = self.make_db(os.path.join(self.tmp, "xdg", "opencode"))
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "xdg")
        self.assertEqual(find_opencode_db(), str(Path(xdg_db).resolve()))
        self.assertEqual(find_opencode_db(db), str(Path(db).resolve()))   # 인자가 먼저

    def test_given_location_missing_is_error(self):
        os.environ["OPENCODE_DB"] = os.path.join(self.tmp, "없음.db")
        with self.assertRaises(FileNotFoundError):
            find_opencode_db()
        with self.assertRaises(FileNotFoundError):
            find_opencode_db(os.path.join(self.tmp, "없음2.db"))
        os.environ["CODEX_HOME"] = os.path.join(self.tmp, "no-codex")
        with self.assertRaises(FileNotFoundError):
            find_codex_home()
        os.environ.pop("CODEX_HOME")
        self.assertEqual(find_codex_home(self.tmp), str(Path(self.tmp).resolve()))


if __name__ == "__main__":
    unittest.main()
