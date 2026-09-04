"""python test_condense.py            # 합성 jsonl 단위 테스트
   python test_condense.py --real     # ~/.claude/projects 실파일로 감량률 출력"""
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from condense import condense, render, estimate_tokens, parse_time  # noqa: E402
from classify import build_prompt, _normalize  # noqa: E402


def _rec(rtype, content, ts="2026-01-01T00:00:00Z"):
    d = {"type": rtype, "message": {"role": rtype, "content": content}}
    if ts:
        d["timestamp"] = ts
    return json.dumps(d, ensure_ascii=False)


def _write(lines):
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


def test_basic():
    big_code = "x = 1\n" * 500
    lines = [
        _rec("user", "너 모델 뭐야"),                                    # 10자 미만 → 제거
        _rec("user", "<system-reminder>비밀</system-reminder>rtl 모듈 검증 테스트벤치 만들어줘"),
        _rec("assistant", [{"type": "text", "text": "계획: uart_tb.sv 작성.\n```systemverilog\n" + big_code + "```\n끝."},
                           {"type": "tool_use", "name": "Write", "input": {"file_path": "C:\\Users\\joung\\proj\\rtl\\uart_tb.sv", "content": big_code}}]),
        _rec("user", [{"type": "tool_result", "content": "파일 결과 " * 1000}]),  # 툴 결과 제외
        _rec("user", "[Request interrupted by user]"),
        _rec("user", "[Image: original 100x100]"),
        _rec("user", "돌려라"),
        _rec("user", "그리고 커버리지 리포트도 뽑아줘 " + "긴 붙여넣기 " * 200),   # 300자 캡
        _rec("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": "cd C:/Users/joung/proj && vsim -c uart_tb"}},
                           {"type": "text", "text": "완료. " + "커버리지 92% 달성, 미커버 분기 3개는 리셋 경로. " * 10}]),
    ]
    p = _write(lines)
    c = condense(p)
    assert len(c["user"]) == 2, c["user"]
    assert c["user"][0].startswith("rtl 모듈"), c["user"][0]
    assert "비밀" not in c["user"][0]
    assert len(c["user"][1]) == 300
    assert len(c["assistant"]) == 2
    assert "x = 1" not in c["assistant"][0] and "[code omitted]" in c["assistant"][0]
    assert "파일 결과" not in render(c)
    assert c["meta"]["tools"] == {"Write": 1, "Bash": 1}
    assert c["meta"]["exts"] == {"sv": 1}
    assert "proj" in c["meta"]["dirs"]
    assert c["final"].startswith("완료.")
    assert c["source"]["transcript_path"] == str(Path(p).resolve()) and c["source"]["session_id"] == Path(p).stem
    assert c["source"]["first_ts"] == "2026-01-01T00:00:00Z"
    assert c["stats"]["assistant_cap"] is None and not c["stats"]["over_budget"]
    # 예산 초과 → 에이전트 캡 축소, 사용자·final 불변
    c2 = condense(p, budget_tokens=50)
    assert c2["stats"]["assistant_cap"] == 500 and c2["stats"]["over_budget"]
    assert c2["user"] == c["user"] and c2["final"] == c["final"]
    prompt = build_prompt(c, ["sw개발", "sw검증", "hw설계"])
    assert "- hw설계" in prompt and "## FINAL ANSWER" in prompt
    os.remove(p)
    print("test_basic OK")


def test_window():
    lines = [
        _rec("user", "첫 번째 업무: 파서 버그 고쳐줘", ts="2026-09-03T02:00:00Z"),
        _rec("assistant", [{"type": "text", "text": "파서 고침. " * 40},
                           {"type": "tool_use", "name": "Edit", "input": {"file_path": "C:/p/src/parser.py"}}], ts="2026-09-03T02:10:00Z"),
        _rec("assistant", [{"type": "text", "text": "시각 없는 레코드는 직전 시각 상속 " * 20}], ts=None),
        _rec("user", "두 번째 업무: 회로도 검토해줘", ts="2026-09-03T05:00:00Z"),
        _rec("assistant", [{"type": "text", "text": "회로도 검토 완료. " * 40},
                           {"type": "tool_use", "name": "Read", "input": {"file_path": "C:/p/hw/top.sch"}}], ts="2026-09-03T05:10:00Z"),
    ]
    p = _write(lines)
    full = condense(p)
    a = condense(p, window=("2026-09-03T02:00:00Z", "2026-09-03T03:00:00Z"))
    b = condense(p, window=(parse_time("2026-09-03T04:00:00Z"), None))
    assert full["meta"]["window"] is None and full["meta"]["exts"] == {"py": 1, "sch": 1}
    assert a["user"] == ["첫 번째 업무: 파서 버그 고쳐줘"] and a["meta"]["exts"] == {"py": 1}
    assert len(a["assistant"]) == 2  # 시각 없는 레코드 → 직전 시각으로 구간 안
    assert a["final"].startswith("시각 없는")
    assert b["user"] == ["두 번째 업무: 회로도 검토해줘"] and b["meta"]["exts"] == {"sch": 1}
    assert b["meta"]["records_in_window"] == 2 and b["meta"]["records"] == 5
    assert b["source"]["first_ts"] == "2026-09-03T02:00:00Z" and b["source"]["last_ts"] == "2026-09-03T05:10:00Z"  # 구간 무관 전체
    assert "window:" in render(a)
    try:
        condense(p, window=(10, 5))
        assert False
    except ValueError:
        pass
    os.remove(p)
    print("test_window OK")


def test_normalize():
    r = _normalize({"shares": {"sw개발": 30, "hw설계": 60, "없는펑션": 10}, "primary": "없는펑션"}, ["sw개발", "hw설계"])
    assert r["shares"] == {"sw개발": 33, "hw설계": 67} and r["primary"] == "hw설계"
    r = _normalize({"shares": {"sw개발": "70", "기타": 30}}, ["sw개발"])
    assert r["primary"] == "sw개발"
    print("test_normalize OK")


def real():
    root = Path.home() / ".claude" / "projects"
    files = sorted(glob.glob(str(root / "*" / "*.jsonl")), key=os.path.getsize, reverse=True)
    files = [f for f in files if os.path.getsize(f) > 200_000]
    files = files[:: max(1, len(files) // 8)][:8]
    print(f"{'file':8} {'orig':>9} {'ratio':>7} {'chars':>7} {'~tokens':>8} cap over")
    for f in files:
        c = condense(f)
        s = c["stats"]
        print(f"{Path(f).stem[-6:]:8} {s['orig_bytes']/1e6:7.2f}MB {s['ratio']*100:6.2f}% {s['out_chars']//1000:5d}k {s['est_tokens']//1000:6d}k {s['assistant_cap']} {s['over_budget']}")


def test_summarize_match():
    from summarize_match import summarize_match, inspect_claude, child_env, _normalize as _nm, save_result, load_results, result_filename
    # PID 검사: 자기 자신(python)으로 PEB/proc 읽기 검증
    info = inspect_claude(os.getpid())
    assert info["cwd"].rstrip("\/").lower() == os.getcwd().rstrip("\/").lower(), (info["cwd"], os.getcwd())
    assert "PATH" in info["env"] or "Path" in info["env"]
    assert info["config_dir"]
    e = child_env({"CLAUDECODE": "1", "ANTHROPIC_MODEL": "opus", "CLAUDE_CONFIG_DIR": "X", "PATH": "p"})
    assert "CLAUDECODE" not in e and "ANTHROPIC_MODEL" not in e
    assert e["CLAUDE_CONFIG_DIR"] == "X" and e["DISABLE_PROMPT_CACHING"] == "1"
    # 매칭 정규화
    org = json.load(open(Path(__file__).parent / "functions.example.json", encoding="utf-8"))
    r = _nm({"summary": "s", "functions": {"sw개발": 50, "hw검증": 30, "엉뚱": 20}, "primary": "엉뚱",
             "products": ["UART IP", "없는제품"]}, org)
    assert r["functions"] == {"sw개발": 62, "hw검증": 38} and r["primary"] == "sw개발" and r["products"] == ["UART IP"]
    # 전체 흐름(runner 주입, CLI 미호출)
    lines = [_rec("user", "uart 테스트벤치 만들어서 시뮬 돌려줘", ts="2026-09-03T02:00:00Z"),
             _rec("assistant", [{"type": "text", "text": "uart_tb.sv 작성하고 시뮬 통과. " * 20},
                                {"type": "tool_use", "name": "Write", "input": {"file_path": "C:/p/rtl/uart_tb.sv"}}], ts="2026-09-03T02:10:00Z")]
    lines = [l.replace('{"type": "user"', '{"sessionId": "sess-123", "cwd": "C:/p", "type": "user"', 1) for l in lines]
    p = _write(lines)
    cpath = p + ".c.json"
    json.dump(condense(p, window=("2026-09-03T02:00:00Z", "2026-09-03T03:00:00Z")), open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
    seen = {}
    def runner(prompt):
        seen["prompt"] = prompt
        return '{"summary":"UART 테스트벤치 작성·시뮬","functions":{"hw검증":80,"hw설계":20},"primary":"hw검증","products":["UART IP"],"evidence":"exts sv"}'
    r = summarize_match(os.getpid(), cpath, Path(__file__).parent / "functions.example.json", runner=runner)
    assert "- hw검증:" in seen["prompt"] and "uart 테스트벤치" in seen["prompt"] and "## META" in seen["prompt"]
    assert r["primary"] == "hw검증" and r["products"] == ["UART IP"] and r["meta"]["model"] == "haiku"
    assert r["meta"]["no_session_persistence"] and r["meta"]["prompt_caching_disabled"]
    # 출처·구간이 결과에 박힘 → 다른 곳에서 가져갈 수 있음
    assert r["schema"] == "function-classifier/result@1" and r["generated_at"]
    assert r["source"]["session_id"] == "sess-123" and r["source"]["transcript_path"] == str(Path(p).resolve())
    assert r["source"]["project_cwd"] == "C:/p" and r["source"]["first_ts"] == "2026-09-03T02:00:00Z"
    assert r["window"]["start_iso"].startswith("2026-09-03T02:00:00") and r["window"]["records_in_window"] == 2
    assert result_filename(r).startswith("sess-123__") and result_filename(r).endswith(".json")
    d = tempfile.mkdtemp()
    saved = save_result(r, out_dir=d)
    assert Path(saved).exists() and (Path(d) / "index.jsonl").exists()
    back = json.load(open(saved, encoding="utf-8"))
    assert back["source"]["session_id"] == "sess-123" and back["primary"] == "hw검증"
    rows = load_results(out_dir=d, session_id="sess-123")
    assert len(rows) == 1 and rows[0]["file"] == str(Path(saved).resolve()) and rows[0]["primary"] == "hw검증"
    assert load_results(out_dir=d, session_id="nope") == []
    assert len(load_results(out_dir=d, transcript_path=p)) == 1
    os.remove(p); os.remove(cpath)
    print("test_summarize_match OK")


if __name__ == "__main__":
    if "--real" in sys.argv:
        real()
    else:
        test_basic()
        test_window()
        test_normalize()
        test_summarize_match()
