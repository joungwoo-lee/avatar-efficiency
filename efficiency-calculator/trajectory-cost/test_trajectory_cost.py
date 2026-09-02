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


def test_synthetic_excluded_from_counts_any_id_format():
    """<synthetic> 레코드: message.id 가 UUID 든 '<synthetic>' 문자열이든 호출 수에서 제외.
    by_provider['free'] 에만 남고 달러는 불변. 구버전 포맷(cache_creation 딕트 없음) 혼합."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sid = "aaaaaaaa-0000-0000-0000-000000000001"
        real = _rec("m1", "claude-opus-5", out=1_000_000)          # $25
        syn_uuid = _rec("11f89a78-d2a6-4c3e-9a1b-000000000001", "<synthetic>")
        syn_uuid["version"] = "2.1.152"
        del syn_uuid["message"]["usage"]["cache_creation"]           # 구버전 스키마
        syn_uuid["message"]["usage"]["cache_creation_input_tokens"] = 0
        syn_lit = _rec("<synthetic>", "<synthetic>")
        syn_lit["version"] = "2.1.252"
        real["version"] = "2.1.226"
        _write(root / "C--proj", sid + ".jsonl", [real, syn_uuid, syn_lit, syn_lit])
        d = tc.session_cost(sid, projects_root=root)
    assert d["total"]["calls"] == 1, d["total"]
    assert d["main_agent"]["calls"] == 1
    assert "<synthetic>" not in d["by_model"], d["by_model"]
    assert d["by_provider"]["free"]["calls"] == 2       # uuid 1 + 문자열 id 는 dedupe 로 1
    assert d["by_provider"]["free"]["cost_usd"] == 0.0
    assert abs(d["trajectory_cost_usd"] - 25.0) < 1e-6
    assert d["min_version"] == "2.1.152" and d["max_version"] == "2.1.252", (d["min_version"], d["max_version"])
    print("ok synthetic_excluded_from_counts_any_id_format")


def test_glm_is_onprem():
    assert tc.classify_model("GLM-5.2-FP8", RATES) == "onprem"
    assert tc.classify_model("zai-org/glm-4.5", RATES) == "onprem"
    print("ok glm_is_onprem")


def test_cache_creation_fallback_when_dict_all_zero():
    """cache_creation 딕트가 있으나 전부 0 이고 최상위 cache_creation_input_tokens 만 있는 경우 -> 5m 로 계상."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sid = "bbbbbbbb-0000-0000-0000-000000000001"
        r = _rec("c1", "claude-opus-5")
        r["message"]["usage"]["cache_creation_input_tokens"] = 1_000_000
        r["message"]["usage"]["cache_creation"] = {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}
        old = _rec("c2", "claude-opus-5")
        old["message"]["usage"]["cache_creation_input_tokens"] = 1_000_000
        del old["message"]["usage"]["cache_creation"]
        _write(root / "C--proj", sid + ".jsonl", [r, old])
        d = tc.session_cost(sid, projects_root=root)
    assert d["total"]["cache_write_5m"] == 2_000_000, d["total"]
    assert abs(d["trajectory_cost_usd"] - 12.5) < 1e-6, d["trajectory_cost_usd"]   # 6.25 x 2
    print("ok cache_creation_fallback_when_dict_all_zero")


if __name__ == "__main__":
    test_price_math()
    test_date_suffix_and_fast()
    test_onprem_is_free()
    test_dedupe_streaming_repeats()
    test_session_with_subagents_and_onprem()
    test_unknown_model_flagged()
    test_synthetic_excluded_from_counts_any_id_format()
    test_glm_is_onprem()
    test_cache_creation_fallback_when_dict_all_zero()
    print("all tests passed")
