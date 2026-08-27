# -*- coding: utf-8 -*-
"""record_actions_code_api.py 에 비용을 붙이는 호출부 예시.

넣을 자리 두 곳 (session-api/record_actions_code_api.py):

  (1) 임포트 — 파일 맨 위 임포트 블록, 59행 `from agent_effort import ...` 바로 아래

        from session_api import (measure_agent_actual, is_trivial_session)  # noqa: E402
        from requirement_actions import collect_record_stats                # noqa: E402
        from agent_effort import load_rates, speedup                        # noqa: E402
    +   from trajectory_cost import session_cost_usd                        # noqa: E402

      (session_api 를 먼저 임포트하므로 경로 설정은 필요 없다.)

  (2) 호출 — measure() 의 return dict (463행) 안, "speedup" 줄 옆에 한 줄

            "speedup": speedup(h_min, actual["total_min"]),
            "speedup_vs_hitl": speedup(h_min, actual["hitl_min"]),
    +       "trajectory_cost_usd": _cost_usd(jsonl_path),
            "channel_audit": audit,

      그리고 파일 아무 데나 (measure 위) 헬퍼 하나 — 트랜스크립트가 없는 세션에서
      측정 전체가 죽지 않게 감싼다:

    +   def _cost_usd(jsonl_path):
    +       try:
    +           return session_cost_usd(jsonl_path)
    +       except (FileNotFoundError, OSError):
    +           return None

이 파일은 원본을 고치지 않고 같은 결과를 만들어 보여준다.
실행: python callsite_example.py <세션.jsonl 경로>
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent / "session-api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from record_actions_code_api import measure          # noqa: E402
from trajectory_cost import session_cost_usd         # noqa: E402  ← (1) 임포트


def _cost_usd(jsonl_path):
    """트랜스크립트가 없으면 None. 비용 때문에 측정이 죽지 않게."""
    try:
        return session_cost_usd(jsonl_path)
    except (FileNotFoundError, OSError):
        return None


def measure_with_cost(jsonl_path, **kw):
    r = measure(jsonl_path, **kw)
    r["trajectory_cost_usd"] = _cost_usd(jsonl_path)   # ← (2) 호출
    return r


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    r = measure_with_cost(sys.argv[1])
    print("세션      : %s" % r["session"])
    print("사람 시간 : %s 분" % r["human"]["min"])
    print("기계 시간 : %s 분" % r["agent"]["machine_min"])
    print("speedup   : %s" % r["speedup"])
    print("LLM 비용  : %s" % ("$%.4f" % r["trajectory_cost_usd"]
                              if r["trajectory_cost_usd"] is not None else "측정 불가"))
