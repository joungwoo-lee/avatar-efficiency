# -*- coding: utf-8 -*-
"""사용량 CSV(한 줄 = 한 사람) → 사람 노동 환산 + 효율 지표 리포트.

입력 CSV 에서 쓰는 컬럼:
    employee_id      사람 식별자
    lines_added      추가 라인 수
    lines_removed    삭제 라인 수
    cli_active_sec   CC 세션 시간(초)
    user_active_sec  사용자 세션 시간(초)
    total_cost       달러 비용

출력 지표 (사람마다):
    effort_min   = diff_effort(추가, 삭제)                      [분]
    x_total      = effort_min / ((cli_active_sec + user_active_sec) / 60)
    x_user       = effort_min / (user_active_sec / 60)
    min_per_usd  = effort_min / total_cost                      [분/$]

x_total·x_user 는 "사람이 직접 짰다면 걸렸을 시간 ÷ 실제 흘러간 시간"이라
배율(무단위)이고, min_per_usd 는 1달러가 사온 사람 노동의 분이다.

경고: 원시 CSV 의 lines_added/removed 는 주석·빈 줄·자동생성 파일을
포함한 값이라 절대 시간으로 읽으면 크게 과대다. 또 사람 단위 총합에
교체 쌍 제거를 걸면 삭제 몫이 흡수돼 사라진다(커밋 단위 분해가 정석).
README.md §4 한계를 읽고 쓸 것 — 사람 간 상대 비교 용도.

    python csv_report.py usage.csv
    python csv_report.py usage.csv --band slow --sort x_user
    python csv_report.py usage.csv --out report.csv
    python csv_report.py usage.csv --json
"""
import argparse
import csv
import json
import sys

from diff_effort import BANDS, DEFAULT_BAND, diff_effort, rates

REQUIRED = ("employee_id", "lines_added", "lines_removed",
            "cli_active_sec", "user_active_sec", "total_cost")

FIELDS = ("employee_id", "lines_added", "lines_removed", "file_deleted_lines",
          "effort_min", "effort_hours", "cli_active_sec", "user_active_sec",
          "total_cost", "x_total", "x_user", "min_per_usd")

SORT_KEYS = ("effort_min", "x_total", "x_user", "min_per_usd",
             "lines_added", "employee_id")


def _num(row, key, default=0.0):
    """CSV 셀 -> float. 빈 값·쉼표·따옴표를 견딘다."""
    v = (row.get(key) or "").strip().replace(",", "").replace('"', "")
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _ratio(num, den):
    """0 나눗셈은 None (출력에서 '-')."""
    if not den:
        return None
    return num / den


def analyze_row(row, band=DEFAULT_BAND, file_deleted_col=None):
    """CSV 한 줄 -> 지표 dict."""
    added = int(_num(row, "lines_added"))
    removed = int(_num(row, "lines_removed"))
    scrap = int(_num(row, file_deleted_col)) if file_deleted_col else 0
    scrap = min(scrap, removed)

    eff = diff_effort(added, removed, scrap, band)
    minutes = eff["minutes"]

    cli_s = _num(row, "cli_active_sec")
    user_s = _num(row, "user_active_sec")
    cost = _num(row, "total_cost")

    return {
        "employee_id": (row.get("employee_id") or "").strip(),
        "lines_added": added,
        "lines_removed": removed,
        "file_deleted_lines": scrap,
        "effort_min": minutes,
        "effort_hours": eff["hours"],
        "cli_active_sec": cli_s,
        "user_active_sec": user_s,
        "total_cost": cost,
        "x_total": _ratio(minutes, (cli_s + user_s) / 60.0),
        "x_user": _ratio(minutes, user_s / 60.0),
        "min_per_usd": _ratio(minutes, cost),
    }


def analyze_csv(path, band=DEFAULT_BAND, file_deleted_col=None,
                encoding="utf-8-sig"):
    """CSV 파일 -> [지표 dict]. 필수 컬럼이 없으면 ValueError."""
    with open(path, newline="", encoding=encoding) as f:
        r = csv.DictReader(f)
        cols = set(r.fieldnames or [])
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise ValueError("CSV 에 필수 컬럼이 없다: %s" % ", ".join(missing))
        return [analyze_row(row, band, file_deleted_col) for row in r
                if (row.get("employee_id") or "").strip()]


def totals(rows):
    """전 인원 합계 — 비율은 합계끼리 다시 나눈다(평균의 평균 금지)."""
    if not rows:
        return None
    s_min = sum(r["effort_min"] for r in rows)
    s_cli = sum(r["cli_active_sec"] for r in rows)
    s_user = sum(r["user_active_sec"] for r in rows)
    s_cost = sum(r["total_cost"] for r in rows)
    return {
        "employee_id": "TOTAL(n=%d)" % len(rows),
        "lines_added": sum(r["lines_added"] for r in rows),
        "lines_removed": sum(r["lines_removed"] for r in rows),
        "file_deleted_lines": sum(r["file_deleted_lines"] for r in rows),
        "effort_min": round(s_min, 1),
        "effort_hours": round(s_min / 60.0, 2),
        "cli_active_sec": s_cli,
        "user_active_sec": s_user,
        "total_cost": s_cost,
        "x_total": _ratio(s_min, (s_cli + s_user) / 60.0),
        "x_user": _ratio(s_min, s_user / 60.0),
        "min_per_usd": _ratio(s_min, s_cost),
    }


def sort_rows(rows, key="effort_min", asc=False):
    """제자리 정렬. 값이 없는 줄(0 나눗셈)은 방향과 무관하게 항상 끝으로."""
    if key == "employee_id":
        rows.sort(key=lambda x: x["employee_id"], reverse=not asc)
        return rows
    miss = float("inf") if asc else float("-inf")
    rows.sort(key=lambda x: miss if x[key] is None else x[key],
              reverse=not asc)
    return rows


def _f(v, spec="%.1f"):
    return "-" if v is None else spec % v


def print_total_block(tot):
    """전 인원 합산 — 비율 3종을 식과 함께 따로 찍는다.

    각 비율은 '합계 ÷ 합계'다. 사람별 비율의 평균이 아니다 — 라인 수가
    많은 사람이 그만큼 더 반영되는 게 맞다.
    """
    sess_min = (tot["cli_active_sec"] + tot["user_active_sec"]) / 60.0
    user_min = tot["user_active_sec"] / 60.0
    print()
    print("[전체 합산 %s]" % tot["employee_id"])
    print("  사람노동 합                 %14.1f 분  (%.1f 시간)"
          % (tot["effort_min"], tot["effort_hours"]))
    print("  CC+사용자 세션시간 합       %14.1f 분  (%.1f 시간)"
          % (sess_min, sess_min / 60.0))
    print("  사용자 세션시간 합          %14.1f 분  (%.1f 시간)"
          % (user_min, user_min / 60.0))
    print("  달러비용 합                 %14.2f $" % tot["total_cost"])
    print("  ----")
    print("  사람노동합 / (CC+사용자)세션시간합 = %s 배"
          % _f(tot["x_total"], "%.2f"))
    print("  사람노동합 / 사용자세션시간합      = %s 배"
          % _f(tot["x_user"], "%.2f"))
    print("  사람노동합 / 달러비용합            = %s 분/$"
          % _f(tot["min_per_usd"], "%.2f"))


def print_table(rows, band, tot=None):
    r = rates(band)
    idw = max([len(x["employee_id"]) for x in rows] + [11])
    if tot:
        idw = max(idw, len(tot["employee_id"]))
    fmt = "%-*s %10d %10d %12.1f %10.1f %10s %10s %12s"
    head = ("%-*s %10s %10s %12s %10s %10s %10s %12s"
            % (idw, "employee_id", "added", "removed", "effort_min",
               "effort_h", "x_total", "x_user", "min_per_usd"))
    print("band=%s  (요율: 작성 %.3f분/줄, 삭제 %.3f분/줄)"
          % (band, r["new_min_per_line"], r["delete_min_per_line"]))
    print(head)
    print("-" * len(head))
    for x in rows:
        print(fmt % (idw, x["employee_id"], x["lines_added"],
                     x["lines_removed"], x["effort_min"], x["effort_hours"],
                     _f(x["x_total"]), _f(x["x_user"]), _f(x["min_per_usd"])))
    if tot:
        print("-" * len(head))
        print(fmt % (idw, tot["employee_id"], tot["lines_added"],
                     tot["lines_removed"], tot["effort_min"],
                     tot["effort_hours"], _f(tot["x_total"]),
                     _f(tot["x_user"]), _f(tot["min_per_usd"])))
    print()
    print("effort_min  사람이 직접 짰다면 걸릴 노동 (분)")
    print("x_total     사람노동 / (CC세션시간 + 사용자세션시간)  [배]")
    print("x_user      사람노동 / 사용자세션시간                 [배]")
    print("min_per_usd 사람노동 / 달러비용                       [분/$]")
    if tot:
        print_total_block(tot)
    print()
    print("주의: 원시 라인 수는 주석·빈 줄·자동생성 파일을 포함한다.")
    print("      절대 시간으로 읽지 말고 사람 간 상대 비교로 쓸 것 (README §4).")


def write_csv(rows, path, tot=None):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for x in rows:
            w.writerow(x)
        if tot:
            w.writerow(tot)


def _main():
    p = argparse.ArgumentParser(
        description="사용량 CSV → 사람별 사람노동 환산 + 효율 지표")
    p.add_argument("csv_path", help="입력 CSV 경로")
    p.add_argument("--band", choices=BANDS, default=DEFAULT_BAND,
                   help="생산성 밴드 (기본 mid)")
    p.add_argument("--file-deleted-col", default=None,
                   help="'파일 통째 삭제' 라인 수 컬럼명 (있을 때만)")
    p.add_argument("--sort", choices=SORT_KEYS, default="effort_min",
                   help="정렬 키 (기본 effort_min 내림차순)")
    p.add_argument("--asc", action="store_true", help="오름차순으로")
    p.add_argument("--encoding", default="utf-8-sig", help="CSV 인코딩")
    p.add_argument("--out", default=None, help="결과를 CSV 로 저장할 경로")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    p.add_argument("--no-total", action="store_true", help="합계 줄 생략")
    a = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        rows = analyze_csv(a.csv_path, a.band, a.file_deleted_col, a.encoding)
    except (OSError, ValueError) as e:
        sys.stderr.write("오류: %s\n" % e)
        return 2
    if not rows:
        sys.stderr.write("오류: employee_id 가 있는 줄이 없다\n")
        return 2

    sort_rows(rows, a.sort, a.asc)
    tot = None if a.no_total else totals(rows)

    if a.out:
        write_csv(rows, a.out, tot)

    if a.json:
        print(json.dumps({"band": a.band, "rows": rows, "total": tot},
                         ensure_ascii=False, indent=2))
    else:
        print_table(rows, a.band, tot)
        if a.out:
            print("\n저장: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
