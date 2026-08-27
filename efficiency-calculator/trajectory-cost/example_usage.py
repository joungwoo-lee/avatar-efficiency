# -*- coding: utf-8 -*-
"""trajectory-cost 사용 예시 — 그대로 복붙해서 쓰는 용도.

실행:
    python example_usage.py                      # 예시 전부 (세션 자동 선택)
    python example_usage.py <세션ID 또는 .jsonl>  # 특정 세션으로

각 예시 함수 안의 주석 `# ---- 복붙 시작/끝 ----` 사이가 실제로 가져다 쓸 코드다.
"""
import sys
from pathlib import Path

# ==========================================================================
# 예시 0. 어디서 임포트하나
# ==========================================================================
# (A) session-api 계열 모듈 안 (record_actions_code_api.py 등)
#     -> session_api.py 가 sys.path 에 trajectory-cost 를 등록해 두므로 경로 설정 불필요.
#
#         from trajectory_cost import session_cost_usd
#
# (B) 그 밖의 위치
#     -> 경로 한 줄 먼저. (이 파일은 trajectory-cost 폴더 안이라 그대로 임포트된다)
#
#         sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "trajectory-cost"))
#         from trajectory_cost import session_cost_usd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trajectory_cost import (session_cost, session_cost_usd,  # noqa: E402
                             project_cost, transcript_files)


# ==========================================================================
# 예시 1. 달러 하나만 받기 — 가장 흔한 경우
# ==========================================================================
def example_1_just_the_dollars(session):
    # ---- 복붙 시작 ----
    from trajectory_cost import session_cost_usd

    usd = session_cost_usd(session)       # 세션 ID 또는 트랜스크립트 .jsonl 경로
    # ---- 복붙 끝 ----
    print("[1] 이 세션 비용: $%.4f" % usd)
    return usd


# ==========================================================================
# 예시 2. record_actions_code_api 측정 결과에 비용 항목 붙이기
# ==========================================================================
def example_2_attach_to_measure(session):
    """session-api 계열에서 쓰는 형태. measure() 결과 dict 에 llm 비용을 얹는다."""
    # ---- 복붙 시작 ----
    from trajectory_cost import session_cost_usd

    # r = measure(session)                        # 기존 측정 결과
    r = {"speedup": None, "human": {"min": None}}  # (예시용 더미)
    r["trajectory_cost_usd"] = session_cost_usd(session)
    # ---- 복붙 끝 ----
    print("[2] measure() 결과에 붙임: trajectory_cost_usd=$%.4f" % r["trajectory_cost_usd"])
    return r


# ==========================================================================
# 예시 3. 분해가 필요할 때 — 메인/서브에이전트/모델별/온프렘
# ==========================================================================
def example_3_breakdown(session):
    # ---- 복붙 시작 ----
    from trajectory_cost import session_cost

    d = session_cost(session)

    total = d["trajectory_cost_usd"]        # 전체 (USD)
    main = d["main_agent"]["cost_usd"]      # 메인 에이전트 몫
    sub = d["subagents"]["cost_usd"]        # 서브에이전트 몫
    onprem_tok = d["onprem"]["total_tokens"]  # 온프렘으로 돌린 토큰량 (비용은 0)
    per_model = {m: b["cost_usd"] for m, b in d["by_model"].items()}
    # ---- 복붙 끝 ----

    print("[3] 합계 $%.4f = 메인 $%.4f + 서브 $%.4f" % (total, main, sub))
    print("    온프렘 토큰 %s개 (비용 0)" % format(onprem_tok, ","))
    for m, c in per_model.items():
        print("    %-32s $%.4f" % (m, c))
    if d["warnings"]:
        print("    warnings: %s" % d["warnings"][0])
    return d


# ==========================================================================
# 예시 4. 여러 세션 일괄 — 프로젝트 폴더 전체
# ==========================================================================
def example_4_batch(project_dir):
    # ---- 복붙 시작 ----
    from trajectory_cost import project_cost

    out = project_cost(project_dir)
    out["trajectory_cost_usd"]                       # 프로젝트 전체 합계
    rows = [(s["session_id"], s["trajectory_cost_usd"]) for s in out["detail"]]
    rows.sort(key=lambda kv: -kv[1])                 # 비싼 세션부터
    # ---- 복붙 끝 ----

    print("[4] %s  세션 %d개  합계 $%.4f" % (project_dir, out["sessions"], out["trajectory_cost_usd"]))
    for sid, usd in rows[:5]:
        print("    %s  $%.4f" % (sid, usd))
    return out


# ==========================================================================
# 예시 5. 사내(온프렘) 모델을 비용 0 으로 지정하는 3가지 방법
# ==========================================================================
def example_5_onprem(session):
    # ---- 복붙 시작 ----
    from trajectory_cost import session_cost_usd

    # (a) 호출할 때 모델 ID 를 직접 넘긴다
    usd = session_cost_usd(session, onprem_models=["our-internal-7b", "sllm-13b"])

    # (b) 환경변수로 (프로세스 전체 적용)
    #     set TRAJECTORY_ONPREM_MODELS=our-internal-7b,sllm-13b
    #
    # (c) rates.json 의 onprem_patterns 에 이름 규칙(정규식) 추가 — 영구 적용
    #     "^onprem/", "^ollama/", "qwen", "llama", "exaone" ... 이미 들어 있음
    # ---- 복붙 끝 ----
    print("[5] 온프렘 지정 후 비용: $%.4f" % usd)
    return usd


# ==========================================================================
# 예시 6. 세션이 없을 수도 있을 때 (배치 스크립트에서 안전하게)
# ==========================================================================
def example_6_safe(session):
    # ---- 복붙 시작 ----
    from trajectory_cost import session_cost_usd

    try:
        usd = session_cost_usd(session)
    except FileNotFoundError:
        usd = None          # 트랜스크립트가 없는 세션 (삭제됐거나 다른 PC)
    # ---- 복붙 끝 ----
    print("[6] 안전 호출 결과: %s" % ("$%.4f" % usd if usd is not None else "트랜스크립트 없음"))
    return usd


def _pick_demo_session():
    """인자가 없을 때 최근 세션 하나 자동 선택."""
    from trajectory_cost import DEFAULT_PROJECTS_ROOT
    files = sorted(Path(DEFAULT_PROJECTS_ROOT).glob("*/*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit("트랜스크립트를 못 찾음. 세션 ID 나 .jsonl 경로를 인자로 넘겨라.")
    return files[0]


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows 콘솔 한글 깨짐 방지
    except Exception:
        pass

    session = sys.argv[1] if len(sys.argv) > 1 else _pick_demo_session()
    print("대상 세션: %s\n" % session)

    example_1_just_the_dollars(session)
    example_2_attach_to_measure(session)
    example_3_breakdown(session)
    example_4_batch(Path(transcript_files(session)[0]).parent)
    example_5_onprem(session)
    example_6_safe("00000000-dead-beef-0000-000000000000")
