# -*- coding: utf-8 -*-
"""코드 라인 변경수(추가/삭제) → 사람 노동 환산 모듈.

세션 기록 없이 **diff 라인 수만** 있을 때 쓰는 독립 환산기다.
근거·유도는 README.md 참조.

    분 = 추가줄 × W_new
       + 순삭제(부분) × W_del
       + 삭제(파일 통째) × W_scrap

이 모듈은 자기완결이다 — ../agent-effort/rates.json 을 읽지 않고
자체 상수를 쓴다. 세션 기반 측정기(../session-api)와 요율 체계가
다르므로 (아래 '이중계상 주의') 섞어 쓰면 안 된다.

이중계상 주의: W_new 안에 이해·탐색·시험이 이미 포함돼 있다.
session-api 의 read/search/think 축과 합산하면 같은 노동을 두 번 센다.
"""
import argparse
import json

# 전체 작업 생산성 (Prechelt 2000, non-comment LOC/시간). 밴드 22~31.
_LOC_PER_HOUR = {"fast": 31.0, "mid": 26.5, "slow": 22.0}

# 이해(comprehension) 시간 분율 (Xia et al. 2018, ~58%).
_COMPREHENSION_SHARE = 0.58

# 파일 통째 폐기 — 읽지 않고 버린다. 훑기 수준 seed (분/줄).
_SCRAP_MIN_PER_LINE = 0.025

BANDS = ("fast", "mid", "slow")
DEFAULT_BAND = "mid"


def rates(band=DEFAULT_BAND):
    """밴드별 줄당 요율 (분/줄).

    W_new   = 60 / (전체 작업 줄/시간)
    W_del   = 60 / (전체 작업 줄/시간 ÷ 이해 분율)
    W_scrap = 고정 seed
    """
    if band not in _LOC_PER_HOUR:
        raise ValueError("band must be one of %s" % (BANDS,))
    loc_h = _LOC_PER_HOUR[band]
    return {
        "band": band,
        "loc_per_hour": loc_h,
        "new_min_per_line": 60.0 / loc_h,
        "delete_min_per_line": 60.0 / (loc_h / _COMPREHENSION_SHARE),
        "scrap_min_per_line": _SCRAP_MIN_PER_LINE,
    }


def diff_effort(added, deleted, file_deleted_lines=0, band=DEFAULT_BAND):
    """추가/삭제 라인 수 → 사람 노동(분).

    added               추가 라인 수 (주석·빈 줄 제외 권장)
    deleted             삭제 라인 수 (file_deleted_lines 포함한 전체)
    file_deleted_lines  그중 '파일이 통째로 사라진' 삭제 라인 수
    band                "fast" | "mid" | "slow"

    순삭제 = max(0, 부분삭제 − 추가). git diff 는 한 줄을 고치면
    +1/−1 쌍으로 잡으므로 그 쌍을 빼야 타이핑을 두 번 세지 않는다.
    파일 통째 삭제는 대응하는 추가가 없으므로 쌍 제거에서 제외한다.
    """
    added = int(added)
    deleted = int(deleted)
    file_deleted_lines = int(file_deleted_lines)
    if added < 0 or deleted < 0 or file_deleted_lines < 0:
        raise ValueError("라인 수는 음수일 수 없다")
    if file_deleted_lines > deleted:
        raise ValueError("file_deleted_lines 는 deleted 를 넘을 수 없다")

    r = rates(band)
    partial_deleted = deleted - file_deleted_lines
    net_deleted = max(0, partial_deleted - added)
    replaced = partial_deleted - net_deleted

    write_min = added * r["new_min_per_line"]
    delete_min = net_deleted * r["delete_min_per_line"]
    scrap_min = file_deleted_lines * r["scrap_min_per_line"]
    total = write_min + delete_min + scrap_min

    return {
        "minutes": round(total, 1),
        "hours": round(total / 60.0, 2),
        "band": band,
        "input": {"added": added, "deleted": deleted,
                  "file_deleted_lines": file_deleted_lines},
        "breakdown": {
            "write": {"lines": added,
                      "min_per_line": round(r["new_min_per_line"], 3),
                      "minutes": round(write_min, 1)},
            "delete": {"lines": net_deleted,
                       "min_per_line": round(r["delete_min_per_line"], 3),
                       "minutes": round(delete_min, 1)},
            "scrap": {"lines": file_deleted_lines,
                      "min_per_line": r["scrap_min_per_line"],
                      "minutes": round(scrap_min, 1)},
        },
        "replaced_pairs": replaced,
    }


def diff_effort_band(added, deleted, file_deleted_lines=0):
    """밴드 3종을 한 번에 — 대표값 하나만 내지 말고 폭을 같이 보라 (README §4)."""
    out = {b: diff_effort(added, deleted, file_deleted_lines, b) for b in BANDS}
    return {
        "mid_minutes": out["mid"]["minutes"],
        "range_minutes": [out["fast"]["minutes"], out["slow"]["minutes"]],
        "mid_hours": out["mid"]["hours"],
        "range_hours": [out["fast"]["hours"], out["slow"]["hours"]],
        "by_band": out,
    }


def _main():
    p = argparse.ArgumentParser(
        description="코드 라인 변경수 → 사람 노동(분) 환산")
    p.add_argument("added", type=int, help="추가 라인 수")
    p.add_argument("deleted", type=int, help="삭제 라인 수")
    p.add_argument("--file-deleted", type=int, default=0,
                   help="삭제 라인 중 파일이 통째로 사라진 몫 (기본 0)")
    p.add_argument("--band", choices=BANDS, default=DEFAULT_BAND,
                   help="생산성 밴드 (기본 mid)")
    p.add_argument("--all-bands", action="store_true",
                   help="fast/mid/slow 3종을 함께 출력")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    a = p.parse_args()

    if a.all_bands:
        res = diff_effort_band(a.added, a.deleted, a.file_deleted)
    else:
        res = diff_effort(a.added, a.deleted, a.file_deleted, a.band)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if a.all_bands:
        print("사람 노동 %.1f분 (%.2f시간)"
              % (res["mid_minutes"], res["mid_hours"]))
        print("  밴드 %.1f ~ %.1f분 (%.2f ~ %.2f시간)"
              % (res["range_minutes"][0], res["range_minutes"][1],
                 res["range_hours"][0], res["range_hours"][1]))
        return

    b = res["breakdown"]
    print("사람 노동 %.1f분 (%.2f시간)  [band=%s]"
          % (res["minutes"], res["hours"], res["band"]))
    print("  작성   %6d줄 x %.3f = %8.1f분" %
          (b["write"]["lines"], b["write"]["min_per_line"],
           b["write"]["minutes"]))
    print("  삭제   %6d줄 x %.3f = %8.1f분" %
          (b["delete"]["lines"], b["delete"]["min_per_line"],
           b["delete"]["minutes"]))
    print("  폐기   %6d줄 x %.3f = %8.1f분" %
          (b["scrap"]["lines"], b["scrap"]["min_per_line"],
           b["scrap"]["minutes"]))
    print("  (교체 쌍 %d줄은 중복 제거됨)" % res["replaced_pairs"])


if __name__ == "__main__":
    _main()
