# -*- coding: utf-8 -*-
"""record-actions w/o LLM 세션 측정 API — 분자·분모 모두 LLM 0회, 완전 결정론.

방법론 (§32):
    분자(human) = 기록 실측 → 고정 규칙으로 사람 행동 구성 → × human 요율.
    LLM의 잔여 역할(행동 종류 선택)을 고정 대응 규칙으로 치환:
      read    = 항해 구조 환산 (기여 정독 실측 + 훑기×탐색요율/정독요율 + 입력)
      draft   = 생성 파일 순계 (§31 재생), 파일 없으면 대화 보고 실측
      edit    = 기존 파일 순계
      search  = 검색 흔적 있으면 1건
      execute = 실행 흔적 있으면 1건
      verify  = 산출물 있으면 1건
    분모 = 공용 실측 (session_api.measure_agent_actual).

humanize=False (대조군): 읽기·쓰기 휴먼화 기능을 끈 옛 자 —
      read  = AI가 검토한 전량 + 입력 (전부 정독 취급, 등급 구분 없음)
      draft/edit = 옛 방식 총량 (Write 마지막 판 + Edit 누적, 번복 소거 없음)
      건수형 규칙은 동일 (평가 대상이 아니므로 통제 변인).
    → 두 모드의 차이 = "읽기 항해 구조 환산 + 쓰기 번복 소거"의 순효과.

사용:
    from record_actions_code_api import measure, measure_batch
    r = measure("session.jsonl")                  # 휴먼화 켬 (기본)
    r = measure("session.jsonl", humanize=False)  # 대조군
    r["speedup"], r["human"]["min"], r["human"]["breakdown"]

CLI:
    python record_actions_code_api.py <session.jsonl> [...] [--raw] [--json]
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from session_api import (measure_agent_actual, is_trivial_session)  # noqa: E402
from requirement_actions import collect_record_stats  # noqa: E402
from agent_effort import load_rates, speedup  # noqa: E402


# 쓰기 툴 포맷 미등록 의심 (§38): "도구 활동 많음 + 산출물 0" 같은 헐거운
# 규칙은 운영성 세션(실행만 하고 산출물 없음)을 오탐해 리포트 신뢰만 깎는다
# (게다가 §33 실사고 세션은 도구 호출 1회라 그 규칙에 안 걸렸음). 대신
# 사고의 실제 서명을 겨냥한다: **미등록 도구의 입력에 글(50단어↑)이 실려
# 나갔는데 그 도구의 응답은 짧은 ack** — 산출물이 그 도구로 제출됐다는
# 직접 증거. 여기에 잡힌 산출물까지 없으면 쓰기 포맷 미등록이 원인이다.
_SUSPECT_MIN_WORDS = 50  # 조회형 읽기 인정 문턱(§27)과 동일 눈금


def suspect_output_channel(stats):
    """미등록 쓰기 포맷 서명 감지 → (의심 여부, 근거 문구). 결정론."""
    captured = (stats.get("artifact_words", 0)
                + stats.get("answer_words", 0))
    unrec_w = stats.get("unrec_write_words", 0)
    tools = stats.get("unrec_write_tools") or {}
    if unrec_w >= _SUSPECT_MIN_WORDS and captured < _SUSPECT_MIN_WORDS:
        names = ", ".join(f"{t}({w}단어)" for t, w in
                          sorted(tools.items(), key=lambda x: -x[1]))
        return True, (f"쓰기 툴 포맷 미등록 의심: 미등록 도구 {names} 입력으로 "
                      f"글 {unrec_w}단어가 나갔는데(응답은 짧은 확인뿐) 잡힌 "
                      f"산출물은 {captured}단어 — 이 도구의 쓰기 포맷을 "
                      "측정기에 등록해야 할 수 있음. 사람 시간·효율 과소 가능")
    return False, ""


def build_actions(stats, rates, humanize=True):
    """기록 실측 → 사람 행동 목록 (결정론, LLM 0회). §32 고정 규칙."""
    rm = rates.get("human_reading_model") or {}
    if humanize:
        read_rate = rates["human"]["read"].get("min_per_unit", 0.005)
        skim_rate = rm.get("skim_min_per_word", 0.00025)
        factor = (skim_rate / read_rate) if read_rate else 0.0
        read_w = (stats.get("deep_words", 0)
                  + stats.get("skim_words", 0) * factor
                  + stats.get("input_words", 0))
        draft_w = stats.get("out_draft_words", 0)
        edit_w = stats.get("out_edit_words", 0)
    else:
        read_w = stats.get("reviewed_words", 0) + stats.get("input_words", 0)
        draft_w = stats.get("gross_draft_words", 0)
        edit_w = stats.get("gross_edit_words", 0)
    if not (draft_w or edit_w):
        draft_w = stats.get("answer_words", 0)  # 보고형: 대화 보고가 산출물
    items = []
    if read_w:
        items.append({"primitive": "read", "count": round(read_w, 1)})
    if draft_w:
        items.append({"primitive": "draft", "count": round(draft_w, 1)})
    if edit_w:
        items.append({"primitive": "edit", "count": round(edit_w, 1)})
    if stats.get("search_calls"):
        items.append({"primitive": "search", "count": 1})
    if stats.get("exec_calls"):
        items.append({"primitive": "execute", "count": 1})
    if draft_w or edit_w:
        items.append({"primitive": "verify", "count": 1})
    return items


def measure(jsonl_path, humanize=True, rates=None, include_subagents=False,
            force=False):
    """세션 1개 → LLM 0회 분자·분모·speedup. 반환 구조는 measure_session 동일."""
    rates = rates or load_rates()
    stats = collect_record_stats(jsonl_path)
    suspect, suspect_why = suspect_output_channel(stats)
    if is_trivial_session(stats) and not force:
        return {"session": Path(jsonl_path).name, "excluded": True,
                "reason": "초소형 세션 (기준 미달)", "record_stats": stats,
                "suspect_output_channel": suspect,
                **({"suspect_reason": suspect_why} if suspect else {})}
    actual = measure_agent_actual(jsonl_path, rates, include_subagents)
    card = rates["human"]
    total = 0.0
    breakdown = []
    for a in build_actions(stats, rates, humanize):
        spec = card[a["primitive"]]
        minutes = a["count"] * spec["min_per_unit"]
        total += minutes
        breakdown.append({"primitive": a["primitive"], "count": a["count"],
                          "unit": spec["unit"], "minutes": round(minutes, 2)})
    h_min = round(total, 2)
    return {
        "session": Path(jsonl_path).name,
        "session_id": actual["counts"].get("session_id"),
        "suspect_output_channel": suspect,
        "human": {"min": h_min, "method": "record-actions-code",
                  "humanize": humanize, "breakdown": breakdown},
        "agent": {"machine_min": actual["machine_min"],
                  "hitl_min": actual["hitl_min"],
                  "total_min": actual["total_min"],
                  "breakdown": actual["breakdown"],
                  "subagent_files": actual["subagent_files"]},
        "speedup": speedup(h_min, actual["total_min"]),
        "speedup_vs_hitl": speedup(h_min, actual["hitl_min"]),
        "notes": [suspect_why] if suspect else [],
    }


def measure_batch(jsonl_paths, **kw):
    """배치. 실패 세션은 {"session", "error"}로 기록하고 계속."""
    rows = []
    for p in jsonl_paths:
        try:
            rows.append(measure(p, **kw))
        except Exception as e:
            rows.append({"session": Path(p).name,
                         "error": f"{type(e).__name__}: {e}"})
    return rows


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: python record_actions_code_api.py <session.jsonl> [...] "
              "[--raw] [--json]", file=sys.stderr)
        return 2
    rows = measure_batch(paths, humanize="--raw" not in argv)
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    th = ta = 0.0
    ok = 0
    for r in rows:
        if "error" in r:
            print(f"{r['session'][:12]}  FAIL: {r['error'][:70]}")
            continue
        if r.get("excluded"):
            print(f"{r['session'][:12]}  제외: {r['reason']}")
            continue
        ok += 1
        th += r["human"]["min"]
        ta += r["agent"]["total_min"]
        print(f"{r['session'][:12]}  human={r['human']['min']:>8.1f}min  "
              f"agent={r['agent']['total_min']:>7.1f}min  "
              f"speedup={r['speedup'] or 0:>6.2f}x")
    if ok and ta > 0:
        print(f"합산: human={th:.0f}min  agent={ta:.1f}min  "
              f"overall speedup={th / ta:.2f}x  ({ok}/{len(rows)} 세션)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
