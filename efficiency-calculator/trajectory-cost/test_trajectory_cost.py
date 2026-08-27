"""trajectory_cost 단위 테스트. 실행: python test_trajectory_cost.py"""

import json
import tempfile
from pathlib import Path

import trajectory_cost as tc

RATES = tc.load_rates()


def _rec(msg_id, model, *, inp=0, w5=0, w1=0, read=0, out=0,
         agent_id=None, agent_type=None, sidechain=False, speed="standard"):
    return {
        "type": "assistant",
        "uuid": msg_id + "-u",
        "requestId": "req_" + msg_id,
        "isSidechain": sidechain,
        **({"agentId": agent_id, "attributionAgent": agent_type} if agent_id else {}),
        "message": {
            "id": msg_id,
            "model": model,
            "usage": {
                "input_tokens": inp,
                "cache_creation_input_tokens": w5 + w1,
                "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1},
                "cache_read_input_tokens": read,
                "output_tokens": out,
                "speed": speed,
            },
        },
    }


def _write(dirpath: Path, name: str, records) -> Path:
    p = dirpath / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return p


def test_price_math():
    """1M input + 1M output on opus-5 = $5 + $25."""
    c = tc.Call("m", None, "claude-opus-5", None, None, False, "standard",
                input_tokens=1_000_000, output_tokens=1_000_000)
    usd, prov = tc.call_cost(c, RATES)
    assert prov == "api" and abs(usd - 30.0) < 1e-9, usd

    # 캐시: write5m 1.25x, write1h 2x, read 0.1x (opus-5 input $5/MTok)
    c = tc.Call("m", None, "claude-opus-5", None, None, False, "standard",
                cache_write_5m=1_000_000, cache_write_1h=1_000_000, cache_read=1_000_000)
    usd, _ = tc.call_cost(c, RATES)
    assert abs(usd - (6.25 + 10.0 + 0.5)) < 1e-9, usd
    print("ok price_math")


def test_date_suffix_and_fast():
    c = tc.Call("m", None, "claude-haiku-4-5-20251001", None, None, False, "standard",
                input_tokens=1_000_000)
    usd, prov = tc.call_cost(c, RATES)
    assert prov == "api" and abs(usd - 1.0) < 1e-9, usd

    c = tc.Call("m", None, "claude-opus-5", None, None, False, "fast", output_tokens=1_000_000)
    usd, _ = tc.call_cost(c, RATES)
    assert abs(usd - 50.0) < 1e-9, usd  # fast mode 프리미엄
    print("ok date_suffix_and_fast")


def test_onprem_is_free():
    for m in ["onprem/qwen3-32b", "llama-3.3-70b", "ollama/gemma3", "EXAONE-4.0"]:
        c = tc.Call("m", None, m, None, None, False, "standard",
                    input_tokens=5_000_000, output_tokens=5_000_000)
        usd, prov = tc.call_cost(c, RATES)
        assert prov == "onprem" and usd == 0.0, (m, prov, usd)

    # 명시 등록으로도 온프렘 지정 가능
    c = tc.Call("m", None, "our-internal-7b", None, None, False, "standard", output_tokens=1_000_000)
    usd, prov = tc.call_cost(c, RATES, onprem_models=["our-internal-7b"])
    assert prov == "onprem" and usd == 0.0
    print("ok onprem_is_free")


def test_dedupe_streaming_repeats():
    calls = [tc.Call("same", None, "claude-opus-5", None, None, False, "standard", output_tokens=100)
             for _ in range(6)]
    calls.append(tc.Call("same", None, "claude-opus-5", None, None, False, "standard", output_tokens=300))
    assert len(tc.dedupe(calls)) == 1
    assert tc.dedupe(calls)[0].output_tokens == 300
    print("ok dedupe_streaming_repeats")


def test_session_with_subagents_and_onprem():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sid = "11111111-2222-3333-4444-555555555555"
        proj = root / "C--proj"
        # 부모: opus-5 1M out = $25, 같은 호출이 3번 중복 기록됨
        parent = [_rec("p1", "claude-opus-5", out=1_000_000)] * 3
        # 온프렘 호출 (부모)
        parent.append(_rec("p2", "onprem/qwen3-32b", inp=2_000_000, out=2_000_000))
        _write(proj, sid + ".jsonl", parent)
        # 서브에이전트: sonnet-5 1M out = $10
        _write(proj / sid / "subagents", "agent-abc.jsonl",
               [_rec("s1", "claude-sonnet-5", out=1_000_000,
                     agent_id="abc", agent_type="general-purpose", sidechain=True)])

        d = tc.session_cost(sid, projects_root=root)

    assert d["subagent_files"] == 1
    assert abs(d["trajectory_cost_usd"] - 35.0) < 1e-6, d["trajectory_cost_usd"]
    assert abs(d["main_agent"]["cost_usd"] - 25.0) < 1e-6
    assert abs(d["subagents"]["cost_usd"] - 10.0) < 1e-6
    assert d["onprem"]["cost_usd"] == 0.0
    assert d["onprem"]["total_tokens"] == 4_000_000       # 토큰은 세되 비용은 0
    assert "general-purpose:abc" in d["by_agent"]
    print("ok session_with_subagents_and_onprem")


def test_unknown_model_flagged():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sid = "99999999-0000-0000-0000-000000000000"
        _write(root / "C--proj", sid + ".jsonl", [_rec("x1", "gpt-9-turbo", out=1000)])
        d = tc.session_cost(sid, projects_root=root)
    assert d["trajectory_cost_usd"] == 0.0
    assert any("gpt-9-turbo" in w for w in d["warnings"])
    print("ok unknown_model_flagged")


if __name__ == "__main__":
    test_price_math()
    test_date_suffix_and_fast()
    test_onprem_is_free()
    test_dedupe_streaming_repeats()
    test_session_with_subagents_and_onprem()
    test_unknown_model_flagged()
    print("all tests passed")
