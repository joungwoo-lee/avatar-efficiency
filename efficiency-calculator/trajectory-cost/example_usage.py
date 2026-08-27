# -*- coding: utf-8 -*-
"""trajectory-cost 사용 예시. 실행: python example_usage.py <세션ID 또는 .jsonl>"""
import sys
from pathlib import Path

# session-api 계열 모듈 안에서는 이 두 줄 불필요 (session_api.py 가 경로를 등록해 둔다)
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---- 여기부터 복붙 ----
from trajectory_cost import session_cost_usd

usd = session_cost_usd(sys.argv[1])      # 세션 ID 또는 트랜스크립트 .jsonl 경로 -> float(USD)
# ---- 여기까지 ----

print("$%.4f" % usd)

# 분해가 필요하면 session_cost() — dict 로 나온다.
#   d = session_cost(session)
#   d["trajectory_cost_usd"]      전체
#   d["main_agent"]["cost_usd"]   메인 에이전트 몫 / d["subagents"]["cost_usd"] 서브에이전트 몫
#   d["by_model"], d["onprem"]    모델별 / 온프렘(비용 0, 토큰량은 집계)
