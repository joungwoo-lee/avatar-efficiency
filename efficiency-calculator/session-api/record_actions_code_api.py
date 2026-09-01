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
      read    = 항해 구조 환산 — 기여 파일은 증거 블록 정독(최소 앞 200단어,
                §75) + 나머지 훑기(450 wpm, §66); 조회형·범위 지정 Read는
                전량 정독(§70·§75); 실행 출력·검색 결과는 호출당 앞 200
                정독 + 나머지 훑기(§59·§73); 입력 전량 정독
      draft   = 생성 파일 순계 (§31 재생) + 기존 파일 순수 추가(§66)
                + 마무리 답변(파일 유무 무관, §73)
      edit    = 기존 파일의 변경 단어 순계 — Edit new_string 중 앵커(3단어+
                연속 일치) 제외 (§66), 요율 = 같은 종류 draft × 0.5 (40 wpm)
      search  = 착지-기여 문서당 1건, 검색한 지시 턴당 최소 1건 (§46·§70)
      execute = 4토막 — 구성(첫 신원만) + 실측 대기 + 판독 + 조작 (§59);
                무효는 환경·타이핑 실수·거부 서명일 때만 (§69)
      verify  = 산출물 있으면 1건
      think   = 전략 생각 (§53) — 지시 직후 첫 응답의 생각 토큰 × 요율
                (정독과 동속 0.005, §57), 서브에이전트 기록 포함 (§68).
                (구 포맷은 토큰 수가 없어 건당 1.5분 고정, §58)
                + 서브 보고문 전량 (§68) + 메인 진행 나레이션 (§73) — 밖으로
                나온 생각, 같은 요율.
                기본 ON, 휴먼화 축과 독립 (include_think=False로 끔).
    분모 = 공용 실측 (session_api.measure_agent_actual).

휴먼화 2축 (§40) — 끈 만큼 "AI 궤적을 그대로 사람이 한 셈"에 가까워진다:
    humanize_rw  (기본 ON)  읽기·쓰기 휴먼화 — 읽기 등급 분해 + 쓰기 번복
                            소거. OFF면 검토 전량 정독·번복 미소거(총량도
                            §66부터 파일 출처·변경 단어 기준으로 분류해
                            항목별 ON ≤ OFF 보장).
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

hitl 축약 모드 (§79, 기본 OFF): measure(..., hitl_compact=True) /
    CLI --hitl-compact. 분모의 사람 확인을 "파일 쓰기 있는 확인 시점당
    min(2.0, 0.5·ln(1+구간 단어/100)), 테스트 통과 파일 제외, correct 없음"
    으로 바꾼다(transcript_actual.actual_effort_minutes 참조). 분자 불변.

구간 측정 (§80): measure(..., as_of=T, window=(start, end)) / CLI
    --as-of T --from A --to B (ISO 8601 또는 epoch 초; tz 없는 ISO는 로컬).
    as_of = "어느 시점의 눈으로" — T 이후 기록을 잘라내고(서브에이전트 포함)
    판정(기여 등급·쓰기 순계·명령 신원·결론·확인 시점)을 그 지식으로만 한다.
    window = "어느 사건을 더하나" — 사건 시각이 [A, B]인 것만 계상.
    기본 as_of = 기록 끝, window = (0, as_of). start ≤ end ≤ as_of.
    · 그 시점에 잰 값 재연: as_of=T (window 생략)
    · 구간이 최종 결과에 기여한 몫: window=(A, B) (as_of 생략)
    가산성: 같은 as_of 아래 구간을 나눠 더하면 전체와 같다 — 건수 하한
    (검색 턴당 1·실행 1·verify 1)·절감율 하한(§76)은 구간마다 적용되어 예외.
    엎어진 앞 작업은 어느 구간에도 안 실린다(전체 순계와 같은 원칙).

CLI:
    python record_actions_code_api.py <session.jsonl> [...]
        [--norw] [--noact] [--nothink] [--hitl-compact] [--json]
        [--as-of T] [--from A] [--to B]
        (--raw, --rawrecord는 구 호환)
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from session_api import (measure_agent_actual, is_trivial_session)  # noqa: E402
from requirement_actions import (collect_record_stats,  # noqa: E402
                                 find_subagent_files)
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

# 채널 결산 (§59 규칙2): 세션에서 오간 글이 **어느 축으로 갔는지** 통로별로
# 결산한다. 구멍은 늘 "이 통로는 실행이니까/도구니까 계산에서 빼자"에서 났다
# (셸 명령문 속 코드·실행 출력 판독·서브에이전트 전량). 통로 이름으로 면제하지
# 않고 결산표를 세션마다 내면, 미계상 채널이 커질 때 리포트에 바로 드러난다.
_CHANNEL_AXIS = {
    "write_tool_words": "쓰기(draft/edit)",
    "shell_cmd_words": "실행-구성",
    "exec_out_words": "실행-판독",
    "tool_result_words": "읽기(등급 분해)",
    "user_input_words": "읽기(지시 입력)",
    "subagent_files": "서브에이전트(전 축 편입, §59)",
    "unrec_write_words": None,      # 미등록 쓰기 포맷 — §38 경보 대상
    "sub_report_words": "생각(think — 서브 보고문, §68)",
    "image_blocks": None,           # 스크린샷 판독 — 미계상
}
_UNCOUNTED_WARN_WORDS = 2000        # 미계상 채널 경보 문턱


def channel_audit(stats):
    """통로별 결산 → {"axes": {...}, "uncounted": {...}, "warn": bool}."""
    ch = dict(stats.get("channels") or {})
    axes, unc = {}, {}
    for k, v in ch.items():
        if not v:
            continue
        axis = _CHANNEL_AXIS.get(k, None)
        if axis:
            axes[k] = {"words": v, "axis": axis}
        else:
            unc[k] = v
    words = sum(v for k, v in unc.items() if k != "image_blocks")
    return {"axes": axes, "uncounted": unc,
            "uncounted_words": words,
            "warn": words >= _UNCOUNTED_WARN_WORDS}


# 전략 생각 계상 (§53) — 원리: 일을 아는 사람은 실무 도구 사용에 생각을
# 쓰지 않는다(숙련 가정). 사람 고민은 문제를 어떻게 풀지 전략 짤 때 든다.
# 따라서 도구 사용 중간의 잔생각은 제외하고, **지시 직후 첫 응답의 생각**
# (= 전략 수립)만 분자에 계상한다. 실측(51세션): 전체 생각 토큰의 68%가
# 지시 직후에 몰림 — 위치 선별만으로 도구 잔생각이 걸러진다.
THINK_TOK2WORD = 0.75        # 토큰→단어 환산
THINK_FALLBACK_MIN = 1.5      # 구 포맷(토큰 미기록) 전략 생각 지점의 건당 시간

# 절감율 하한 (§76): 절감율 = 1 − agent/human 은 위로 100%에서 막히지만
# 아래로는 한계가 없어(agent가 human의 3배면 −200%) 세션별 평균이 음수
# 하나에 끌려간다. 분자에 바닥을 깔아 절감율이 SAVINGS_FLOOR 밑으로 못
# 내려가게 한다:  절감율 ≥ F  ⇔  human ≥ agent / (1 − F).
# F = −0.5 → human ≥ agent × 2/3. 바닥에 걸린 세션은 notes 한 줄(실측 원값
# 포함)로 드러난다 — 출력 필드는 늘리지 않는다. None 이면 끔.
SAVINGS_FLOOR = -0.5
HUMAN_FLOOR_RATIO = 1.0 / (1.0 - SAVINGS_FLOOR)   # = 0.6667
#                              (§58) 구 기록은 생각 블록의 존재만 남고 양이 없다.
#                              양을 모르는 지점에 "보통 한 턴"만 인정하고 깊은
#                              고민의 몫은 포기한다(과소 유지).
#                              참고 — §60 재보정 검토: 측정기 부산물 세션
#                              (entrypoint=sdk-cli, 지점당 4,396토큰)을 제외한
#                              실측 442지점의 중앙값은 622토큰 = 2.33분, 평균은
#                              973토큰 = 3.65분이다. 즉 1.5분은 그 실측 중앙값보다
#                              **더 낮은 하한**이며, 2.33분으로 올리면 전체 배율이
#                              5.34 → 5.41배(+1.3%)가 된다. 하한 성격을 유지하기로
#                              하여 1.5분을 존치한다.
#                              요율(rates.json think)이 바뀌어도 건당 분은 고정 —
#                              아래에서 분을 단어로 역환산해 쓴다.
#                              신 포맷(2026-08-12+)은 실측 토큰 그대로.
_THINK_DEFAULT_SPEC = {"unit": "word_count", "min_per_unit": 0.005}
#                      # rates.json에 think 항목이 없을 때의 폴백
#                      # (§57 분자 정독과 동속 — 200wpm 상당)


def collect_strategy_thinking(jsonl_path, subagent_paths=(), count_window=None):
    """지시 직후 첫 응답의 생각(=전략 생각)만 **계상**. 결정론, LLM 0회.

    §68: 서브에이전트 기록(subagent_paths)도 같은 규칙으로 훑는다 — 서브의
    지시(부모가 준 프롬프트) 직후 첫 응답 생각 = 그 서브의 전략 생각.
    "사람이 직렬로 다 한다면" 위임 여부에 값이 흔들리지 않게. 서브 몫은
    sub_tokens/sub_points/sub_fallback_points로 따로도 보고한다.

    도구 중간 생각은 계상하지 않는다(§53 숙련자 가정) — 다만 그 크기를
    mid_tokens로 함께 보고해 미계상 규모가 리포트에 드러나게 한다
    (실측: 전 세션 생각 토큰의 74%가 여기 해당).

    선별 규칙 (§53):
      지시 = user 메시지 중 도구 결과 회신(tool_result)·meta·사이드체인 제외.
      전략 지점 = 그 지시 직후 첫 assistant 메시지에 생각 흔적이 있는 경우.
      생각량 = usage.output_tokens_details.thinking_tokens (2026-08-12+ 기록).
      구 포맷(토큰 수 미기록, 생각 블록만 존재)은 fallback_points로 세고,
      건당 THINK_FALLBACK_MIN(1.5분) 고정으로 계상한다(§58) — 실측 평균
      (2.98분)이 아니라 중앙값(1.49분)에 맞춘 하한이다.

    반환: {"points": 전략 지점 수, "tokens": 전략 생각 토큰,
           "fallback_points": 토큰 미기록 전략 지점 수,
           "mid_tokens": 도구 중간 생각 토큰, "mid_points": 그 지점 수,
           "all_tokens": 전략+중간 합,
           "sub_points"/"sub_tokens"/"sub_fallback_points": 위 합계 중 서브 몫}
    """
    points = tokens = fallback = 0
    mid_tokens = mid_points = 0
    sub_points = sub_tokens = sub_fallback = 0
    for _path, _is_sub in [(jsonl_path, False)] + [(p, True)
                                                   for p in subagent_paths]:
        try:
            fh = open(_path, encoding="utf-8", errors="replace")
        except OSError:
            if _is_sub:
                continue
            raise
        with fh:
            _r = _scan_strategy_thinking(fh, skip_sidechain=not _is_sub,
                                         count_window=count_window)
        points += _r[0]; tokens += _r[1]; fallback += _r[2]
        mid_points += _r[3]; mid_tokens += _r[4]
        if _is_sub:
            sub_points += _r[0]; sub_tokens += _r[1]; sub_fallback += _r[2]
    return {"points": points, "tokens": tokens, "fallback_points": fallback,
            "mid_points": mid_points, "mid_tokens": mid_tokens,
            "all_tokens": tokens + mid_tokens,
            "sub_points": sub_points, "sub_tokens": sub_tokens,
            "sub_fallback_points": sub_fallback}


def _scan_strategy_thinking(fh, skip_sidechain=True, count_window=None):
    """기록 1파일의 전략/중간 생각 집계 → (points, tokens, fallback, mid_points,
    mid_tokens). 서브 파일은 전 기록이 isSidechain이라 skip_sidechain=False.
    count_window: §80 — 생각은 그 응답 레코드의 시각으로 귀속."""
    points = tokens = fallback = 0
    mid_tokens = mid_points = 0
    seen = set()
    awaiting = False
    win = tuple(count_window) if count_window else None
    last_tw = 0.0
    if True:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if skip_sidechain and rec.get("isSidechain"):
                continue
            _tw = _ts_epoch(rec.get("timestamp")) or last_tw
            last_tw = _tw
            inw = win is None or (win[0] <= _tw <= win[1])
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
                if tt and inw:
                    points += 1
                    tokens += tt
                elif has_block and inw:
                    points += 1
                    fallback += 1
                awaiting = False
            elif t == "assistant":
                # 도구 중간 생각 (§59) — 지시 직후가 아닌 모든 응답의 생각
                msg = rec.get("message") or {}
                mid = msg.get("id")
                if mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                det = ((msg.get("usage") or {}).get("output_tokens_details")
                       or {})
                tt = det.get("thinking_tokens") or 0
                if tt and inw:
                    mid_points += 1
                    mid_tokens += tt
    return points, tokens, fallback, mid_points, mid_tokens


# ---------------------------------------------------------------- §80 구간 측정

def _ts_epoch(x):
    """ISO 타임스탬프 → epoch 초 (없거나 깨지면 None)."""
    if not x:
        return None
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def parse_time(x):
    """CLI/API 시각 인자 → epoch 초. 숫자(문자열 포함)는 epoch, ISO 8601은
    파싱(tz 없으면 로컬 시각으로 해석). None은 None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    try:
        return float(s)
    except ValueError:
        pass
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()          # 로컬 시각으로 해석
    return dt.timestamp()


def slice_session(jsonl_path, as_of, subagent_paths=None):
    """T(as_of) 이후 레코드를 잘라낸 임시 세션 사본 → (main, subs, tmpdir).

    "그 시점의 눈으로" 재연: 판정 규칙(기여 등급·쓰기 순계·명령 신원·결론
    승격·확인 시점)이 세션 전체를 보고 정해지므로, T 시점 값을 재연하려면
    T 뒤 기록이 없어야 한다. 시각 없는 레코드는 직전 시각을 물려받아 판정.
    서브에이전트 기록도 같은 T로 자르고 `<stem>/subagents/`에 둬 자동 탐색
    (find_subagent_files·measure_agent_actual)이 그대로 동작한다.
    호출자가 tmpdir를 지운다(shutil.rmtree)."""
    as_of = float(as_of)
    if subagent_paths is None:
        subagent_paths = find_subagent_files(jsonl_path)
    tmpdir = tempfile.mkdtemp(prefix="asof_")
    stem = Path(jsonl_path).stem

    def _cut(src, dst):
        last = 0.0
        n = 0
        with open(src, encoding="utf-8", errors="replace") as fi, \
                open(dst, "w", encoding="utf-8") as fo:
            for line in fi:
                s = line.strip()
                if not s:
                    continue
                try:
                    rec = json.loads(s)
                except json.JSONDecodeError:
                    continue
                t = _ts_epoch(rec.get("timestamp")) if isinstance(rec, dict) \
                    else None
                if t is None:
                    t = last
                last = t
                if t <= as_of:
                    fo.write(line if line.endswith("\n") else line + "\n")
                    n += 1
        return n
    main = os.path.join(tmpdir, stem + ".jsonl")
    _cut(jsonl_path, main)
    subs = []
    if subagent_paths:
        sd = os.path.join(tmpdir, stem, "subagents")
        os.makedirs(sd, exist_ok=True)
        for sp in subagent_paths:
            dst = os.path.join(sd, Path(sp).name)
            if _cut(sp, dst):
                subs.append(dst)
            else:
                os.unlink(dst)
    return main, subs, tmpdir


def write_minutes(kind_words, rates, is_edit=False):
    """쓰기 종류별 요율 적용 (§59). 반환: (분, 단어수).

    코드·문서·데이터는 사람 절차가 다르다 — 코드는 짜고, 문서는 쓰고,
    데이터는 뽑는다. human_write_model이 없으면 구 단일 요율로 폴백.
    """
    total_w = sum(kind_words.values())
    wm = rates.get("human_write_model")
    if not wm:
        r = rates["human"]["edit" if is_edit else "draft"]["min_per_unit"]
        return total_w * r, total_w
    f = wm.get("edit_factor", 0.4) if is_edit else 1.0
    other = wm.get("other_min_per_word", 0.05)
    minutes = sum(w * wm.get(f"{k}_min_per_word", other) * f
                  for k, w in kind_words.items())
    return minutes, total_w


def exec_item(stats, rates, humanize_act=True):
    """실행 4토막 (§59): 수단 구성 + 실측 대기 + 결과 판독 + 기계 조작.

    종전은 건당 고정 2.0분이라 즉석 스크립트(건당 평균 97단어)와
    `git status`가 같은 값이었다. 구성·대기·판독은 전부 트랜스크립트
    실측이라 seed가 오히려 하나 줄어든다.
    """
    calls = stats.get("exec_calls", 0)
    if not calls:
        return None
    net = min(max(1, stats.get("exec_net_calls", 0)), calls)
    em = rates.get("human_exec_model")
    if not em:  # 구 폴백: 건당 고정 요율
        return {"primitive": "execute", "count": net if humanize_act else calls}
    if humanize_act:
        n = net
        compose_w = stats.get("exec_compose_words", 0)
        mech = (n * em.get("new_cmd_min", 0.25)
                + max(0, calls - n) * em.get("repeat_cmd_min", 0.1))
    else:  # 로레코드 — 궤적 그대로: 매 호출이 새 명령
        n = calls
        compose_w = stats.get("exec_compose_words_gross", 0)
        mech = calls * em.get("new_cmd_min", 0.25)
    rr = rates["human"]["read"]["min_per_unit"]
    sr = (rates.get("human_reading_model") or {}).get("skim_min_per_word",
                                                      rr / 20)
    compose = compose_w * em.get("compose_min_per_word", 0.05)
    wait = stats.get("exec_wait_min", 0.0)
    read = (stats.get("exec_out_deep_words", 0) * rr
            + stats.get("exec_out_skim_words", 0) * sr)
    return {"primitive": "execute", "count": n, "unit": "episode",
            "minutes": round(compose + wait + read + mech, 2),
            "detail": {"compose_min": round(compose, 2),
                       "wait_min": round(wait, 2),
                       "read_min": round(read, 2),
                       "mechanical_min": round(mech, 2),
                       "compose_words": compose_w,
                       "out_words": stats.get("exec_out_words", 0)}}


def build_actions(stats, rates, humanize_rw=True, humanize_act=True):
    """기록 실측 → 사람 행동 목록 (결정론, LLM 0회). §32 고정 규칙.

    휴먼화 2축 (§40):
      humanize_rw  = 읽기·쓰기 휴먼화. ON이면 읽기 등급 분해(정독/훑기/헛읽기)
                     + 쓰기 번복 소계(순계). OFF면 검토 전량 정독·번복 미소거.
      humanize_act = 행동 건수 휴먼화. ON이면 행동 순계(§46) — 읽기 3등급·
                     쓰기 순계의 원리를 건수형에 적용: 검색 = 착지-기여
                     문서당 1건(쿼리 다듬기는 그 1건에 흡수, 헛검색 자동 0)
                     — §70부터 검색한 지시 턴당 최소 1건,
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
                  + stats.get("input_words", 0)
                  # §73: 검색 결과 판독 — 호출당 앞 200 정독·나머지 훑기
                  # (rw OFF는 reviewed 전량 정독에 이미 포함, 여기만 가산)
                  + stats.get("search_out_deep_words", 0)
                  + stats.get("search_out_skim_words", 0) * factor)
        draft_kind = dict(stats.get("out_draft_by_kind") or {})
        edit_kind = dict(stats.get("out_edit_by_kind") or {})
        if not draft_kind:  # 구 stats 호환
            draft_kind = {"other": stats.get("out_draft_words", 0)}
            edit_kind = {"other": stats.get("out_edit_words", 0)}
    else:  # rw 끔 — 읽기 전량 정독, 쓰기 번복 미소거
        # 실행 출력은 아래 exec_item이 따로 매기므로 여기서 뺀다(이중계상 방지)
        read_w = (max(0, stats.get("reviewed_words", 0)
                      - stats.get("exec_out_words", 0))
                  + stats.get("input_words", 0))
        gdk = stats.get("gross_draft_by_kind")
        gek = stats.get("gross_edit_by_kind")
        gk = dict(stats.get("gross_write_by_kind") or {})
        if gdk is not None and gek is not None:
            # §66: 총량도 종류별 draft/edit가 직접 온다 (파일 출처 기준 분류).
            # 종전의 전역 share 비율 분배는 종류 무관 희석이라 폐지.
            draft_kind = dict(gdk)
            edit_kind = dict(gek)
        elif gk:  # 구 stats 호환
            gd = stats.get("gross_draft_words", 0)
            ge = stats.get("gross_edit_words", 0)
            tot = gd + ge
            share = (gd / tot) if tot else 1.0
            draft_kind = {k: v * share for k, v in gk.items()}
            edit_kind = {k: v * (1 - share) for k, v in gk.items()}
        else:
            draft_kind = {"other": stats.get("gross_draft_words", 0)}
            edit_kind = {"other": stats.get("gross_edit_words", 0)}
    draft_w = sum(draft_kind.values())
    edit_w = sum(edit_kind.values())
    # §73: 마무리 답변은 파일 산출물 유무와 무관하게 draft(문서 요율) — 파일이
    # 있어도 사람은 인수인계 메모·결과 보고를 쓴다. 보고형(파일 없음)은 종전과
    # 같은 값. 양 모드 동일(단조성 불변).
    aw = stats.get("answer_words", 0)
    if aw:
        draft_kind["doc"] = draft_kind.get("doc", 0) + aw
    draft_w = sum(draft_kind.values())
    items = []
    if read_w:
        items.append({"primitive": "read", "count": round(read_w, 1)})
    if draft_w:
        dm, dw = write_minutes(draft_kind, rates)
        items.append({"primitive": "draft", "count": round(dw, 1),
                      "unit": "word_count", "minutes": round(dm, 2),
                      "detail": {k: round(v, 1)
                                 for k, v in draft_kind.items() if v}})
    if edit_w:
        emn, ew = write_minutes(edit_kind, rates, is_edit=True)
        items.append({"primitive": "edit", "count": round(ew, 1),
                      "unit": "word_count", "minutes": round(emn, 2),
                      "detail": {k: round(v, 1)
                                 for k, v in edit_kind.items() if v}})
    if raw_record:
        # 궤적 재연: 행동 횟수 = 세션 기록의 호출 수 그대로
        if stats.get("search_calls"):
            items.append({"primitive": "search",
                          "count": stats["search_calls"]})
    else:
        # 행동 순계 (§46): 하한 1(흔적 있으면 최소 1건) ≤ 순계 ≤ 호출 수
        # (로레코드) — 항목별 ON ≤ OFF 단조성 유지(§43 교훈)
        if stats.get("search_calls"):
            # §70: 하한을 세션당 1 → 검색한 지시 턴당 1로. 숙련자도 새 지시가
            # 오면 위치 확인은 한 번 한다. 착지-기여 문서 수와 큰 쪽.
            n = max(1, stats.get("search_landing_docs", 0),
                    stats.get("search_turns", 0))
            items.append({"primitive": "search",
                          "count": min(n, stats["search_calls"])})
    ex = exec_item(stats, rates, humanize_act)   # 실행 4토막 (§59)
    if ex:
        items.append(ex)
    if (draft_w or edit_w) and stats.get("verify_here", True):
        # §82: 구간 측정에서는 세션 마지막 쓰기가 속한 구간에만 1건
        # 마무리 확인 1건 — 두 모드 공통 (§43). 초기 §39는 "기록에 대응
        # 행동 없음"이라며 로레코드에서 verify를 뺐는데, 그 결과 도구 호출이
        # 1~2회뿐인 소형 세션에서 궤적 천장이 바닥 자보다 낮아지는 모순이
        # 실측 43/91건 발생. 궤적을 재연하는 사람도 산출물 확인은 하므로
        # 공통 계상 — 이로써 건수형이 항목별로 OFF ≥ ON 보장.
        items.append({"primitive": "verify", "count": 1})
    return items


def measure(jsonl_path, humanize_rw=True, humanize_act=True, rates=None,
            include_subagents=False, force=False, humanize=None,
            include_think=True, subagent_paths=None, hitl_compact=False,
            as_of=None, window=None):
    """세션 1개 → LLM 0회 분자·분모·speedup. 반환 구조는 measure_session 동일.

    humanize_rw / humanize_act: 휴먼화 2축 (build_actions 참조, §40).
    humanize: 구 인터페이스 호환 — True/False/"rawrecord"를 2축으로 변환
              (지정 시 2축 인자보다 우선).
    subagent_paths: 분자에 넣을 서브에이전트 트랜스크립트 (기본 자동 탐색,
              []로 주면 구 동작인 "서브에이전트 0원"이 된다 — §59 기여도 분해용).
    include_think: 생각 계상 (§53·§59, collect_strategy_thinking 참조).
              기본 ON — 휴먼화 2축과 독립(모든 조합에 동일 가산이라 §43
              단조성 불변). False로 구(생각 미계상) 동작.
    hitl_compact: §79 hitl 축약 모드 — 분모의 사람 확인만 바꾼다(기본 OFF).
    as_of / window: §80 구간 측정 (모듈 docstring). as_of=T면 T 이후 기록을
              잘라낸 사본으로 잰다(slice_session). window=(start, end)면
              판정은 기록 전체(as_of까지), 계상은 사건 시각이 구간 안인 것만
              (collect_record_stats·parse_actions의 count_window). as_of나
              window가 있으면 초소형 제외(§64)는 건너뛴다(force와 동일).
    """
    if humanize is not None:  # 구 인터페이스 호환 (§39 이전 소비자)
        if humanize == RAW_RECORD:
            humanize_rw, humanize_act = False, False
        else:
            humanize_rw, humanize_act = bool(humanize), True
    as_of = parse_time(as_of)
    if window is not None:
        window = (parse_time(window[0]) or 0.0, parse_time(window[1]))
        if window[1] is None:
            window = (window[0], as_of if as_of is not None else float("inf"))
        if window[0] > window[1]:
            raise ValueError(f"window start > end: {window}")
        if as_of is not None and window[1] > as_of:
            raise ValueError(f"window end {window[1]} > as_of {as_of}")
        force = True
    if as_of is not None:
        force = True   # 시점·구간 측정은 초소형 제외(§64)를 건너뛴다
        src_name = Path(jsonl_path).name
        main, subs_cut, tmpdir = slice_session(jsonl_path, as_of, subagent_paths)
        try:
            r = measure(main, humanize_rw=humanize_rw, humanize_act=humanize_act,
                        rates=rates, include_subagents=include_subagents,
                        force=force, include_think=include_think,
                        subagent_paths=subs_cut, hitl_compact=hitl_compact,
                        as_of=None, window=window)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        r["session"] = src_name
        r["window"] = {"start": window[0] if window else None,
                       "end": window[1] if window else None,
                       "as_of": as_of}
        return r
    rates = rates or load_rates()
    # 분자는 서브에이전트 몫을 포함한다 (§59 규칙1: 병렬은 분모만) —
    # subagent_paths=[]로 끄면 구 동작(전량 0원). 감사·기여도 분해용.
    subs = (list(subagent_paths) if subagent_paths is not None
            else find_subagent_files(jsonl_path))
    stats = collect_record_stats(jsonl_path, subagent_paths=subs,
                                 count_window=window)
    suspect, suspect_why = suspect_output_channel(stats)
    # §64 초소형 제외: 세션 러닝타임(첫~마지막 기록)이 5분 이하면 측정 안 함
    actual = measure_agent_actual(jsonl_path, rates, include_subagents,
                                  hitl_compact=hitl_compact,
                                  count_window=window)
    span = actual["counts"].get("session_span_min") or None
    if is_trivial_session(stats, span) and not force:
        return {"session": Path(jsonl_path).name, "excluded": True,
                "reason": (f"초소형 세션 — 러닝타임 "
                           f"{span or 0:.1f}분 (기준 5분 이하)"),
                "record_stats": stats,
                "suspect_output_channel": suspect,
                **({"suspect_reason": suspect_why} if suspect else {})}
    card = rates["human"]
    total = 0.0
    breakdown = []
    for a in build_actions(stats, rates, humanize_rw, humanize_act):
        spec = card[a["primitive"]]
        # 항목이 분을 직접 들고 오면 그대로 (§59 — 실행 4토막·쓰기 종류별
        # 요율처럼 단일 요율로 환원 안 되는 계산)
        minutes = a["minutes"] if "minutes" in a \
            else a["count"] * spec["min_per_unit"]
        total += minutes
        row = {"primitive": a["primitive"], "count": a["count"],
               "unit": a.get("unit", spec["unit"]),
               "minutes": round(minutes, 2)}
        if a.get("detail"):
            row["detail"] = a["detail"]
        breakdown.append(row)
    think_info = None
    if include_think:  # 전략 생각 (§53) — 휴먼화 축과 독립, 기본 ON
        st = collect_strategy_thinking(jsonl_path, subs, count_window=window)
        spec = card.get("think") or _THINK_DEFAULT_SPEC
        # 구 포맷 지점은 건당 고정 분(§58) — 요율에 무관하게 같은 시간이
        # 되도록 분을 단어로 역환산해 더한다(breakdown 단위 일관성 유지).
        fb_words = (st["fallback_points"] * THINK_FALLBACK_MIN
                    / spec["min_per_unit"]) if st["fallback_points"] else 0.0
        # 전략 생각(지시 직후 첫 응답)만 계상 — 도구 중간 생각은 집계만
        # 하고 분자에 넣지 않는다(§53 숙련자 가정 유지). 미계상 크기는
        # think.mid_tokens로 그대로 보고된다.
        # §68: 서브에이전트가 부모에게 낸 보고문(전량)은 밖으로 나온 생각 —
        # think 요율로 가산. 직접 생각(토큰×0.005) ≈ 위임(서브 생각 토큰×0.005
        # + 보고 단어×0.005)이 되어 위임 여부에 값이 안 흔들린다.
        rep_words = stats.get("sub_report_words", 0)
        # §73: 메인 진행 나레이션(마무리 답변 제외 assistant 텍스트)도 §68과
        # 같은 논리 — 사람이 혼자 했다면 속으로 정리한 것 = 밖으로 나온 생각.
        narr_words = stats.get("narration_words", 0)
        strat_words = round(st["tokens"] * THINK_TOK2WORD, 1)
        think_words = round(strat_words + fb_words + rep_words + narr_words, 1)
        if think_words:
            minutes = think_words * spec["min_per_unit"]
            total += minutes
            breakdown.append({"primitive": "think", "count": think_words,
                              "unit": spec.get("unit", "word_count"),
                              "minutes": round(minutes, 2),
                              "detail": {"strategy_words": strat_words,
                                         "fallback_words": round(fb_words, 1),
                                         "sub_report_words": rep_words,
                                         "narration_words": narr_words}})
        think_info = dict(st)
        think_info["sub_report_words"] = rep_words
        think_info["narration_words"] = narr_words
    h_min = round(total, 2)
    audit = channel_audit(stats)
    notes = [suspect_why] if suspect else []
    # §76 절감율 하한 — 분자 바닥 = agent_total × HUMAN_FLOOR_RATIO
    h_raw = h_min
    if SAVINGS_FLOOR is not None:
        h_floor = round(actual["total_min"] * HUMAN_FLOOR_RATIO, 2)
        if h_min < h_floor:
            h_min = h_floor
            notes.append(
                f"절감율 하한 {SAVINGS_FLOOR * 100:.0f}% 적용 — 분자 실측 "
                f"{h_raw:.1f}분 → 바닥 {h_floor:.1f}분 (agent "
                f"{actual['total_min']:.1f}분 × {HUMAN_FLOOR_RATIO:.3f}, §76)")
    if audit["warn"]:
        notes.append(
            "미계상 채널 " + ", ".join(f"{k} {v:,}" for k, v in
                                   audit["uncounted"].items())
            + " — 분자 과소 가능 (§59 채널 결산)")
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
                  "automation_saved_min": actual.get("automation_saved_min", 0.0),
                  "hitl_compact": hitl_compact,
                  "subagent_files": actual["subagent_files"]},
        "speedup": speedup(h_min, actual["total_min"]),
        "speedup_vs_hitl": speedup(h_min, actual["hitl_min"]),
        "channel_audit": audit,
        "notes": notes,
        **({"window": {"start": window[0], "end": window[1], "as_of": None}}
           if window else {}),
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
    opts = {}
    rest = []
    i = 0
    while i < len(argv):   # §80 값 있는 옵션
        if argv[i] in ("--as-of", "--from", "--to") and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    argv = rest
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: python record_actions_code_api.py <session.jsonl> [...] "
              "[--norw] [--noact] [--nothink] [--hitl-compact] [--json] "
              "[--as-of T] [--from A] [--to B]   "
              "(--raw=--norw, --rawrecord=--norw --noact 호환; T/A/B = ISO 8601 "
              "또는 epoch 초, tz 없으면 로컬)",
              file=sys.stderr)
        return 2
    rw = not ("--norw" in argv or "--raw" in argv or "--rawrecord" in argv)
    act = not ("--noact" in argv or "--rawrecord" in argv)
    think = "--nothink" not in argv
    compact = "--hitl-compact" in argv
    window = None
    if "--from" in opts or "--to" in opts:
        window = (opts.get("--from", 0), opts.get("--to"))
    rows = measure_batch(paths, humanize_rw=rw, humanize_act=act,
                         include_think=think, hitl_compact=compact,
                         as_of=opts.get("--as-of"), window=window)
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
