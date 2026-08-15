# -*- coding: utf-8 -*-
"""세션 경로 기반 human w/o AI 산정 (분자의 대안 방식).

요구사항 기반(estimator.py — Work Unit Catalog × Monte Carlo)과 달리,
트랜스크립트에 기록된 **실제 작업 경로를 사람이 그대로 수행했다면**으로 보고
동작 count × human 요율(rates.json "human" 카드)을 곱한다.

  human_path_min = tool 실행수   × human.execute (2.0분/회)
                 + 읽은 단어수   × human.read    (0.005분/단어)
                 + 산출 단어수   × human.draft   (0.05분/단어)

특성 비교:
  - 요구사항 기반: "그 산출물을 만들려면 사람은 무슨 일을 얼마나" — 경로 무관,
    LLM 2회, Work Unit 자(수십 분/건)
  - 세션 경로 기반: "AI가 실제 밟은 경로를 사람 속도로" — LLM 미사용·결정론적,
    primitive 자. AI의 시행착오·과잉 탐색까지 사람 노동으로 환산되는 상방 편향과,
    사람이라면 안 거쳤을 경로 단축을 무시하는 양방향 편향이 있음.

동작 count는 ../agent-effort/transcript_actual.parse_actions를 재사용한다
(같은 트랜스크립트 파서 — 요율만 human 카드로 다르게 곱는 것).
"""
import glob
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AGENT_DIR = _HERE.parent / "agent-effort"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from transcript_actual import parse_actions  # noqa: E402
from agent_effort import load_rates, DEFAULT_RATES_PATH  # noqa: E402


def human_path_minutes(counts, rates=None):
    """동작 카운트 × human 요율 → 분.

    반환: {human_path_min, breakdown{execute,read,draft}, counts}
    """
    h = (rates or load_rates())["human"]
    breakdown = {
        "execute": counts["tool_calls"] * h["execute"]["min_per_unit"],
        "read": counts["tool_result_words"] * h["read"]["min_per_unit"],
        "draft": counts["assistant_words"] * h["draft"]["min_per_unit"],
    }
    return {
        "human_path_min": round(sum(breakdown.values()), 2),
        "breakdown": {k: round(v, 2) for k, v in breakdown.items()},
        "counts": counts,
    }


def measure_session_path(jsonl_path, rates=None, include_subagents=True):
    """트랜스크립트 1개 → 세션 경로 기반 human w/o AI 분.

    사람 counterfactual이므로 서브에이전트가 수행한 작업도 그 사람이 해야 할
    노동 — 기본 합산.
    """
    counts = parse_actions(jsonl_path)
    if include_subagents:
        for sf in glob.glob(str(Path(jsonl_path).with_suffix("")) + "/subagents/*.jsonl"):
            sc = parse_actions(sf)
            for k in ("tool_calls", "tool_result_words", "assistant_words"):
                counts[k] += sc[k]
    return human_path_minutes(counts, rates)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        r = measure_session_path(p)
        b = r["breakdown"]
        print(f"{Path(p).name}: human_path={r['human_path_min']}min "
              f"(execute {b['execute']} + read {b['read']} + draft {b['draft']})")
