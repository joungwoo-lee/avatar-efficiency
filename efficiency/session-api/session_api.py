# -*- coding: utf-8 -*-
"""세션 측정 API — 실행된 Claude Code 세션 1개의 AI 효율(speedup) 산정.

speedup = human_min(분자) ÷ agent_min(분모)
  분자(human) — 방식 선택:
    "req-actions"    (기본) 요구사항·행동: 기록→할일→사람 행동×요율.
                     규모 숫자는 코드 닻(항해 구조 읽기량·산출물 상한)이 확정.
                     calls="single"이면 할일 정리+행동 분해를 LLM 1회로 병합.
    "record-actions" 세션기록·행동: 할일 안 거치고 기록에서 바로 행동 분해.
                     같은 닻 적용. 교차확인 기준선 — 쓰기 규모가 AI 산출
                     전량을 상속(4~5배 과대)하는 한계 (CHANGELOG §20).
  분모: 트랜스크립트에 기록된 동작 단서 × 요율 (LLM 미사용, 결정론적)
        (../agent-effort/transcript_actual — 병렬 서브에이전트는 시간 미가산)

workunit 방식은 폐기 — workunit_deprecated.py 참고 보관.
아바타(사전) 측정 API는 ../counterfactual-api. 본 모듈은 사후(세션) 전용.

사용:
    from session_api import measure_session
    r = measure_session(llm, "session.jsonl")                    # req-actions
    r = measure_session(llm, "session.jsonl", human="record-actions")
    r["speedup"], r["human"]["min"], r["agent"]["total_min"]
"""
import glob
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (_ROOT / "human-effort" / "requirement-based",
           _ROOT / "human-effort" / "shared",
           _ROOT / "human-effort" / "record-actions",
           _ROOT / "human-effort" / "requirement-actions",
           _ROOT / "agent-effort"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from transcript_requirements import (extract_requirements,  # noqa: E402
                                     normalize_claude_code_jsonl)
from requirement_actions import (collect_record_stats,  # noqa: E402
                                 estimate_actions_from_requirements,
                                 estimate_actions_single)
from primitive_effort import estimate_human_min  # noqa: E402
from transcript_actual import parse_actions, actual_effort_minutes  # noqa: E402
from agent_effort import load_rates, speedup  # noqa: E402


class JsonRetryLLM:
    """프록시가 불량 JSON을 뱉으면 최대 retries회 재호출하는 래퍼."""

    def __init__(self, inner, retries=2):
        self.inner = inner
        self.retries = retries

    def complete_json(self, prompt, max_tokens):
        last = None
        for _ in range(self.retries + 1):
            try:
                return self.inner.complete_json(prompt, max_tokens)
            except Exception as e:
                last = e
        raise last


# 초소형 세션 판정 기준: 검토·입력 자료와 산출물이 이 밑이면 측정 가치 없는
# 핑퐁·잡담 세션 — 측정 시 완료조건 고정비로 5~7배 역부풀림이 실측 확인됨.
TRIVIAL_READ_WORDS = 100
TRIVIAL_ARTIFACT_WORDS = 50


def is_trivial_session(record_stats):
    """초소형(잡담·핑퐁) 세션 여부 — LLM 미사용 실측 판정."""
    read_total = (record_stats.get("reviewed_words", 0)
                  + record_stats.get("input_words", 0))
    return (read_total < TRIVIAL_READ_WORDS
            and record_stats.get("artifact_words", 0) < TRIVIAL_ARTIFACT_WORDS)


def measure_agent_actual(jsonl_path, rates=None, include_subagents=False):
    """분모만: 트랜스크립트 실측 agent_min. LLM 미사용, 결정론적.

    측정 기조: 분모 = "AI를 쓰는 사람의 에포트" + "AI가 실제 소모한 시간".
    - hitl은 단서(지시 건수·산출물 분량) × 요율 추정 — 산출물 검토·후작업은
      세션 밖에서 몰아 할 수 있어 세션 wall-clock으로는 못 잡는다.
    - 서브에이전트는 메인 타임라인과 **병렬**로 돌므로 실제 소모 시간에
      가산하지 않는다(기본 False). include_subagents=True는 자원량 참고용.
    """
    rates = rates or load_rates()
    counts = parse_actions(jsonl_path)
    sub_files = glob.glob(str(Path(jsonl_path).with_suffix("")) + "/subagents/*.jsonl")
    if include_subagents:  # 자원량(토큰·동작 총량) 관점 참고용 — 시간 아님
        for sf in sub_files:
            sc = parse_actions(sf)
            for k in ("tool_calls", "tool_result_words", "assistant_words"):
                counts[k] += sc[k]
    actual = actual_effort_minutes(counts, rates)
    actual["subagent_files"] = len(sub_files)
    actual["subagents_included"] = include_subagents
    return actual


def measure_session(llm, jsonl_path, human="req-actions", calls="single",
                    rates=None, max_chars=8000, include_subagents=False,
                    force=False):
    """세션 1개 → 분자·분모·speedup.

    human: "req-actions"(기본) | "record-actions"(교차확인 기준선)
    calls: "single"(할일+행동 병합, LLM 1회) | "staged"(할일→행동 2회,
           단계별 감사 가능). record-actions는 항상 1회라 calls 무시.

    반환: {
      "session": 파일명, "session_id",
      "human": {min, method, anchors, todos?, breakdown},
      "agent": {machine_min, hitl_min, total_min, breakdown, counts,
                subagent_files},
      "speedup": human_min / agent_total (None if agent 0),
      "speedup_vs_hitl": human_min / hitl_min (사람 감독시간 대비),
      "notes"
    }
    """
    rates = rates or load_rates()

    stats = collect_record_stats(jsonl_path)
    if is_trivial_session(stats) and not force:
        return {"session": Path(jsonl_path).name,
                "excluded": True,
                "reason": (f"초소형 세션 — 검토·입력 {stats['reviewed_words'] + stats['input_words']}단어, "
                           f"산출물 {stats['artifact_words']}단어 (기준 미달). "
                           "측정 시 역부풀림 확인돼 제외. force=True로 강제 측정 가능"),
                "record_stats": stats}

    actual = measure_agent_actual(jsonl_path, rates, include_subagents)
    notes = []

    if human == "req-actions":
        if calls == "single":
            norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars,
                                               include_tool_stats=False)
            ra = estimate_actions_single(llm, norm, record_stats=stats,
                                         rates=rates)
        else:
            norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars)
            req, n = extract_requirements(llm, norm)
            notes += n
            ra = estimate_actions_from_requirements(llm, req,
                                                    record_stats=stats,
                                                    rates=rates)
    elif human == "record-actions":
        norm = normalize_claude_code_jsonl(jsonl_path, max_chars=max_chars,
                                           include_tool_stats=False)
        ra = estimate_human_min(llm, norm, rates=rates, record_stats=stats)
    else:
        raise ValueError(
            f"지원하지 않는 human 방식: {human} "
            "(workunit은 폐기 — workunit_deprecated.py)")
    notes += ra["notes"]

    h_min = ra["human_min"]
    total = actual["total_min"]
    return {
        "session": Path(jsonl_path).name,
        "session_id": actual["counts"].get("session_id"),
        "human": {
            "min": h_min,
            "method": human,
            "anchors": ra.get("anchors", {}),
            "todos": ra.get("todos"),
            "breakdown": ra["breakdown"],
        },
        "agent": {
            "machine_min": actual["machine_min"],
            "hitl_min": actual["hitl_min"],
            "total_min": total,
            "breakdown": actual["breakdown"],
            "counts": {k: v for k, v in actual["counts"].items()
                       if k not in ("first_ts", "last_ts")},
            "subagent_files": actual["subagent_files"],
        },
        "speedup": speedup(h_min, total),
        "speedup_vs_hitl": speedup(h_min, actual["hitl_min"]),
        "notes": notes,
    }


def measure_sessions(llm, jsonl_paths, **kw):
    """배치: 세션별 measure_session. 실패는 {"session", "error"}로 기록하고 계속."""
    results = []
    for p in jsonl_paths:
        try:
            results.append(measure_session(llm, p, **kw))
        except Exception as e:
            results.append({"session": Path(p).name,
                            "error": f"{type(e).__name__}: {e}"})
    return results


def format_report(rows):
    lines = []
    th = ta = 0.0
    for r in rows:
        if "error" in r:
            lines.append(f"{r['session'][:12]}  FAIL: {r['error'][:70]}")
            continue
        if r.get("excluded"):
            lines.append(f"{r['session'][:12]}  제외: {r['reason'][:70]}")
            continue
        h, a = r["human"], r["agent"]
        th += h["min"]
        ta += a["total_min"]
        lines.append(
            f"{r['session'][:12]}  human={h['min']:>7.1f}min ({h['method']})  "
            f"agent={a['total_min']:>7.1f}min "
            f"({a['machine_min']:.1f}+{a['hitl_min']:.1f})  "
            f"speedup={r['speedup'] or 0:>5.2f}x")
        for t in (h.get("todos") or [])[:3]:
            lines.append(f"              todo: {str(t)[:64]}")
    ok = [r for r in rows if "error" not in r and not r.get("excluded")]
    if ok and ta > 0:
        lines.append(f"합산: human={th:.0f}min  agent={ta:.1f}min  "
                     f"overall speedup={th / ta:.2f}x  ({len(ok)}/{len(rows)} 세션)")
    return "\n".join(lines)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: python session_api.py <session.jsonl> [...] "
              "[--json] [--actual-only] [--human=record-actions] [--staged]",
              file=sys.stderr)
        return 2
    if "--actual-only" in argv:  # 분모 실측만 — LLM 불필요
        for p in paths:
            a = measure_agent_actual(p)
            print(f"{Path(p).name}: agent={a['total_min']}min "
                  f"(기계 {a['machine_min']} + hitl {a['hitl_min']})")
        return 0
    human = "req-actions"
    for a in argv:
        if a.startswith("--human="):
            human = a.split("=", 1)[1]
    calls = "staged" if "--staged" in argv else "single"
    from onprem_llm_sim import OnpremLLM
    llm = JsonRetryLLM(OnpremLLM())
    rows = measure_sessions(llm, paths, human=human, calls=calls)
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(format_report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
