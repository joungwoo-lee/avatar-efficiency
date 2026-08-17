# -*- coding: utf-8 -*-
"""전 세션 효율 리포트 — record-actions w/o LLM(휴먼화 ON), 마크다운 출력.

이 PC의 Claude Code 세션 전체(~/.claude/projects, 서브에이전트 기록 제외)를
LLM 0회로 측정해 마크다운 리포트를 만든다:
  ① 요약 리포트 — 휴먼화 ON/OFF 평균·차이, 효율 분포 히스토그램
  ② 디테일 — 측정한 모든 세션의 표 (agent·human·speedup, ON/OFF 병기)

사용:
    python report_all_sessions.py                     # 기본 루트, stdout 출력
    python report_all_sessions.py --out report.md     # 파일로 저장
    python report_all_sessions.py D:\\other\\projects  # 루트 지정
"""
import glob
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


def collect(root):
    files = [f for f in glob.glob(os.path.join(root, "**", "*.jsonl"),
                                  recursive=True)
             if f"{os.sep}subagents{os.sep}" not in f]
    rows = []
    n_excl = n_err = 0
    for f in files:
        try:
            on = measure(f)
            if on.get("excluded"):
                n_excl += 1
                continue
            off = measure(f, humanize=False)
            rows.append({"session": on["session"],
                         "agent": on["agent"]["total_min"],
                         "h_on": on["human"]["min"], "sp_on": on["speedup"] or 0,
                         "h_off": off["human"]["min"],
                         "sp_off": off["speedup"] or 0})
        except Exception:
            n_err += 1
    return rows, n_excl, n_err


def histogram(values):
    buckets = {}
    for s in values:
        buckets[min(int(s), 10)] = buckets.get(min(int(s), 10), 0) + 1
    lines = ["| 범위 | 개수 |", "|---|---|"]
    for b in range(0, 11):
        if b in buckets:
            lines.append(f"| {f'{b}.x' if b < 10 else '10.x+'} | {buckets[b]} |")
    return lines


def render(rows, n_excl, n_err, root):
    n = len(rows)
    if not n:
        return f"측정 가능한 세션 없음 (제외 {n_excl}, 실패 {n_err})"
    avg_on = sum(r["h_on"] for r in rows) / n
    avg_off = sum(r["h_off"] for r in rows) / n
    diff = avg_off - avg_on
    n_diff = sum(1 for r in rows if abs(r["h_off"] - r["h_on"]) > 0.005)
    med_agent = statistics.median(r["agent"] for r in rows)
    big = [r["h_off"] - r["h_on"] for r in rows if r["agent"] > med_agent]
    small = [r["h_off"] - r["h_on"] for r in rows if r["agent"] <= med_agent]
    sps = [r["sp_on"] for r in rows]

    out = [
        f"# 세션 효율 리포트 — record-actions w/o LLM (휴먼화 ON)",
        "",
        f"- 측정일: {date.today().isoformat()}  |  루트: `{root}`",
        f"- 측정 {n}세션 (초소형 제외 {n_excl}, 실패 {n_err}) — LLM 0회, 결정론",
        "",
        "## 휴먼화(읽기 등급 분해 + 쓰기 번복 소거) 효과",
        "",
        "| | 평균 |",
        "|---|---|",
        f"| humanize ON | {avg_on:.1f}min |",
        f"| humanize OFF | {avg_off:.1f}min |",
        f"| 차이 | **+{diff:.1f}min (+{100 * diff / avg_on:.1f}%)** |",
        "",
        f"{n_diff}개 세션에서 차이 발생. 대형 세션(agent 중앙값 "
        f"{med_agent:.1f}min 초과) 평균 차이 "
        f"{sum(big) / len(big) if big else 0:.1f}min vs 소형 "
        f"{sum(small) / len(small) if small else 0:.1f}min "
        "(번복 소거 + 등급 분해 효과는 대형 세션에 집중).",
        "",
        "## 효율값 (휴먼화 ON)",
        "",
        f"avg: {sum(sps) / n:.2f}  |  중앙값: {statistics.median(sps):.2f}",
        "",
    ]
    out += histogram(sps)
    out += [
        "",
        "## 디테일 — 전체 측정 표 (agent 시간 큰 순)",
        "",
        "| 세션 | agent(min) | human ON(min) | 효율 ON | human OFF(min) | 효율 OFF |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: -r["agent"]):
        out.append(f"| {r['session'][:16]} | {r['agent']:.1f} "
                   f"| {r['h_on']:.1f} | {r['sp_on']:.2f} "
                   f"| {r['h_off']:.1f} | {r['sp_off']:.2f} |")
    return "\n".join(out)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    root = argv[0] if argv else DEFAULT_ROOT
    report = render(*collect(root), root=root)
    if out_path:
        Path(out_path).write_text(report, encoding="utf-8")
        print(f"저장: {out_path}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
