# -*- coding: utf-8 -*-
"""코드 라인 변경수(추가/삭제) → 사람 노동 환산 모듈.

세션 기록 없이 **diff 라인 수만** 있을 때 쓰는 독립 환산기다.
근거·유도는 README.md 참조.

    유효추가 = 추가줄 × 유효라인비율
    유효삭제 = max(0, 삭제줄 × 유효라인비율 − 유효추가)      # 교체 쌍 제거

    분 = (유효추가 × W_new + 유효삭제 × W_del) × 구성비 계수

  W_new  전체 작업 생산성 (Prechelt) — 밴드 22~31 줄/시간
  W_del  삭제 판단 = 인스펙션 속도 (Fagan 계열) — 200 줄/시간
  구성비 계수  코드/문서/데이터 비율에서 나오는 실효 요율 배수
  유효라인비율 주석·빈 줄·자동생성물을 걷어낸 비율

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

# 삭제 판단 속도 (줄/시간). 코드 인스펙션·리뷰 속도 앵커 — README §2.2.
# 밴드(작성 생산성)와 무관한 별도 상수다: 지우는 일은 짜는 일이 아니라
# 읽고 판단하는 일이라 작성 속도와 같이 움직일 이유가 없다.
_DELETE_LOC_PER_HOUR = 200.0

# 종류별 요율 배수 — ../agent-effort/rates.json human_write_model 의
# 코드 0.08 / 문서 0.05 / 데이터 0.01 비율을 그대로 승계 (README §2.5).
# 이 배수는 요율의 비율이다(코드=문헌 유도, 문서=Karat 앵커, 데이터=seed).
# 여기에 곱할 **구성비**는 사용자가 넣는 값이고, 출처가 다르다 — 예시로
# 도는 0.44/0.315/0.244 는 Claude Code 세션 트랜스크립트에서 Write/Edit 로
# 나간 단어를 확장자별로 집계한 실측이다(단어 기준, 라인 기준 아님).
KIND_FACTOR = {"code": 1.0, "doc": 0.625, "data": 0.125}
KINDS = ("code", "doc", "data")

BANDS = ("fast", "mid", "slow")
DEFAULT_BAND = "mid"


def rates(band=DEFAULT_BAND):
    """밴드별 줄당 요율 (분/줄).

    W_new = 60 / (전체 작업 줄/시간)
    W_del = 60 / (삭제 판단 줄/시간)   — 밴드와 무관한 고정 앵커
    """
    if band not in _LOC_PER_HOUR:
        raise ValueError("band must be one of %s" % (BANDS,))
    loc_h = _LOC_PER_HOUR[band]
    return {
        "band": band,
        "loc_per_hour": loc_h,
        "new_min_per_line": 60.0 / loc_h,
        "delete_loc_per_hour": _DELETE_LOC_PER_HOUR,
        "delete_min_per_line": 60.0 / _DELETE_LOC_PER_HOUR,
    }


def mix_factor(code=1.0, doc=0.0, data=0.0):
    """코드/문서/데이터 구성비 -> 실효 요율 배수.

    비율은 합이 1이 아니어도 된다 — 내부에서 정규화한다.
    (0.44, 0.315, 0.244) -> 0.668

    이 예시 구성비의 출처: Claude Code 세션 트랜스크립트에서 Write/Edit
    도구로 나간 단어를 확장자별로 집계한 실측 (session-api/
    record_actions_code_api.md §2.5). 사람이 짠 코드가 아니라 **에이전트
    산출물**의 구성이고, **단어 기준**이라 라인 기준인 이 모듈에 그대로
    넣으면 오차가 있다. 자기 데이터를 라인 기준으로 재서 넣을 것 —
    measure_ratios.py 가 그 값을 뽑는다.

    가정: 종류별 상대 비용(코드 1 : 문서 0.625 : 데이터 0.125)은
    타이핑 축에서 잰 비율인데, 전체 작업 축으로 옮겨도 같다고 본다.
    문서·데이터의 '전체 작업 생산성' 문헌이 없어서 쓰는 가정이다.
    """
    w = {"code": float(code), "doc": float(doc), "data": float(data)}
    for k, v in w.items():
        if v < 0:
            raise ValueError("구성비는 음수일 수 없다: %s=%s" % (k, v))
    total = sum(w.values())
    if total <= 0:
        raise ValueError("구성비 합이 0이다")
    return sum(w[k] / total * KIND_FACTOR[k] for k in KINDS)


def effective_ratio(comment_ratio=0.0, generated_ratio=0.0):
    """주석·빈 줄 비율, 자동생성물 비율 -> 유효 라인 비율.

    Prechelt 의 요율은 non-comment LOC 기준이므로, 원시 diff 라인 수를
    그 기준으로 되돌리는 계수다. 두 비율은 서로 다른 축이라 곱한다
    (생성 파일 안의 주석을 두 번 빼는 오차는 있으나 방향이 안전하다).

    (0.25, 0.10) -> 0.675
    """
    for name, v in (("comment_ratio", comment_ratio),
                    ("generated_ratio", generated_ratio)):
        if not 0.0 <= float(v) < 1.0:
            raise ValueError("%s 는 0 이상 1 미만이어야 한다: %s" % (name, v))
    return (1.0 - float(comment_ratio)) * (1.0 - float(generated_ratio))


def diff_effort(added, deleted, band=DEFAULT_BAND, mix=None, eff_ratio=1.0):
    """추가/삭제 라인 수 → 사람 노동(분).

    added      추가 라인 수 (원시값 그대로 넣고 eff_ratio 로 보정)
    deleted    삭제 라인 수
    band       "fast" | "mid" | "slow"
    mix        구성비 계수 (mix_factor 결과) 또는 None(=1.0, 전부 코드)
    eff_ratio  유효 라인 비율 (effective_ratio 결과) 또는 1.0(미보정)

    순삭제 = max(0, 유효삭제 − 유효추가). git diff 는 한 줄을 고치면
    +1/−1 쌍으로 잡으므로 그 쌍을 빼야 타이핑을 두 번 세지 않는다.

    파일 통째 삭제는 별도로 다루지 않는다 — 집계 데이터에 그 구분이
    잡히지 않고, 삭제 요율 자체가 판단 비용 수준으로 내려와 있어
    따로 뺄 실익이 없다.
    """
    added = int(added)
    deleted = int(deleted)
    if added < 0 or deleted < 0:
        raise ValueError("라인 수는 음수일 수 없다")
    mix = 1.0 if mix is None else float(mix)
    eff_ratio = float(eff_ratio)
    if mix <= 0:
        raise ValueError("mix 는 양수여야 한다")
    if not 0.0 < eff_ratio <= 1.0:
        raise ValueError("eff_ratio 는 0 초과 1 이하여야 한다")

    r = rates(band)
    eff_added = added * eff_ratio
    eff_deleted = deleted * eff_ratio
    net_deleted = max(0.0, eff_deleted - eff_added)
    replaced = eff_deleted - net_deleted

    write_min = eff_added * r["new_min_per_line"] * mix
    delete_min = net_deleted * r["delete_min_per_line"] * mix
    total = write_min + delete_min

    return {
        "minutes": round(total, 1),
        "hours": round(total / 60.0, 2),
        "band": band,
        "mix": round(mix, 4),
        "eff_ratio": round(eff_ratio, 4),
        "input": {"added": added, "deleted": deleted},
        "breakdown": {
            "write": {"lines": round(eff_added, 1),
                      "min_per_line": round(r["new_min_per_line"] * mix, 4),
                      "minutes": round(write_min, 1)},
            "delete": {"lines": round(net_deleted, 1),
                       "min_per_line": round(r["delete_min_per_line"] * mix, 4),
                       "minutes": round(delete_min, 1)},
        },
        "replaced_pairs": round(replaced, 1),
    }


def diff_effort_band(added, deleted, mix=None, eff_ratio=1.0):
    """밴드 3종을 한 번에 — 대표값 하나만 내지 말고 폭을 같이 보라 (README §4)."""
    out = {b: diff_effort(added, deleted, b, mix, eff_ratio) for b in BANDS}
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
    p.add_argument("--band", choices=BANDS, default=DEFAULT_BAND,
                   help="생산성 밴드 (기본 mid)")
    p.add_argument("--mix", default=None, metavar="CODE,DOC,DATA",
                   help="구성비 (measure_ratios.py 로 실측해 넣는다). "
                        "생략하면 전부 코드 요율")
    p.add_argument("--comment-ratio", type=float, default=0.0,
                   help="주석·빈 줄 비율 (예: 0.25). 기본 0 = 미보정")
    p.add_argument("--generated-ratio", type=float, default=0.0,
                   help="자동생성물 비율 (예: 0.10). 기본 0 = 미보정")
    p.add_argument("--all-bands", action="store_true",
                   help="fast/mid/slow 3종을 함께 출력")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    a = p.parse_args()

    mix = None
    if a.mix:
        parts = [float(x) for x in a.mix.split(",")]
        if len(parts) != 3:
            p.error("--mix 는 CODE,DOC,DATA 세 값이어야 한다")
        mix = mix_factor(*parts)
    er = effective_ratio(a.comment_ratio, a.generated_ratio)

    if a.all_bands:
        res = diff_effort_band(a.added, a.deleted, mix, er)
    else:
        res = diff_effort(a.added, a.deleted, a.band, mix, er)

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
    print("사람 노동 %.1f분 (%.2f시간)  [band=%s, mix=%.4f, eff_ratio=%.4f]"
          % (res["minutes"], res["hours"], res["band"],
             res["mix"], res["eff_ratio"]))
    print("  작성  %10.1f줄 x %.4f = %10.1f분" %
          (b["write"]["lines"], b["write"]["min_per_line"],
           b["write"]["minutes"]))
    print("  삭제  %10.1f줄 x %.4f = %10.1f분" %
          (b["delete"]["lines"], b["delete"]["min_per_line"],
           b["delete"]["minutes"]))
    print("  (교체 쌍 %.1f줄은 중복 제거됨)" % res["replaced_pairs"])


if __name__ == "__main__":
    _main()
