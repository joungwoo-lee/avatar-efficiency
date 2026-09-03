"""python test_condense.py            # 합성 jsonl 단위 테스트
   python test_condense.py --real     # ~/.claude/projects 실파일로 감량률 출력"""
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from condense import condense, render, estimate_tokens  # noqa: E402
from classify import build_prompt, _normalize  # noqa: E402


def _rec(rtype, content, ts="2026-01-01T00:00:00Z"):
    return json.dumps({"type": rtype, "timestamp": ts, "message": {"role": rtype, "content": content}}, ensure_ascii=False)


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
    assert c["stats"]["assistant_cap"] is None and not c["stats"]["over_budget"]
    # 예산 초과 → 에이전트 캡 축소, 사용자·final 불변
    c2 = condense(p, budget_tokens=50)
    assert c2["stats"]["assistant_cap"] == 500 and c2["stats"]["over_budget"]
    assert c2["user"] == c["user"] and c2["final"] == c["final"]
    prompt = build_prompt(c, ["sw개발", "sw검증", "hw설계"])
    assert "- hw설계" in prompt and "## FINAL ANSWER" in prompt
    os.remove(p)
    print("test_basic OK")


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


if __name__ == "__main__":
    if "--real" in sys.argv:
        real()
    else:
        test_basic()
        test_normalize()
