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
    x_ai_time        = effort_min / (cli_active_sec / 60)
    x_total      = effort_min / ((cli_active_sec + user_active_sec) / 60)
    x_user_time       = effort_min / (user_active_sec / 60)
    min_per_usd  = effort_min / total_cost                      [분/$]

전 인원 합산도 같은 네 식을 합계끼리 나눠 따로 찍는다.

보정 계수는 **ratios.json 에서 읽는다.** measure_ratios.py 로 대상
저장소를 한 번 재면 그 파일이 생기고, 이 스크립트가 자동으로 집어
쓴다. 손으로 플래그를 옮길 필요가 없다.

    python measure_ratios.py <저장소>     # ratios.json 생성
    python csv_report.py usage.csv        # 자동으로 읽어 보정 적용

    python csv_report.py usage.csv --config other/ratios.json
    python csv_report.py usage.csv --no-config        # 보정 없이 (과대)
    python csv_report.py usage.csv --band slow --sort x_user_time --out r.csv

계수 세 개가 하는 일:
    mix (코드/문서/데이터 구성비)  전부 코드 요율로 치면 문서·데이터를
                                   과대 계상한다 -> 실효 요율 배수
    comment_ratio, generated_ratio 주석·빈 줄·자동생성물을 걷어낸다.
                                   요율이 non-comment LOC 기준이라 필요.

플래그로 직접 줄 수도 있고(--mix/--comment-ratio/--generated-ratio),
그 경우 설정 파일보다 우선한다.

경고: 보정 없이 돌리면 절대 시간이 크게 과대다(대략 2배). 또 사람 단위
총합에 교체 쌍 제거를 걸면 삭제 몫이 흡수돼 사라진다(커밋 단위 분해가
정석). README.md §0·§3.5·§4 를 읽고 쓸 것.
"""
import argparse
import csv
import json
import os
import sys

from diff_effort import (BANDS, DEFAULT_BAND, KINDS, diff_effort,
                         effective_ratio, mix_factor, rates)

REQUIRED = ("employee_id", "lines_added", "lines_removed",
            "cli_active_sec", "user_active_sec", "total_cost")

FIELDS = ("employee_id", "lines_added", "lines_removed",
          "effort_min", "effort_hours", "cli_active_sec", "user_active_sec",
          "total_cost", "x_ai_time", "x_total", "x_user_time", "min_per_usd")

SORT_KEYS = ("effort_min", "x_ai_time", "x_total", "x_user_time", "min_per_usd",
             "lines_added", "employee_id")


_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(_HERE, "ratios.json")


def find_config(explicit=None):
    """설정 파일 경로를 정한다 — 명시 > 현재 폴더 > 스크립트 폴더."""
    if explicit:
        if not os.path.exists(explicit):
            raise ValueError("설정 파일이 없다: %s" % explicit)
        return explicit
    for cand in (os.path.join(os.getcwd(), "ratios.json"), DEFAULT_CONFIG):
        if os.path.exists(cand):
            return cand
    return None


def load_config(path):
    """ratios.json -> (mix_parts, comment_ratio, generated_ratio, cfg)."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    m = cfg.get("mix") or {}
    parts = [float(m.get(k, 0.0)) for k in KINDS]
    if sum(parts) <= 0:
        raise ValueError("설정의 mix 합이 0이다: %s" % path)
    return (parts, float(cfg.get("comment_ratio", 0.0)),
            float(cfg.get("generated_ratio", 0.0)), cfg)


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


def analyze_row(row, band=DEFAULT_BAND, mix=None, eff_ratio=1.0):
    """CSV 한 줄 -> 지표 dict."""
    added = int(_num(row, "lines_added"))
    removed = int(_num(row, "lines_removed"))

    eff = diff_effort(added, removed, band, mix, eff_ratio)
    minutes = eff["minutes"]

    cli_s = _num(row, "cli_active_sec")
    user_s = _num(row, "user_active_sec")
    cost = _num(row, "total_cost")

    return {
        "employee_id": (row.get("employee_id") or "").strip(),
        "lines_added": added,
        "lines_removed": removed,
        "effort_min": minutes,
        "effort_hours": eff["hours"],
        "cli_active_sec": cli_s,
        "user_active_sec": user_s,
        "total_cost": cost,
        "x_ai_time": _ratio(minutes, cli_s / 60.0),
        "x_total": _ratio(minutes, (cli_s + user_s) / 60.0),
        "x_user_time": _ratio(minutes, user_s / 60.0),
        "min_per_usd": _ratio(minutes, cost),
    }


def analyze_stream(f, band=DEFAULT_BAND, mix=None, eff_ratio=1.0):
    """열린 텍스트 스트림 -> [지표 dict]. 필수 컬럼이 없으면 ValueError.

    파일이 아니라 스트림을 받는다 — 업로드된 CSV 내용처럼 디스크에 없는
    입력도 같은 코드로 처리하기 위해서다.
    """
    r = csv.DictReader(f)
    cols = set(r.fieldnames or [])
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise ValueError("CSV 에 필수 컬럼이 없다: %s" % ", ".join(missing))
    return [analyze_row(row, band, mix, eff_ratio) for row in r
            if (row.get("employee_id") or "").strip()]


def analyze_csv(path, band=DEFAULT_BAND, mix=None, eff_ratio=1.0,
                encoding="utf-8-sig"):
    """CSV 파일 -> [지표 dict]. 필수 컬럼이 없으면 ValueError."""
    with open(path, newline="", encoding=encoding) as f:
        return analyze_stream(f, band, mix, eff_ratio)


def totals(rows):
    """전 인원 합계 — 비율은 합계끼리 다시 나눈다(비율의 평균 금지)."""
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
        "effort_min": round(s_min, 1),
        "effort_hours": round(s_min / 60.0, 2),
        "cli_active_sec": s_cli,
        "user_active_sec": s_user,
        "total_cost": s_cost,
        "x_ai_time": _ratio(s_min, s_cli / 60.0),
        "x_total": _ratio(s_min, (s_cli + s_user) / 60.0),
        "x_user_time": _ratio(s_min, s_user / 60.0),
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


def print_assumptions(band, mix, eff_ratio, mix_parts, comment_r, gen_r,
                      cfg_path=None, cfg=None):
    """무엇을 가정하고 계산했는지 먼저 밝힌다 — 안 켜면 안 켰다고 찍는다."""
    r = rates(band)
    print("[가정]")
    if cfg_path:
        print("  설정          %s" % cfg_path)
        meas = (cfg or {}).get("measured") or {}
        if meas:
            repos = ", ".join(meas.get("repos") or []) or "(미기록)"
            span = " ~ ".join(x for x in (meas.get("since"),
                                          meas.get("until")) if x)
            print("                잰 대상: %s / %s"
                  % (repos, span or "전체 기간"))
            if meas.get("at"):
                print("                잰 시각: %s (기준: %s)"
                      % (meas["at"], meas.get("basis", "-")))
            if (cfg or {}).get("proxy"):
                # 예시 프로젝트로 대신 잰 값이다. 실측으로 읽히면 안 된다.
                print("                ※ 대리 측정(추정) — %s"
                      % meas.get("proxy_note", "대상 세션의 저장소가 아니다"))
    else:
        print("  설정          없음 — measure_ratios.py 로 먼저 재라")
    print("  밴드          %s — 작성 %.3f분/줄 (%.1f줄/h), "
          "삭제 %.3f분/줄 (%.0f줄/h)"
          % (band, r["new_min_per_line"], r["loc_per_hour"],
             r["delete_min_per_line"], r["delete_loc_per_hour"]))
    if mix_parts:
        tot = sum(mix_parts)
        print("  구성비        코드 %.1f%% / 문서 %.1f%% / 데이터 %.1f%%"
              " → 실효 요율 배수 %.4f"
              % (mix_parts[0] / tot * 100, mix_parts[1] / tot * 100,
                 mix_parts[2] / tot * 100, mix))
    else:
        print("  구성비        미지정 → 전부 코드 요율 (문서·데이터 과대)")
    if comment_r or gen_r:
        print("  유효 라인     주석·빈 줄 %.1f%% + 자동생성물 %.1f%% 제외"
              " → 유효 라인 비율 %.4f"
              % (comment_r * 100, gen_r * 100, eff_ratio))
    else:
        print("  유효 라인     미보정 → 주석·빈 줄·자동생성물 포함 (과대)")
    print()


def print_total_block(tot):
    """전 인원 합산 — 비율 4종을 식과 함께 따로 찍는다.

    각 비율은 '합계 ÷ 합계'다. 사람별 비율의 평균이 아니다 — 라인 수가
    많은 사람이 그만큼 더 반영되는 게 맞다.
    """
    cli_min = tot["cli_active_sec"] / 60.0
    sess_min = (tot["cli_active_sec"] + tot["user_active_sec"]) / 60.0
    user_min = tot["user_active_sec"] / 60.0
    print()
    print("[전체 합산 %s]" % tot["employee_id"])
    print("  사람노동 합                 %14.1f 분  (%.1f 시간)"
          % (tot["effort_min"], tot["effort_hours"]))
    print("  AI 세션시간 합              %14.1f 분  (%.1f 시간)"
          % (cli_min, cli_min / 60.0))
    print("  AI+사람 세션시간 합         %14.1f 분  (%.1f 시간)"
          % (sess_min, sess_min / 60.0))
    print("  사람 시간 합                %14.1f 분  (%.1f 시간)"
          % (user_min, user_min / 60.0))
    print("  달러비용 합                 %14.2f $" % tot["total_cost"])
    print("  ----")
    print("  사람노동합 / AI세션시간합          = %s 배"
          % _f(tot["x_ai_time"], "%.2f"))
    print("  사람노동합 / (AI+사람)세션시간합   = %s 배"
          % _f(tot["x_total"], "%.2f"))
    print("  사람노동합 / 사람시간합            = %s 배"
          % _f(tot["x_user_time"], "%.2f"))
    print("  사람노동합 / 달러비용합            = %s 분/$"
          % _f(tot["min_per_usd"], "%.2f"))


def print_table(rows, tot=None):
    idw = max([len(x["employee_id"]) for x in rows] + [11])
    if tot:
        idw = max(idw, len(tot["employee_id"]))
    fmt = "%-*s %10d %10d %12.1f %10.1f %10s %10s %12s %12s"
    head = ("%-*s %10s %10s %12s %10s %10s %10s %12s %12s"
            % (idw, "employee_id", "added", "removed", "effort_min",
               "effort_h", "x_ai_time", "x_total", "x_user_time", "min_per_usd"))
    print(head)
    print("-" * len(head))
    for x in rows:
        print(fmt % (idw, x["employee_id"], x["lines_added"],
                     x["lines_removed"], x["effort_min"], x["effort_hours"],
                     _f(x["x_ai_time"]), _f(x["x_total"]), _f(x["x_user_time"]),
                     _f(x["min_per_usd"])))
    if tot:
        print("-" * len(head))
        print(fmt % (idw, tot["employee_id"], tot["lines_added"],
                     tot["lines_removed"], tot["effort_min"],
                     tot["effort_hours"], _f(tot["x_ai_time"]),
                     _f(tot["x_total"]), _f(tot["x_user_time"]),
                     _f(tot["min_per_usd"])))
    print()
    print("effort_min  사람이 직접 짰다면 걸릴 노동 (분)")
    print("x_ai_time   사람노동 / AI 세션시간                    [배]")
    print("x_total     사람노동 / (AI 세션시간 + 사람시간)       [배]")
    print("x_user_time 사람노동 / 사람시간                        [배]")
    print("min_per_usd 사람노동 / 달러비용                       [분/$]")
    if tot:
        print_total_block(tot)


def write_rows(f, rows, tot=None):
    """열린 텍스트 스트림에 리포트 CSV 를 쓴다."""
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for x in rows:
        w.writerow(x)
    if tot:
        w.writerow(tot)


def csv_text(rows, tot=None):
    """리포트 CSV 를 문자열로. 파일로 못 쓰는 자리(업로드형 UI)에서 쓴다."""
    import io as _io
    buf = _io.StringIO(newline="")
    write_rows(buf, rows, tot)
    return buf.getvalue()


def write_csv(rows, path, tot=None):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        write_rows(f, rows, tot)


def _main():
    p = argparse.ArgumentParser(
        description="사용량 CSV → 사람별 사람노동 환산 + 효율 지표")
    p.add_argument("csv_path", help="입력 CSV 경로")
    p.add_argument("--band", choices=BANDS, default=DEFAULT_BAND,
                   help="생산성 밴드 (기본 mid)")
    p.add_argument("--config", default=None,
                   help="보정 계수 파일 (기본: ./ratios.json 또는 "
                        "스크립트 폴더의 ratios.json 자동 사용)")
    p.add_argument("--no-config", action="store_true",
                   help="설정 파일을 무시하고 보정 없이 돌린다 (과대)")
    p.add_argument("--mix", default=None, metavar="CODE,DOC,DATA",
                   help="구성비를 직접 지정 (설정 파일보다 우선)")
    p.add_argument("--comment-ratio", type=float, default=None,
                   help="주석·빈 줄 비율 직접 지정 (설정보다 우선)")
    p.add_argument("--generated-ratio", type=float, default=None,
                   help="자동생성물 비율 직접 지정 (설정보다 우선)")
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

    mix_parts = None
    comment_r = 0.0
    gen_r = 0.0
    cfg = None
    cfg_path = None
    try:
        if not a.no_config:
            cfg_path = find_config(a.config)
            if cfg_path:
                mix_parts, comment_r, gen_r, cfg = load_config(cfg_path)
        # 플래그는 설정 파일보다 우선
        if a.mix:
            mix_parts = [float(x) for x in a.mix.split(",")]
            if len(mix_parts) != len(KINDS):
                raise ValueError("--mix 는 CODE,DOC,DATA 세 값이어야 한다")
        if a.comment_ratio is not None:
            comment_r = a.comment_ratio
        if a.generated_ratio is not None:
            gen_r = a.generated_ratio

        mix = mix_factor(*mix_parts) if mix_parts else None
        er = effective_ratio(comment_r, gen_r)
        rows = analyze_csv(a.csv_path, a.band, mix, er, a.encoding)
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
        print(json.dumps({
            "band": a.band,
            "config_path": cfg_path,
            "config": cfg,
            "mix": mix if mix is not None else 1.0,
            "mix_parts": mix_parts,
            "eff_ratio": er,
            "comment_ratio": comment_r,
            "generated_ratio": gen_r,
            "rows": rows, "total": tot}, ensure_ascii=False, indent=2))
    else:
        print_assumptions(a.band, mix if mix is not None else 1.0, er,
                          mix_parts, comment_r, gen_r, cfg_path, cfg)
        print_table(rows, tot)
        if not mix_parts and not (comment_r or gen_r):
            print()
            print("주의: 보정 없이 돌렸다 — 절대 시간이 대략 2배 과대다.")
            print("      measure_ratios.py <저장소> 로 먼저 재라 (README §0).")
        if a.out:
            print("\n저장: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
