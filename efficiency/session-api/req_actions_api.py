# -*- coding: utf-8 -*-
"""req-actions 세션 측정 API — 할일 중간층을 거치는 기본 방식.

자의 위치 (README "세 자의 위치" 필독): **직행 자 — 바닥(code_api) 근처.**
직행 지시 + 할일 중간층 + 건수형 코드 상한(§29)이 최소 경로로 수렴시킨다.
결과가 record_actions_code_api와 비슷하게 나오는 것은 궤적 추종이 아니라
직행 성공의 증거다. 닻은 LLM이 낸 항목을 조정만 하고 추가하지 않으므로,
LLM이 항목을 누락한 세션은 바닥 밑(과소)으로 갈 수 있다.

record-actions와의 차이는 딱 하나 — **행동을 짜는 LLM이 무엇을 보고
짜느냐.** 본 API는 기록에서 "완성해야 했던 결과물(할일)"만 추린 뒤 행동
분해 LLM에게 그 할일 목록만 보여준다 — 완성된 요리 사진만 보고 레시피
견적을 내는 방식. 세션의 경위(왕복·시행착오)는 행동 설계 입력에서
차단되고, 실측·명시 수량은 닻으로만 들어온다. 이 중간층이 쓰기 스코프
절삭(§20: 14,700→300단어)과 건수 억제의 원천이다.

방법론:
    트랜스크립트 → 할일(완성해야 할 결과물) 정리 → 사람 행동 목록 → 행동 × 요율
    분모는 기록 실측(LLM 0회) — 공용 코어 session_api.measure_agent_actual.

숫자 결정권: LLM은 행동 종류만 정하고, 규모 숫자는 코드 닻이 확정
(항해 구조 읽기량 = 기여 정독 + 후보 훑기 + 헛읽기 0, 산출물 상한,
완료조건 = 검증 건수). 근거: CHANGELOG §13~§16, §20.

record-actions(할일 안 거치는 교차확인 기준선)는 record_actions_api.py.

사용:
    from req_actions_api import measure
    r = measure(llm, "session.jsonl")              # LLM 1회 (할일+행동 병합)
    r = measure(llm, "session.jsonl", calls="staged")  # LLM 2회 (단계 감사)
    r["speedup"], r["human"]["min"], r["human"]["todos"], r["human"]["anchors"]

CLI:
    python req_actions_api.py <session.jsonl> [...] [--json] [--staged]
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from session_api import (measure_session, measure_sessions,  # noqa: E402
                         format_report, JsonRetryLLM)


def measure(llm, jsonl_path, calls="single", **kw):
    """세션 1개 → req-actions 분자 + 실측 분모 → speedup.

    calls: "single"(기본, LLM 1회) | "staged"(할일→행동 2회, 단계별 감사).
    나머지 인자·반환 구조는 session_api.measure_session과 동일.
    """
    return measure_session(llm, jsonl_path, human="req-actions",
                           calls=calls, **kw)


def measure_batch(llm, jsonl_paths, calls="single", **kw):
    """배치 측정. 실패 세션은 {"session", "error"}로 기록하고 계속."""
    return measure_sessions(llm, jsonl_paths, human="req-actions",
                            calls=calls, **kw)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: python req_actions_api.py <session.jsonl> [...] "
              "[--json] [--staged]", file=sys.stderr)
        return 2
    calls = "staged" if "--staged" in argv else "single"
    from onprem_llm_sim import OnpremLLM
    rows = measure_batch(JsonRetryLLM(OnpremLLM()), paths, calls=calls)
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(format_report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
