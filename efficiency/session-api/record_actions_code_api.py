# -*- coding: utf-8 -*-
"""record-actions w/o LLM 세션 측정 API — 분자·분모 모두 LLM 0회, 완전 결정론.

자의 위치 (README "세 자의 위치" 필독): **직행 경로의 바닥 자.**
건수형은 AI 행동의 변환이 아니라 "흔적 있으면 1건" — 검색 40회도 search
1건이다. 세 방식의 예상 순서는 req ≈ code ≤ rec이며, 판단 노동이 깊은
세션에서는 절대값이 과소(보수적)임을 감안하고 켬/끔 대조·세션 간 비교·
대량 일괄 측정에 쓸 것.

방법론 (§32):
    분자(human) = 기록 실측 → 고정 규칙으로 사람 행동 구성 → × human 요율.
    LLM의 잔여 역할(행동 종류 선택)을 고정 대응 규칙으로 치환:
      read    = 항해 구조 환산 (기여 정독 실측 + 훑기×탐색요율/정독요율 + 입력)
      draft   = 생성 파일 순계 (§31 재생), 파일 없으면 대화 보고 실측
      edit    = 기존 파일 순계
      search  = 검색 흔적 있으면 1건
      execute = 실행 흔적 있으면 1건
      verify  = 산출물 있으면 1건
      think   = 전략 생각 (§53) — 지시 직후 첫 응답의 생각 토큰 × 요율.
                (신 포맷 기록만 — 구 포맷은 미계상, §55)
                기본 ON, 휴먼화 축과 독립 (include_think=False로 끔).
    분모 = 공용 실측 (session_api.measure_agent_actual).

휴먼화 2축 (§40) — 끈 만큼 "AI 궤적을 그대로 사람이 한 셈"에 가까워진다:
    humanize_rw  (기본 ON)  읽기·쓰기 휴먼화 — 읽기 등급 분해 + 쓰기 번복
                            소거. OFF면 검토 전량 정독·번복 미소거.
    humanize_act (기본 ON)  행동 건수 휴먼화 — 건수형 "흔적 있으면 1건".
                            OFF = 로레코드: 행동 횟수를 세션 기록 그대로
                            (검색 40회면 search 40건).
    조합 순서 규약 (표·리포트·문서 공통): rw ON·act ON → rw OFF·act ON →
    rw ON·act OFF → rw OFF·act OFF(로레코드).

사용 (조합 순서 규약대로):
    from record_actions_code_api import measure, measure_batch
    r = measure("session.jsonl")                        # rw ON · act ON (기본)
    r = measure("session.jsonl", humanize_rw=False)     # rw OFF · act ON
    r = measure("session.jsonl", humanize_act=False)    # rw ON · act OFF
    r = measure("session.jsonl", humanize_rw=False,
                humanize_act=False)                     # rw OFF · act OFF
    r = measure("session.jsonl", humanize=False)        # 구 인터페이스 호환
    r["speedup"], r["human"]["min"], r["human"]["breakdown"]

CLI:
    python record_actions_code_api.py <session.jsonl> [...]
        [--norw] [--noact] [--nothink] [--json]
        (--raw, --rawrecord는 구 호환)
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


RAW_RECORD = "rawrecord"  # 구 인터페이스 호환용 (§40에서 2축 옵션으로 재편)


# 전략 생각 계상 (§53) — 원리: 일을 아는 사람은 실무 도구 사용에 생각을
# 쓰지 않는다(숙련 가정). 사람 고민은 문제를 어떻게 풀지 전략 짤 때 든다.
# 따라서 도구 사용 중간의 잔생각은 제외하고, **지시 직후 첫 응답의 생각**
# (= 전략 수립)만 분자에 계상한다. 실측(51세션): 전체 생각 토큰의 68%가
# 지시 직후에 몰림 — 위치 선별만으로 도구 잔생각이 걸러진다.
THINK_TOK2WORD = 0.75        # 토큰→단어 환산
THINK_AVG_STRAT_TOK = 0      # 구 포맷(토큰 미기록) 대체 단가 — 0 = 미계상
#                              (§55) 구 기록은 생각 블록의 존재만 남고 양이
#                              없다. 지점당 평균으로 때우면 생각의 양이 아니라
#                              지시 건수를 재게 되고(생각 토큰 대 지점 수
#                              상관 0.99), 소형 세션이 실측 대비 7~27배
#                              부풀려진다 — 모르는 값은 0으로 두고 과소를
#                              택한다. 신 포맷(2026-08-12+) 기록만 계상.
_THINK_DEFAULT_SPEC = {"unit": "word_count", "min_per_unit": 0.0025}
#                      # rates.json에 think 항목이 없을 때의 폴백 (400wpm 상당)


def collect_strategy_thinking(jsonl_path):
    """지시 직후 첫 응답의 생각(=전략 생각)만 선별 집계. 결정론, LLM 0회.

    선별 규칙 (§53):
      지시 = user 메시지 중 도구 결과 회신(tool_result)·meta·사이드체인 제외.
      전략 지점 = 그 지시 직후 첫 assistant 메시지에 생각 흔적이 있는 경우.
      생각량 = usage.output_tokens_details.thinking_tokens (2026-08-12+ 기록).
      구 포맷(토큰 수 미기록, 생각 블록만 존재)은 fallback_points로 세어
      보고만 하고 계상하지 않는다(§55, THINK_AVG_STRAT_TOK=0) — 양을
      모르는 생각에 평균값을 붙이면 지시 건수를 재게 되므로.

    반환: {"points": 전략 지점 수, "tokens": 토큰 실측 합,
           "fallback_points": 토큰 미기록 지점 수}
    """
    points = tokens = fallback = 0
    seen = set()
    awaiting = False
    with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("isSidechain"):
                continue
            t = rec.get("type")
            if t == "user":
                content = (rec.get("message") or {}).get("content")
                if isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in content):
                    continue  # 도구 결과 회신 — 지시 아님
                if rec.get("isMeta"):
                    continue
                awaiting = True
            elif t == "assistant" and awaiting:
                msg = rec.get("message") or {}
                mid = msg.get("id")
                if mid in seen:
                    continue  # 같은 메시지의 스트리밍 중복 기록
                if mid:
                    seen.add(mid)
                det = ((msg.get("usage") or {}).get("output_tokens_details")
                       or {})
                tt = det.get("thinking_tokens") or 0
                has_block = any(
                    isinstance(b, dict) and b.get("type") == "thinking"
                    for b in (msg.get("content") or []))
                if tt:
                    points += 1
                    tokens += tt
                elif has_block:
                    points += 1
                    fallback += 1
                awaiting = False
    return {"points": points, "tokens": tokens, "fallback_points": fallback}


def build_actions(stats, rates, humanize_rw=True, humanize_act=True):
    """기록 실측 → 사람 행동 목록 (결정론, LLM 0회). §32 고정 규칙.

    휴먼화 2축 (§40):
      humanize_rw  = 읽기·쓰기 휴먼화. ON이면 읽기 등급 분해(정독/훑기/헛읽기)
                     + 쓰기 번복 소계(순계). OFF면 검토 전량 정독·번복 미소거.
      humanize_act = 행동 건수 휴먼화. ON이면 행동 순계(§46) — 읽기 3등급·
                     쓰기 순계의 원리를 건수형에 적용: 검색 = 착지-기여
                     문서당 1건(쿼리 다듬기는 그 1건에 흡수, 헛검색 자동 0),
                     실행 = 정규화 명령 신원당 1건(같은 명령 반복 = 번복
                     상쇄, 실패 호출은 쓰기 순계의 실패 편집 제외처럼
                     순계에서 상쇄 — §48). 하한 max(1,·) — 흔적 있으면
                     최소 1건(구 바닥값),
                     상한 min(·, 호출 수) — 로레코드 이하. OFF면 로레코드 —
                     행동 횟수를 세션 기록 그대로(search=검색 호출 수,
                     execute=실행 호출 수). "AI가 한 행동을 사람이 똑같이
                     했다면"의 자.
                     마무리 verify 1건(산출물 있을 때)은 두 모드 공통(§43).
    기본(둘 다 ON) = 바닥 자. 구 humanize=True/False/"rawrecord"는
    measure()의 호환 인자로만 남음.
    """
    rm = rates.get("human_reading_model") or {}
    raw_record = not humanize_act
    if humanize_rw:
        read_rate = rates["human"]["read"].get("min_per_unit", 0.005)
        skim_rate = rm.get("skim_min_per_word", 0.00025)
        factor = (skim_rate / read_rate) if read_rate else 0.0
        read_w = (stats.get("deep_words", 0)
                  + stats.get("skim_words", 0) * factor
                  + stats.get("input_words", 0))
        draft_w = stats.get("out_draft_words", 0)
        edit_w = stats.get("out_edit_words", 0)
    else:  # rw 끔 — 읽기 전량 정독, 쓰기 번복 미소거
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
    if raw_record:
        # 궤적 재연: 행동 횟수 = 세션 기록의 호출 수 그대로
        if stats.get("search_calls"):
            items.append({"primitive": "search",
                          "count": stats["search_calls"]})
        if stats.get("exec_calls"):
            items.append({"primitive": "execute",
                          "count": stats["exec_calls"]})
    else:
        # 행동 순계 (§46): 하한 1(흔적 있으면 최소 1건) ≤ 순계 ≤ 호출 수
        # (로레코드) — 항목별 ON ≤ OFF 단조성 유지(§43 교훈)
        if stats.get("search_calls"):
            n = max(1, stats.get("search_landing_docs", 0))
            items.append({"primitive": "search",
                          "count": min(n, stats["search_calls"])})
        if stats.get("exec_calls"):
            n = max(1, stats.get("exec_net_calls", 0))
            items.append({"primitive": "execute",
                          "count": min(n, stats["exec_calls"])})
    if draft_w or edit_w:
        # 마무리 확인 1건 — 두 모드 공통 (§43). 초기 §39는 "기록에 대응
        # 행동 없음"이라며 로레코드에서 verify를 뺐는데, 그 결과 도구 호출이
        # 1~2회뿐인 소형 세션에서 궤적 천장이 바닥 자보다 낮아지는 모순이
        # 실측 43/91건 발생. 궤적을 재연하는 사람도 산출물 확인은 하므로
        # 공통 계상 — 이로써 건수형이 항목별로 OFF ≥ ON 보장.
        items.append({"primitive": "verify", "count": 1})
    return items


def measure(jsonl_path, humanize_rw=True, humanize_act=True, rates=None,
            include_subagents=False, force=False, humanize=None,
            include_think=True):
    """세션 1개 → LLM 0회 분자·분모·speedup. 반환 구조는 measure_session 동일.

    humanize_rw / humanize_act: 휴먼화 2축 (build_actions 참조, §40).
    humanize: 구 인터페이스 호환 — True/False/"rawrecord"를 2축으로 변환
              (지정 시 2축 인자보다 우선).
    include_think: 전략 생각 계상 (§53, collect_strategy_thinking 참조).
              기본 ON — 휴먼화 2축과 독립(모든 조합에 동일 가산이라 §43
              단조성 불변). False로 구(생각 미계상) 동작.
    """
    if humanize is not None:  # 구 인터페이스 호환 (§39 이전 소비자)
        if humanize == RAW_RECORD:
            humanize_rw, humanize_act = False, False
        else:
            humanize_rw, humanize_act = bool(humanize), True
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
    for a in build_actions(stats, rates, humanize_rw, humanize_act):
        spec = card[a["primitive"]]
        minutes = a["count"] * spec["min_per_unit"]
        total += minutes
        breakdown.append({"primitive": a["primitive"], "count": a["count"],
                          "unit": spec["unit"], "minutes": round(minutes, 2)})
    think_info = None
    if include_think:  # 전략 생각 (§53) — 휴먼화 축과 독립, 기본 ON
        st = collect_strategy_thinking(jsonl_path)
        eff_tok = st["tokens"] + st["fallback_points"] * THINK_AVG_STRAT_TOK
        think_words = round(eff_tok * THINK_TOK2WORD, 1)
        if think_words:
            spec = card.get("think") or _THINK_DEFAULT_SPEC
            minutes = think_words * spec["min_per_unit"]
            total += minutes
            breakdown.append({"primitive": "think", "count": think_words,
                              "unit": spec.get("unit", "word_count"),
                              "minutes": round(minutes, 2)})
        think_info = st
    h_min = round(total, 2)
    return {
        "session": Path(jsonl_path).name,
        "session_id": actual["counts"].get("session_id"),
        "suspect_output_channel": suspect,
        "human": {"min": h_min, "method": "record-actions-code",
                  "humanize_rw": humanize_rw, "humanize_act": humanize_act,
                  "include_think": include_think,
                  **({"think": think_info} if think_info else {}),
                  # 구 소비자 호환 표현: 둘 다 ON=True / act만 ON=False /
                  # 둘 다 OFF="rawrecord"
                  "humanize": (True if humanize_rw and humanize_act else
                               False if humanize_act else RAW_RECORD),
                  "breakdown": breakdown},
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
              "[--norw] [--noact] [--nothink] [--json]   "
              "(--raw=--norw, --rawrecord=--norw --noact 호환)",
              file=sys.stderr)
        return 2
    rw = not ("--norw" in argv or "--raw" in argv or "--rawrecord" in argv)
    act = not ("--noact" in argv or "--rawrecord" in argv)
    think = "--nothink" not in argv
    rows = measure_batch(paths, humanize_rw=rw, humanize_act=act,
                         include_think=think)
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
