# -*- coding: utf-8 -*-
"""오프라인 단위테스트(mock LLM) + --live 시 cursor-proxy 실호출 테스트.

    python test_estimator.py          # mock만
    python test_estimator.py --live   # mock + 프록시 라이브
"""
import json
import sys
from pathlib import Path

from estimator import EffortEstimator, DEFAULT_RATES_PATH

_HERE = Path(__file__).resolve().parent


class MockLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(self, prompt, max_tokens):
        self.calls += 1
        return self.responses.pop(0)


GOOD = {
    "human": [
        {"primitive": "read", "count": 800},
        {"primitive": "draft", "count": 200},
        {"primitive": "verify", "count": 2},
    ],
    "agent": [
        {"primitive": "read", "count": 800},
        {"primitive": "draft", "count": 200},
        {"primitive": "verify", "count": 2},
    ],
    "hitl": [
        {"primitive": "instruct", "count": 1},
        {"primitive": "review", "count": 200},
        {"primitive": "approve", "count": 1},
    ],
    "ai_io": {"input_words": 1000, "output_words": 300},
    "rationale": "test",
}


def approx(a, b, eps=0.01):
    assert abs(a - b) < eps, f"{a} != {b}"


def test_math():
    est = EffortEstimator(MockLLM([GOOD]))
    r = est.estimate("dummy spec")
    # human: 800*0.005 + 200*0.05 + 2*3.0 = 4 + 10 + 6 = 20
    approx(r["human_only"]["minutes"], 20.0)
    # agent traj: 800*0.0005 + 200*0.002 + 2*0.5 = 0.4 + 0.4 + 1.0 = 1.8
    # ai_io: 1000*0.00002 + 300*0.0015 = 0.02 + 0.45 = 0.47
    approx(r["agent"]["machine"]["minutes"], 2.27)
    # hitl: 1*3.0 + 200*0.006 + 1*1.0 = 5.2
    approx(r["agent"]["hitl"]["minutes"], 5.2)
    approx(r["agent"]["minutes"], 7.47)  # machine + hitl 합산 헤드라인
    approx(r["metrics"]["human_labor_leverage"], 20.0 / 5.2, 0.01)
    print("ok test_math")


def test_retry_on_bad_schema():
    bad = {"nonsense": True}
    mock = MockLLM([bad, GOOD])
    est = EffortEstimator(mock)
    r = est.estimate("dummy")
    assert mock.calls == 2
    assert any("재시도" in n for n in r["confidence_notes"])
    approx(r["human_only"]["minutes"], 20.0)
    print("ok test_retry_on_bad_schema")


def test_unknown_primitive_dropped():
    tainted = json.loads(json.dumps(GOOD))
    tainted["human"].append({"primitive": "teleport", "count": 99})
    est = EffortEstimator(MockLLM([tainted]))
    r = est.estimate("dummy")
    approx(r["human_only"]["minutes"], 20.0)  # teleport 무시
    assert any("teleport" in n for n in r["confidence_notes"])
    print("ok test_unknown_primitive_dropped")


def test_empty_hitl_warns():
    no_hitl = json.loads(json.dumps(GOOD))
    no_hitl["hitl"] = []
    est = EffortEstimator(MockLLM([no_hitl]))
    r = est.estimate("dummy")
    assert r["agent"]["hitl"]["minutes"] == 0
    assert r["metrics"]["human_labor_leverage"] is None
    assert any("hitl" in n for n in r["confidence_notes"])
    print("ok test_empty_hitl_warns")


def test_double_failure_raises():
    est = EffortEstimator(MockLLM([{"x": 1}, {"y": 2}]))
    try:
        est.estimate("dummy")
    except ValueError:
        print("ok test_double_failure_raises")
        return
    raise AssertionError("ValueError 미발생")


def test_rates_not_in_prompt():
    from estimator import build_prompt
    rates = json.loads(DEFAULT_RATES_PATH.read_text(encoding="utf-8"))
    p = build_prompt("spec", rates)
    assert "min_per_unit" not in p
    for card in ("human", "agent", "hitl"):
        for spec in rates[card].values():
            assert f": {spec['min_per_unit']} min" not in p
    assert "2.0" not in p and "0.005" not in p  # 대표 요율값 미노출
    print("ok test_rates_not_in_prompt")


def test_live():
    from onprem_llm_sim import OnpremLLM
    spec = (_HERE / "examples" / "sample_spec.txt").read_text(encoding="utf-8")
    est = EffortEstimator(OnpremLLM())
    r = est.estimate(spec)
    assert r["human_only"]["minutes"] > 0
    assert r["agent"]["machine"]["minutes"] > 0
    assert r["agent"]["hitl"]["minutes"] > 0, "라이브 응답에 hitl 없음"
    assert r["human_only"]["minutes"] > r["agent"]["hitl"]["minutes"], "leverage < 1 — 수량 이상"
    print("ok test_live")
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    test_math()
    test_retry_on_bad_schema()
    test_unknown_primitive_dropped()
    test_empty_hitl_warns()
    test_double_failure_raises()
    test_rates_not_in_prompt()
    if "--live" in sys.argv:
        test_live()
    print("all tests passed")
