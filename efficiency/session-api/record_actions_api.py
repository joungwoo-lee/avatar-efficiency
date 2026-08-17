# -*- coding: utf-8 -*-
"""record-actions 세션 측정 API — 할일 안 거치는 교차확인 기준선.

방법론:
    트랜스크립트 → (할일 정리 없이) 바로 사람 행동 목록 → 행동 × 요율
    분모는 기록 실측(LLM 0회) — 공용 코어 session_api.measure_agent_actual.
    닻은 신방식과 동일하게 적용 (항해 구조 읽기량·산출물 상한) — 두 방식의
    차이가 "할일 중간층 유무"만 반영되도록 숫자 결정권은 코드로 통일.

자의 위치 (README "세 자의 위치" 필독): **위쪽 자 — 궤적 냄새를 간직한
기준선.** 본 API도 req-actions처럼 "사람이 했다면"으로 행동을 재구성하고
같은 닻을 쓴다. 차이는 딱 하나 — **행동을 짜는 LLM이 무엇을 보고
짜느냐**: req는 할일 목록만 보고 짜고(요리 사진만 보고 레시피 견적),
본 API는 **세션 요약을 직접 보면서** 짠다(주방 CCTV 요약을 보며 견적).
프롬프트가 직행을 지시해도 눈앞의 활동 신호(검색·실행·왕복 횟수)에
LLM이 앵커링되고, 건수형 상한(§29)도 의도적으로 안 달아 건수형이 부푼다.
따라서 req-actions보다 **크게 나오는 것이 정상**이며, 그 간격이 곧
"직행 자와 궤적 자의 거리"다 (10세션 실측 +37min/26%, 전부 닻 없는
건수형에서 발생 — draft/edit/read는 세 방식 동일). 본 API는 더 나은 자가
아니라 **req를 검산하는 거울**이다 — req ≤ rec 순서가 깨지면 측정 버그를
의심할 것 (§29·§30·§33 사고 전부 이 역전으로 발견).

용도·한계 (CHANGELOG §20 대조 실험):
    교차확인 기준선 전용. **단독 판정에 쓰지 말 것.**
    기본 측정은 req_actions_api.py, LLM 없는 바닥 자는
    record_actions_code_api.py.

사용:
    from record_actions_api import measure
    r = measure(llm, "session.jsonl")              # LLM 1회
    r["speedup"], r["human"]["min"], r["human"]["anchors"]

CLI:
    python record_actions_api.py <session.jsonl> [...] [--json]
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from session_api import (measure_session, measure_sessions,  # noqa: E402
                         format_report, JsonRetryLLM)


def measure(llm, jsonl_path, **kw):
    """세션 1개 → record-actions 분자 + 실측 분모 → speedup.

    LLM 1회 (행동 분해만 — 할일 중간층 없음).
    반환 구조는 session_api.measure_session과 동일.
    """
    return measure_session(llm, jsonl_path, human="record-actions", **kw)


def measure_batch(llm, jsonl_paths, **kw):
    """배치 측정. 실패 세션은 {"session", "error"}로 기록하고 계속."""
    return measure_sessions(llm, jsonl_paths, human="record-actions", **kw)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: python record_actions_api.py <session.jsonl> [...] [--json]",
              file=sys.stderr)
        return 2
    from onprem_llm_sim import OnpremLLM
    rows = measure_batch(JsonRetryLLM(OnpremLLM()), paths)
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(format_report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
