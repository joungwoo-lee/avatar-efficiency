# -*- coding: utf-8 -*-
"""전 세션 효율 리포트 — record-actions w/o LLM(휴먼화 ON), 마크다운 출력.

이 PC의 Claude Code 세션 전체(~/.claude/projects, 서브에이전트 기록 제외)를
LLM 0회로 측정해 마크다운 리포트를 만든다:
  ① 요약 — 휴먼화 2축(rw·act) 4조합 평균·효율 비교 + 효과 분해(act/rw),
     효율 분포 히스토그램(기본 자 기준)
  ② 디테일 — 측정한 모든 세션의 표 (agent + 4조합 human·speedup 병기)

사용:
    python report_all_sessions.py                     # 기본 루트, stdout 출력
    python report_all_sessions.py --out report.md     # 파일로 저장
    python report_all_sessions.py D:\\other\\projects  # 루트 지정
    python report_all_sessions.py --hitl-compact      # §79 hitl 축약 모드로 분모
"""
import glob
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from record_actions_code_api import measure  # noqa: E402

DEFAULT_ROOT = os.path.join(str(Path.home()), ".claude", "projects")


ACTIVE_GRACE_SEC = 600  # 최근 10분 내 갱신된 세션 = 진행 중 — 측정 제외


def is_ai_invoked(jsonl_path):
    """AI(프로그램)가 SDK/헤드리스로 돌린 세션인가 (§54). 결정론.

    사람이 터미널에서 연 세션은 첫 user 레코드가 entrypoint="cli"·
    promptSource="typed"로, 프로그램이 claude CLI를 SDK로 호출해 돌린
    세션(예: 측정기 자신의 견적 엔진 구동)은 entrypoint="sdk-cli"·
    promptSource="sdk"로 기록된다. 후자는 사람의 업무 세션이 아니므로
    전 세션 집계에서 제외 — 서브에이전트 제외와 같은 원리(AI가 시킨
    일은 그걸 시킨 세션의 분모에 이미 비용으로 잡혀 있거나, 애초에
    측정 모집단이 아니다). 필드가 없는 구 기록은 사람 세션으로 간주
    (제외는 직접 증거가 있을 때만 — 보수적).
    """
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") == "user":
                    return (rec.get("entrypoint") == "sdk-cli"
                            or rec.get("promptSource") == "sdk")
    except OSError:
        pass
    return False


def collect(root, hitl_compact=False):
    import time
    files = [f for f in glob.glob(os.path.join(root, "**", "*.jsonl"),
                                  recursive=True)
             if f"{os.sep}subagents{os.sep}" not in f]
    # 진행 중 세션 제외 (§44): 기록이 아직 자라는 세션을 측정에 넣으면
    # 실행할 때마다 합계·분포가 흔들린다 — 완결된 세션만 잰다.
    now = time.time()
    active = [f for f in files
              if now - os.path.getmtime(f) < ACTIVE_GRACE_SEC]
    files = [f for f in files if f not in active]
    # AI 호출 세션 제외 (§54): 프로그램이 SDK로 돌린 세션(견적 엔진 구동
    # 등)은 사람의 업무 세션이 아니다 — 서브에이전트 제외와 같은 원리.
    ai_invoked = [f for f in files if is_ai_invoked(f)]
    files = [f for f in files if f not in ai_invoked]
    rows = []
    n_excl = n_err = n_excl_suspect = 0
    for f in files:
        try:
            on = measure(f, hitl_compact=hitl_compact)
            if on.get("excluded"):
                n_excl += 1
                if on.get("suspect_output_channel"):
                    n_excl_suspect += 1
                continue
            hc = {"hitl_compact": hitl_compact}
            rwoff = measure(f, humanize_rw=False, **hc)               # rw만 끔
            actoff = measure(f, humanize_act=False, **hc)             # act만 끔
            raw = measure(f, humanize_rw=False, humanize_act=False, **hc)  # 로레코드
            hb = on["agent"]["breakdown"]["hitl"]
            rows.append({"session": on["session"],
                         "agent": on["agent"]["total_min"],
                         # 민감도용 분해 (§49): machine+instruct는 고정
                         # (instruct는 실측 보정), seed 요율(review·correct)만
                         # 0.5×/1×/2×로 흔든다
                         "agent_fixed": (on["agent"]["machine_min"]
                                         + hb.get("instruct", 0)),
                         "agent_seed": (hb.get("review", 0)
                                        + hb.get("correct", 0)),
                         "h_on": on["human"]["min"], "sp_on": on["speedup"] or 0,
                         "h_rwoff": rwoff["human"]["min"],
                         "sp_rwoff": rwoff["speedup"] or 0,
                         "h_actoff": actoff["human"]["min"],
                         "sp_actoff": actoff["speedup"] or 0,
                         "h_raw": raw["human"]["min"],
                         "sp_raw": raw["speedup"] or 0,
                         "suspect": on.get("suspect_output_channel", False),
                         "suspect_why": (on.get("notes") or [""])[0]})
        except Exception:
            n_err += 1
    return (rows, n_excl, n_err, n_excl_suspect, len(active),
            len(ai_invoked))


def histogram(series):
    """{조합이름: [효율값...]} → 조합별 효율 구간 개수 표 (마크다운 줄 목록)."""
    hist = {}
    for name, values in series.items():
        b = {}
        for s in values:
            b[min(int(s), 10)] = b.get(min(int(s), 10), 0) + 1
        hist[name] = b
    top = max((k for b in hist.values() for k in b), default=0)
    lines = ["| 범위 | " + " | ".join(hist) + " |",
             "|---|" + "---|" * len(hist)]
    for k in range(0, top + 1):
        lbl = f"{k}.x" if k < 10 else "10.x+"
        lines.append(f"| {lbl} | "
                     + " | ".join(str(hist[h].get(k, 0)) for h in hist) + " |")
    return lines


def render(rows, n_excl, n_err, n_excl_suspect, n_active, n_ai, root,
           hitl_compact=False):
    n = len(rows)
    if not n:
        return f"측정 가능한 세션 없음 (제외 {n_excl}, 실패 {n_err})"
    suspects = [r for r in rows if r["suspect"]]
    avg = {k: sum(r[k] for r in rows) / n
           for k in ("h_on", "h_rwoff", "h_actoff", "h_raw")}
    agent_sum = sum(r["agent"] for r in rows)
    total = {k: sum(r[k] for r in rows)
             for k in ("h_on", "h_rwoff", "h_actoff", "h_raw")}
    n_diff = sum(1 for r in rows if abs(r["h_rwoff"] - r["h_on"]) > 0.005)
    med_agent = statistics.median(r["agent"] for r in rows)
    big = [r["h_rwoff"] - r["h_on"] for r in rows if r["agent"] > med_agent]
    small = [r["h_rwoff"] - r["h_on"] for r in rows if r["agent"] <= med_agent]
    sps = [r["sp_on"] for r in rows]

    out = [
        f"# 세션 효율 리포트 — record-actions w/o LLM (휴먼화 2축 4조합)"
        + (" — **hitl 축약 모드** (§79)" if hitl_compact else ""),
        "",
        f"- 측정일: {date.today().isoformat()}  |  루트: `{root}`",
        f"- 측정 {n}세션 (초소형 제외 {n_excl}, 진행 중 제외 {n_active}, "
        f"AI 호출 세션 제외 {n_ai}, 실패 {n_err}"
        + (f", **⚠ 쓰기 툴 포맷 의심 {len(suspects)}건"
           + (f"+제외분 {n_excl_suspect}건" if n_excl_suspect else "") + "**"
           if (suspects or n_excl_suspect) else "")
        + ") — LLM 0회, 결정론",
        "",
        "## 4조합 비교 — 휴먼화 2축(rw=읽기·쓰기, act=행동 건수)",
        "",
        "| 조합 | 사람시간 평균 | 효율 평균 | 전체 효율 (휴먼 합산 ÷ 에이전트 합산) |",
        "|---|---|---|---|",
    ] + [
        f"| {label} | {avg[hk]:.1f}min "
        + ("(raw)" if hk == "h_raw" else
           f"(raw대비 −{100 * (avg['h_raw'] - avg[hk]) / avg['h_raw']:.1f}%)")
        + f" | {sum(r[sk] for r in rows) / n:.2f}"
        + f" | {total[hk] / agent_sum:.2f} "
        f"({total[hk]:.0f} ÷ {agent_sum:.0f}min) |"
        for label, hk, sk in (
            ("rw ON · act ON", "h_on", "sp_on"),
            ("rw OFF · act ON", "h_rwoff", "sp_rwoff"),
            ("rw ON · act OFF", "h_actoff", "sp_actoff"),
            ("rw OFF · act OFF", "h_raw", "sp_raw"))
    ] + [
        "",
        "효과 분해 (평균): "
        f"**act 효과(행동 건수) {avg['h_actoff'] - avg['h_on']:.1f}min** / "
        f"**rw 효과(읽기·쓰기) {avg['h_rwoff'] - avg['h_on']:.1f}min** / "
        f"총효과 {avg['h_raw'] - avg['h_on']:.1f}min "
        f"(+{100 * (avg['h_raw'] - avg['h_on']) / avg['h_on']:.0f}%)",
        "",
        f"{n_diff}개 세션에서 rw ON/OFF 차이 발생. 대형 세션(agent 중앙값 "
        f"{med_agent:.1f}min 초과) 평균 차이 "
        f"{sum(big) / len(big) if big else 0:.1f}min vs 소형 "
        f"{sum(small) / len(small) if small else 0:.1f}min "
        "(번복 소거 + 등급 분해 효과는 대형 세션에 집중).",
        "",
        "## hitl seed 요율 민감도 (0.5× / 1× / 2×)",
        "",
        "분모의 사람 감독 중 **미보정 seed 요율(review·correct)만** 흔든 전체"
        " 효율(휴먼 합산 ÷ 에이전트 합산, rw ON·act ON). instruct는 실측"
        " 보정(지시 1,456건)이라 고정, 기계 시간도 고정. 절대값 불확실성을"
        " 숨기지 않으면서 상대 결론의 강건성을 보이기 위함(§49).",
        "",
        "| seed 배율 | 에이전트 합산(min) | 전체 효율 |",
        "|---|---|---|",
    ] + [
        (lambda d: f"| {k}× | {d:.0f} | {total['h_on'] / d:.2f} |")(
            sum(r["agent_fixed"] + k * r["agent_seed"] for r in rows))
        for k in (0.5, 1, 2)
    ] + [
        "",
        "## 효율값 구간별 개수 (4조합)",
        "",
    ]
    out += histogram({
        "rwON·actON": sps,
        "rwOFF·actON": [r["sp_rwoff"] for r in rows],
        "rwON·actOFF": [r["sp_actoff"] for r in rows],
        "rwOFF·actOFF": [r["sp_raw"] for r in rows]})
    out += [
        "",
        "## 디테일 — 전체 측정 표 (agent 시간 큰 순, min/효율)",
        "",
        "| 세션 | agent(min) | rwON·actON | 효율 | rwOFF·actON | 효율 "
        "| rwON·actOFF | 효율 | rwOFF·actOFF | 효율 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: -r["agent"]):
        mark = "⚠ " if r["suspect"] else ""
        out.append(f"| {mark}{r['session'][:16]} | {r['agent']:.1f} "
                   f"| {r['h_on']:.1f} | {r['sp_on']:.2f} "
                   f"| {r['h_rwoff']:.1f} | {r['sp_rwoff']:.2f} "
                   f"| {r['h_actoff']:.1f} | {r['sp_actoff']:.2f} "
                   f"| {r['h_raw']:.1f} | {r['sp_raw']:.2f} |")
    if suspects:
        out += [
            "",
            "## ⚠ 쓰기 툴 포맷 미등록 의심 세션",
            "",
            "이 세션들은 **미등록 도구의 입력에 글이 실려 나갔는데 응답은 "
            "짧은 확인뿐**이고 잡힌 산출물(파일+답변+JSON)도 없다 — 산출물이 "
            "그 도구로 제출됐을 직접 증거가 있어 **사람 시간·효율이 과소일 "
            "수 있다.** 근거의 도구 이름을 측정기에 쓰기 채널로 등록하면 "
            "해소된다.",
            "",
            "| 세션 | 효율 ON | 근거 |",
            "|---|---|---|",
        ]
        for r in sorted(suspects, key=lambda r: r["sp_on"]):
            out.append(f"| {r['session'][:16]} | {r['sp_on']:.2f} "
                       f"| {r['suspect_why']} |")
    return "\n".join(out)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    compact = "--hitl-compact" in argv
    argv = [a for a in argv if a != "--hitl-compact"]
    root = argv[0] if argv else DEFAULT_ROOT
    report = render(*collect(root, hitl_compact=compact), root=root,
                    hitl_compact=compact)
    if out_path:
        Path(out_path).write_text(report, encoding="utf-8")
        print(f"저장: {out_path}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
