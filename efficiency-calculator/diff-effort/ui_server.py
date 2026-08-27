# -*- coding: utf-8 -*-
"""diff-effort 웹 UI — 브라우저에서 재고, 돌리고, 저장한다.

    python ui_server.py            # http://127.0.0.1:8765 열림
    python ui_server.py --port 9000 --no-browser

화면 하나에 네 칸이다.

    1) 저장소 고르기   폴더를 훑어 git 저장소를 골라 담는다 -> measure_ratios
    2) 비율 표시       재고 나온 계수(구성비·주석·자동생성물)를 보여준다
    3) CSV 고르기      사용량 CSV 를 골라 담는다
    4) 결과 + 저장     사람별 표 + 전체 합산, 리포트 CSV 로 저장

파일 선택은 **서버가 한다**. 브라우저의 <input type=file> 은 실제 경로를
주지 않기 때문에(보안), 서버가 폴더 목록을 내주고 사용자가 그걸 눌러
고른다. 그래서 127.0.0.1 에만 바인딩한다 — 이 서버는 자기 PC 의 파일을
읽고 쓴다. 외부에 열지 말 것.

계산은 전부 measure_ratios.py · csv_report.py 를 그대로 부른다. UI 는
따로 계산하지 않는다 — CLI 와 값이 갈리면 안 되기 때문이다.
"""
import argparse
import io
import json
import os
import string
import sys
import threading
import webbrowser
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import csv_report as CR
import measure_ratios as MR
from diff_effort import (BANDS, DEFAULT_BAND, KINDS, effective_ratio,
                         mix_factor, rates)

_HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(_HERE, "ui.html")

# 서버 모드에서 받는 CSV 내용의 상한. 사람 한 줄짜리 표라 이걸 넘길 일이 없다.
MAX_UPLOAD = 5 * 1024 * 1024

# 서버 모드에서 막는 것들 — 왜 막는지 그대로 사용자에게 보낸다.
BLOCKED_MSG = ("서버 모드에서는 막혀 있다: %s. 이 서버는 남의 PC 가 아니라 "
               "서버 자신의 디스크를 보게 되기 때문이다. 비율은 서버에 "
               "고정된 ratios.json 을 쓰고, CSV 는 내용만 올린다.")

# 마지막 리포트 결과 — 저장 버튼이 이걸 쓴다(다시 계산하지 않는다).
_LAST = {"rows": None, "total": None, "csv_path": None}
_LOCK = threading.Lock()


# ---------------------------------------------------------------- 파일 탐색

def drives():
    """win32 드라이브 문자 목록. 다른 OS 는 루트 하나."""
    if os.name != "nt":
        return ["/"]
    out = []
    for ch in string.ascii_uppercase:
        d = ch + ":\\"
        if os.path.exists(d):
            out.append(d)
    return out


def is_repo(path):
    """git 저장소인가 — .git 이 폴더(보통)이거나 파일(worktree)."""
    return (os.path.isdir(os.path.join(path, ".git"))
            or os.path.isfile(os.path.join(path, ".git")))


def browse(path, kind="dir"):
    """폴더 목록. kind='csv' 면 .csv 파일도 같이 준다."""
    if not path:
        ds = drives()
        return {"path": "", "up": None, "drives": ds,
                "dirs": [{"name": d, "path": d, "repo": False} for d in ds],
                "files": [], "is_repo": False}
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise ValueError("폴더가 아니다: %s" % path)
    dirs, files = [], []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except OSError as e:
        raise ValueError("읽을 수 없다: %s" % e)
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if e.is_dir():
                dirs.append({"name": e.name, "path": e.path,
                             "repo": is_repo(e.path)})
            elif kind == "csv" and e.name.lower().endswith(".csv"):
                files.append({"name": e.name, "path": e.path,
                              "size": e.stat().st_size})
        except OSError:
            continue
    up = os.path.dirname(path.rstrip("\\/")) or None
    if up == path:
        up = None
    return {"path": path, "up": up, "drives": drives(), "dirs": dirs,
            "files": files, "is_repo": is_repo(path)}


# ---------------------------------------------------------------- 동작

class _NS(object):
    """measure_ratios.to_config 이 읽는 argparse 네임스페이스 대역."""

    def __init__(self, since=None, until=None, author=None):
        self.since = since or None
        self.until = until or None
        self.author = author or None


def do_measure(body):
    """저장소들을 재서 ratios.json 을 쓴다."""
    repos = [r for r in (body.get("repos") or []) if r]
    if not repos:
        raise ValueError("저장소를 하나 이상 골라라")
    bad = [r for r in repos if not is_repo(r)]
    if bad:
        raise ValueError("git 저장소가 아니다: %s" % ", ".join(bad))
    out = (body.get("out") or "").strip() or MR.DEFAULT_CONFIG

    ns = _NS(body.get("since"), body.get("until"), body.get("author"))
    m = MR.measure(repos, ns.since, ns.until, ns.author,
                   not body.get("no_cloc"))
    cfg = MR.to_config(m, ns)
    if body.get("proxy"):
        # 대상 세션의 저장소가 아니라 예시 프로젝트로 잰 값이다. 파일에
        # 박아둬야 나중에 이 리포트를 실측으로 오해하지 않는다.
        cfg["proxy"] = True
        cfg["measured"]["proxy_note"] = (
            (body.get("proxy_note") or "").strip()
            or "대상 세션의 저장소가 아닌 예시 프로젝트로 잰 개략 추정값")
    saved = None
    if not body.get("no_save"):
        saved = MR.save_config(cfg, os.path.abspath(out))
    buf = io.StringIO()
    with redirect_stdout(buf):
        MR.print_report(m)
    return {"config": cfg, "detail": m, "saved_to": saved,
            "text": buf.getvalue().rstrip()}


def read_ratios(path=None):
    """지금 쓰이는 ratios.json 을 그대로 보여준다."""
    p = CR.find_config((path or "").strip() or None)
    if not p:
        return {"path": None, "config": None}
    with open(p, encoding="utf-8") as f:
        return {"path": p, "config": json.load(f)}


def public_ratios(cfg):
    """서버 모드에서 내보내도 되는 것만 추린다.

    보여줄 것은 **잰 저장소의 git 원격 주소와 비율값**뿐이다. 로컬 경로·
    설정 파일 위치는 서버 안쪽 사정이라 내보내지 않는다.
    """
    m = (cfg or {}).get("measured") or {}
    return {
        "mix": (cfg or {}).get("mix"),
        "comment_ratio": (cfg or {}).get("comment_ratio"),
        "generated_ratio": (cfg or {}).get("generated_ratio"),
        "proxy": bool((cfg or {}).get("proxy")),
        "proxy_note": m.get("proxy_note"),
        "repos": list(m.get("remotes") or []),   # 원격 주소만. 경로는 뺀다
        "repo_count": len(m.get("repos") or []),
        "since": m.get("since"), "until": m.get("until"),
        "at": m.get("at"), "basis": m.get("basis"),
        "diff_lines_total": m.get("diff_lines_total"),
        "comment_source": m.get("comment_source"),
    }


def server_assumptions(band, mix, eff_ratio, mix_parts, comment_r, gen_r, pub):
    """서버 모드용 [가정] 블록 — 경로 대신 원격 주소를 적는다.

    csv_report.print_assumptions 를 그대로 쓰면 서버의 파일 경로가 그대로
    딸려 나간다. 값은 같고 출처 표기만 공개 가능한 것으로 바꾼다.
    """
    r = rates(band)
    out = ["[가정]", "  설정          이 서버에 고정된 ratios.json"]
    repos = pub.get("repos") or []
    span = " ~ ".join(x for x in (pub.get("since"), pub.get("until")) if x)
    out.append("                잰 대상: %s / %s"
               % (", ".join(repos) or "(원격 주소 미기록)",
                  span or "전체 기간"))
    if pub.get("at"):
        out.append("                잰 시각: %s (기준: %s)"
                   % (pub["at"], pub.get("basis", "-")))
    if pub.get("proxy"):
        out.append("                ※ 대리 측정(추정) — %s"
                   % (pub.get("proxy_note")
                      or "대상 세션의 저장소가 아니다"))
    out.append("  밴드          %s — 작성 %.3f분/줄 (%.1f줄/h), "
               "삭제 %.3f분/줄 (%.0f줄/h)"
               % (band, r["new_min_per_line"], r["loc_per_hour"],
                  r["delete_min_per_line"], r["delete_loc_per_hour"]))
    if mix_parts:
        tot = sum(mix_parts)
        out.append("  구성비        코드 %.1f%% / 문서 %.1f%% / 데이터 %.1f%%"
                   " → 실효 요율 배수 %.4f"
                   % (mix_parts[0] / tot * 100, mix_parts[1] / tot * 100,
                      mix_parts[2] / tot * 100, mix))
    else:
        out.append("  구성비        미지정 → 전부 코드 요율 (문서·데이터 과대)")
    if comment_r or gen_r:
        out.append("  유효 라인     주석·빈 줄 %.1f%% + 자동생성물 %.1f%% 제외"
                   " → 유효 라인 비율 %.4f"
                   % (comment_r * 100, gen_r * 100, eff_ratio))
    else:
        out.append("  유효 라인     미보정 (과대)")
    return "\n".join(out)


# ------------------------------------------------------- 전제 두 개 점검
#
# 이 계산은 실측 두 개에 기댄다. 둘 중 하나라도 없으면 나온 숫자는
# 노동시간도 효율도 아니다. UI 가 그걸 눈에 보이게 하려고 상태를 낸다.
#
#   (1) 구성비   코드/문서/데이터 비율. 전부 코드 요율로 치면 문서·데이터
#                가 코드만큼 비싸져 effort 자체가 부풀려진다.
#   (2) 사람 개입시간(user_active_sec)  사람이 실제로 붙어 있던 시간.
#                x_user·x_total 의 분모다. 안 재면 효율을 못 낸다.

# 사람 개입시간이 CC 세션시간의 이 비율보다 작으면 계측 누락으로 본다.
HITL_MIN_SHARE = 0.10
HITL_MIN_SEC = 60.0

# 개입시간이 과소하게 찍히는 까닭과 제대로 재는 법. 경고에 같이 실어 보낸다.
HITL_WHY = ("사람이 일을 안 한 게 아니라 타임스탬프에 안 잡힌 것이다 — "
            "확인해야 할 사람 노동을 세션이 끝난 뒤 몰아서 했거나, "
            "AI 를 돌려놓고 그게 도는 동안 다른 자리에서 했기 때문이다.")
HITL_REMEDY = ("세션 트랜스크립트가 있으면 efficiency-calculator/session-api "
               "의 세션 분석으로 다시 잴 수 있다 — 지시·검토·중단 단서에서 "
               "사람 개입시간(hitl)을 뽑는다: "
               "python req_actions_api.py session.jsonl")

# 구성비를 대상 세션의 저장소에서 못 잴 때의 차선책.
MIX_PROXY_GUIDE = ("대상 세션의 저장소를 못 재면, 성격이 비슷한 예시 "
                   "프로젝트를 대신 재서 개략 추정값을 얻어라 — 1 칸에서 "
                   "'예시 프로젝트로 대신 잼' 을 켜고 재면 된다. "
                   "그렇게 얻은 값은 추정이지 실측이 아니다.")


def mix_status(mix_parts, source, proxy=False):
    """구성비 상태 -> UI 가 그릴 dict.

    level 은 셋이다. measured(대상에서 실측) · proxy(예시 프로젝트로 대신
    잰 추정) · none(아예 없음). proxy 를 measured 와 같은 초록으로 두면
    추정값을 실측으로 오해한다 — 그래서 따로 가른다.
    """
    if not mix_parts:
        return {"ok": False, "level": "none", "source": "none",
                "detail": "구성비 미측정 — 전부 코드 요율로 쳤다. "
                          "effort 가 부풀려진다(문서·데이터가 코드값).",
                "guide": MIX_PROXY_GUIDE}
    tot = sum(mix_parts) or 1.0
    share = "코드 %.1f%% / 문서 %.1f%% / 데이터 %.1f%%" \
        % tuple(p / tot * 100 for p in mix_parts)
    if proxy:
        return {"ok": False, "level": "proxy", "source": source,
                "detail": share + " — 예시 프로젝트로 대신 잰 값이다. "
                                  "개략 추정이지 이 세션의 실측이 아니다.",
                "guide": "보고할 때 '대리 측정(추정)' 이라고 반드시 밝혀라. "
                         "대상 저장소를 쓸 수 있게 되면 다시 재라."}
    return {"ok": True, "level": "measured", "source": source,
            "detail": share, "guide": ""}


def hitl_status(rows):
    """사람 개입시간 실측 상태 -> UI 가 그릴 dict.

    분모가 0 인 사람은 효율을 아예 못 낸다(x_user 가 '-' 로 빠진다).
    분모가 있어도 CC 시간에 견줘 터무니없이 작으면 계측 누락을 의심한다 —
    사람이 그 시간에 그 결과물을 다 봤다는 게 성립하지 않기 때문이다.
    """
    missing, tiny = [], []
    for r in rows:
        u = r["user_active_sec"]
        if not u or u <= 0:
            missing.append(r["employee_id"])
        elif u < HITL_MIN_SEC or u < r["cli_active_sec"] * HITL_MIN_SHARE:
            tiny.append(r["employee_id"])
    n = len(rows)
    ok = not missing and not tiny
    if missing and len(missing) == n:
        detail = ("사람 개입시간이 전원 0 이다 — 효율(x_user·x_total)을 "
                  "낼 수 없다.")
    elif missing or tiny:
        bits = []
        if missing:
            bits.append("0 인 사람 %d명 (%s)"
                        % (len(missing), ", ".join(missing[:5])))
        if tiny:
            bits.append("CC 시간의 %.0f%% 미만이라 계측 누락인 사람 %d명 (%s)"
                        % (HITL_MIN_SHARE * 100, len(tiny),
                           ", ".join(tiny[:5])))
        detail = " · ".join(bits) + " — 그 사람들의 효율값은 못 믿는다."
    else:
        detail = "전원 사람 개입시간이 들어 있다 (%d명)." % n
    return {"ok": ok, "missing": missing, "tiny": tiny, "count": n,
            "detail": detail,
            "why": "" if ok else HITL_WHY,
            "remedy": "" if ok else HITL_REMEDY,
            "min_share": HITL_MIN_SHARE, "min_sec": HITL_MIN_SEC}


def do_report(body, mode="local", fixed_config=None):
    """사용량 CSV -> 사람별 지표 + 전체 합산 + [가정] 블록.

    로컬 모드는 서버 디스크의 CSV 경로를 읽고, 서버 모드는 브라우저가
    올린 **내용**만 받는다(경로는 아예 안 받는다 — 서버 자신의 파일을
    읽히는 통로가 되기 때문).
    """
    csv_path = (body.get("csv_path") or "").strip()
    csv_text_in = body.get("csv_text")
    if mode == "server":
        if csv_path:
            raise ValueError(BLOCKED_MSG % "CSV 를 경로로 지정하는 것")
        if not isinstance(csv_text_in, str) or not csv_text_in.strip():
            raise ValueError("CSV 파일을 올려라")
        if len(csv_text_in.encode("utf-8")) > MAX_UPLOAD:
            raise ValueError("CSV 가 너무 크다 (상한 %dMB)"
                             % (MAX_UPLOAD // (1024 * 1024)))
    elif not csv_path and not csv_text_in:
        raise ValueError("CSV 경로를 골라라")
    elif csv_path and not os.path.isfile(csv_path):
        raise ValueError("파일이 없다: %s" % csv_path)

    band = body.get("band") or DEFAULT_BAND
    if band not in BANDS:
        raise ValueError("밴드가 이상하다: %s" % band)
    sort_key = body.get("sort") or "effort_min"
    if sort_key not in CR.SORT_KEYS:
        raise ValueError("정렬 키가 이상하다: %s" % sort_key)

    mix_parts = None
    comment_r = 0.0
    gen_r = 0.0
    cfg = cfg_path = None
    if mode == "server":
        # 서버 모드의 비율은 **서버에 고정된 파일 하나**다. 요청으로 바꿀
        # 수 없다 — 사람마다 다른 계수를 쓰면 같은 표에서 비교가 안 된다.
        cfg_path = fixed_config or CR.find_config(None)
        if not cfg_path:
            raise ValueError("이 서버에 고정된 ratios.json 이 없다 "
                             "— 관리자가 먼저 넣어야 한다")
        mix_parts, comment_r, gen_r, cfg = CR.load_config(cfg_path)
        mix_source = "config"
    else:
        if not body.get("no_config"):
            cfg_path = CR.find_config(
                (body.get("config") or "").strip() or None)
            if cfg_path:
                mix_parts, comment_r, gen_r, cfg = CR.load_config(cfg_path)
        mix_source = "config" if mix_parts else "none"
        if body.get("mix"):
            mix_parts = [float(x) for x in str(body["mix"]).split(",")]
            if len(mix_parts) != len(KINDS):
                raise ValueError("구성비는 CODE,DOC,DATA 세 값이어야 한다")
            mix_source = "inline"
        if body.get("comment_ratio") not in (None, ""):
            comment_r = float(body["comment_ratio"])
        if body.get("generated_ratio") not in (None, ""):
            gen_r = float(body["generated_ratio"])

    mix = mix_factor(*mix_parts) if mix_parts else None
    er = effective_ratio(comment_r, gen_r)
    if csv_text_in is not None and (mode == "server" or not csv_path):
        rows = CR.analyze_stream(io.StringIO(csv_text_in.lstrip("﻿"),
                                             newline=""), band, mix, er)
    else:
        rows = CR.analyze_csv(csv_path, band, mix, er,
                              body.get("encoding") or "utf-8-sig")
    if not rows:
        raise ValueError("employee_id 가 있는 줄이 없다")
    CR.sort_rows(rows, sort_key, bool(body.get("asc")))
    tot = None if body.get("no_total") else CR.totals(rows)

    pub = public_ratios(cfg)
    buf = io.StringIO()
    with redirect_stdout(buf):
        if mode == "server":
            # 경로가 딸려나가지 않는 판을 쓴다. 값은 같다.
            print(server_assumptions(band, mix if mix is not None else 1.0,
                                     er, mix_parts, comment_r, gen_r, pub))
            print()
        else:
            CR.print_assumptions(band, mix if mix is not None else 1.0, er,
                                 mix_parts, comment_r, gen_r, cfg_path, cfg)
        if tot:
            CR.print_total_block(tot)
    with _LOCK:
        _LAST["rows"] = rows
        _LAST["total"] = tot
        _LAST["csv_path"] = csv_path
    proxy = bool((cfg or {}).get("proxy")) and mix_source == "config"
    gates = {"mix": mix_status(mix_parts, mix_source, proxy),
             "hitl": hitl_status(rows)}
    return {"rows": rows, "total": tot, "fields": list(CR.FIELDS),
            "assumptions": buf.getvalue().strip(),
            "config_path": None if mode == "server" else cfg_path,
            "ratios": pub if mode == "server" else None,
            "csv_text": CR.csv_text(rows, tot) if mode == "server" else None,
            "uncorrected": not mix_parts and not (comment_r or gen_r),
            "gates": gates,
            "trustworthy": gates["mix"]["ok"] and gates["hitl"]["ok"],
            "csv_path": csv_path,
            "out_suggest": None if mode == "server" else suggest_out(csv_path)}


def do_save(body):
    """마지막 결과를 리포트 CSV 로 쓴다 — 다시 계산하지 않는다."""
    with _LOCK:
        rows, tot = _LAST["rows"], _LAST["total"]
    if not rows:
        raise ValueError("먼저 리포트를 돌려라")
    out = (body.get("out") or "").strip()
    if not out:
        raise ValueError("저장 경로를 적어라")
    out = os.path.abspath(out)
    if not out.lower().endswith(".csv"):
        out += ".csv"
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        raise ValueError("폴더가 없다: %s" % d)
    CR.write_csv(rows, out, tot)
    return {"saved_to": out, "rows": len(rows)}


def suggest_out(csv_path):
    """저장 경로 기본값 — 입력 CSV 옆에 *_report.csv."""
    if not csv_path:
        return os.path.join(_HERE, "report.csv")
    return os.path.splitext(os.path.abspath(csv_path))[0] + "_report.csv"


# ---------------------------------------------------------------- HTTP

# 서버 모드에서 열어두는 것 — 이 둘뿐이다.
SERVER_GET = ("/", "/index.html", "/ui.html", "/api/meta", "/api/ratios")
SERVER_POST = ("/api/report",)


class Handler(BaseHTTPRequestHandler):
    """로컬 모드 핸들러. 서버 모드는 아래 make_handler 로 만든다."""

    server_version = "diff-effort-ui"
    mode = "local"          # "local" | "server"
    fixed_config = None     # 서버 모드에서 쓸 ratios.json 경로

    def log_message(self, fmt, *args):      # 조용히
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str))

    def _err(self, e, code=400):
        self._json({"error": str(e)}, code)

    def _query(self):
        q = parse_qs(urlparse(self.path).query)
        return dict((k, v[0]) for k, v in q.items())

    def _drain(self, n, chunk=65536):
        """거절할 요청의 몸통을 읽어 버린다 (최대 64MB 까지만)."""
        left = min(n, 64 * 1024 * 1024)
        while left > 0:
            got = self.rfile.read(min(chunk, left))
            if not got:
                break
            left -= len(got)

    def _blocked(self, what):
        self._json({"error": BLOCKED_MSG % what, "blocked": True}, 403)

    def _meta(self):
        m = {
            "mode": self.mode,
            "bands": list(BANDS),
            "default_band": DEFAULT_BAND,
            "sort_keys": list(CR.SORT_KEYS),
            "required": list(CR.REQUIRED),
            "hitl_min_share": HITL_MIN_SHARE,
            "hitl_min_sec": HITL_MIN_SEC,
            "hitl_why": HITL_WHY,
            "hitl_remedy": HITL_REMEDY,
            "mix_proxy_guide": MIX_PROXY_GUIDE,
            "max_upload": MAX_UPLOAD,
        }
        if self.mode == "local":
            # 로컬 모드에서만 서버(=내 PC) 경로를 내준다.
            m.update({"here": _HERE, "default_config": CR.DEFAULT_CONFIG,
                      "home": os.path.expanduser("~")})
        return m

    def _ratios(self):
        """서버 모드에서는 원격 주소와 비율값만 내보낸다."""
        if self.mode != "server":
            return read_ratios(self._query().get("path"))
        path = self.fixed_config or CR.find_config(None)
        if not path:
            return {"mode": "server", "public": None,
                    "error_hint": "이 서버에 고정된 ratios.json 이 없다"}
        with open(path, encoding="utf-8") as f:
            return {"mode": "server", "public": public_ratios(json.load(f))}

    def do_GET(self):
        p = urlparse(self.path).path
        if self.mode == "server" and p not in SERVER_GET:
            return self._blocked("이 경로(%s)" % p)
        try:
            if p in ("/", "/index.html", "/ui.html"):
                with open(INDEX, encoding="utf-8") as f:
                    return self._send(200, f.read(),
                                      "text/html; charset=utf-8")
            if p == "/api/browse":
                q = self._query()
                return self._json(browse(q.get("path", ""),
                                         q.get("kind", "dir")))
            if p == "/api/ratios":
                return self._json(self._ratios())
            if p == "/api/meta":
                return self._json(self._meta())
            if p == "/api/suggest-out":
                return self._json(
                    {"out": suggest_out(self._query().get("csv_path"))})
            return self._json({"error": "없는 경로: %s" % p}, 404)
        except (OSError, ValueError) as e:
            return self._err(e)
        except Exception as e:                              # noqa: BLE001
            return self._err(e, 500)

    def do_POST(self):
        p = urlparse(self.path).path
        if self.mode == "server" and p not in SERVER_POST:
            return self._blocked(
                "저장소 선택·비율 측정" if p == "/api/measure"
                else "서버 디스크에 저장" if p == "/api/save"
                else "이 경로(%s)" % p)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                # 답하기 전에 보낸 몸통을 비워준다. 안 읽고 끊으면 클라이언트가
                # 응답 대신 연결 끊김(RST)을 본다 — 왜 거절됐는지 못 읽는다.
                self._drain(n)
                raise ValueError("요청이 너무 크다 (상한 %dMB)"
                                 % (MAX_UPLOAD // (1024 * 1024)))
            body = json.loads(self.rfile.read(n) or b"{}")
            if p == "/api/report":
                return self._json(do_report(body, self.mode,
                                            self.fixed_config))
            if p == "/api/measure":
                return self._json(do_measure(body))
            if p == "/api/save":
                return self._json(do_save(body))
            return self._json({"error": "없는 경로: %s" % p}, 404)
        except (OSError, ValueError, RuntimeError) as e:
            return self._err(e)
        except Exception as e:                              # noqa: BLE001
            return self._err(e, 500)


def make_handler(mode="local", fixed_config=None):
    """모드가 박힌 핸들러 클래스를 만든다."""
    return type("Handler_" + mode, (Handler,),
                {"mode": mode, "fixed_config": fixed_config})


def serve(port=8765, open_browser=True, mode="local", config=None,
          host=None):
    if mode == "server":
        cfg = config or CR.find_config(None)
        if not cfg:
            sys.stderr.write("오류: 서버 모드는 고정된 ratios.json 이 "
                             "있어야 한다 (--config 로 지정)" + chr(10))
            return 2
        cfg = os.path.abspath(cfg)
        host = host or "0.0.0.0"
    else:
        cfg = None
        host = host or "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), make_handler(mode, cfg))
    url = "http://%s:%d/" % ("127.0.0.1" if host == "0.0.0.0" else host, port)
    print("diff-effort UI [%s]  %s" % (mode, url))
    if mode == "server":
        print("  고정 비율: %s" % cfg)
        print("  CSV 는 내용만 받는다. 저장소 선택·측정·서버 저장은 막혀 있다.")
    else:
        print("  (127.0.0.1 전용 — 이 서버는 이 PC 의 파일을 읽고 쓴다)")
    print("  Ctrl+C 로 종료")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(chr(10) + "종료")
    finally:
        httpd.server_close()
    return 0


def _main():
    p = argparse.ArgumentParser(description="diff-effort 웹 UI")
    p.add_argument("--port", type=int, default=8765, help="포트 (기본 8765)")
    p.add_argument("--no-browser", action="store_true",
                   help="브라우저를 자동으로 열지 않는다")
    p.add_argument("--server", action="store_true",
                   help="서버 모드 — CSV 업로드만 받고 비율은 고정. "
                        "저장소 선택·측정·서버 저장을 막는다")
    p.add_argument("--config", default=None,
                   help="서버 모드에서 쓸 고정 ratios.json 경로")
    p.add_argument("--host", default=None,
                   help="바인딩 주소 (기본: 로컬 127.0.0.1 / 서버 0.0.0.0)")
    a = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    return serve(a.port, not a.no_browser,
                 "server" if a.server else "local", a.config, a.host)


if __name__ == "__main__":
    sys.exit(_main())
