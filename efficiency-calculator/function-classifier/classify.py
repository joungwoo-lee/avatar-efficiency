"""
classify.py — 압축본을 LLM에 넣어 펑션(부서 내 업무 구분) 비율을 분류.

LLM 계약(레포 공통): llm.complete_json(prompt: str, max_tokens: int) -> dict

사용:
  from classify import classify
  r = classify(llm, "session.jsonl", ["sw개발", "sw검증", "hw설계", "문서작성"])
  # r = {"shares": {"sw개발": 60, ...}, "primary": "sw개발", "evidence": "...", "condense_stats": {...}}
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from condense import condense, render, DEFAULT_BUDGET_TOKENS  # noqa: E402

PROMPT = """아래는 한 작업 세션의 압축 기록이다. 이 세션에서 수행된 업무를 주어진 펑션 목록으로 분류하라.

규칙:
- 한 세션이 여러 펑션에 걸치는 게 정상이다. 각 펑션의 비중(합계 100)을 매겨라.
- 목록에 없는 업무는 "기타"에 넣어라.
- 판단 근거: USER의 지시 내용, ASSISTANT의 설명, META의 파일 확장자·경로·툴 분포를 모두 본다.
- 코드는 생략돼 있다. 어떤 파일을 만졌는지는 META.paths/exts 로 판단하라.

펑션 목록:
{functions}

반드시 JSON만 출력:
{{"shares": {{"<펑션>": <정수>, ...}}, "primary": "<비중 최대 펑션>", "evidence": "<근거 한두 문장>"}}

=== 세션 기록 ===
{body}
"""


def build_prompt(condensed, functions):
    fl = "\n".join(f"- {f}" for f in functions)
    return PROMPT.format(functions=fl, body=render(condensed))


def _normalize(raw, functions):
    shares = raw.get("shares") or {}
    allowed = list(functions) + ["기타"]
    clean = {}
    for k, v in shares.items():
        if k in allowed:
            try:
                clean[k] = max(0, int(round(float(v))))
            except (TypeError, ValueError):
                pass
    total = sum(clean.values())
    if total > 0 and total != 100:
        clean = {k: int(round(v * 100 / total)) for k, v in clean.items()}
    primary = raw.get("primary")
    if primary not in clean and clean:
        primary = max(clean, key=clean.get)
    return {"shares": clean, "primary": primary, "evidence": str(raw.get("evidence", "")).strip()}


def classify(llm, jsonl_path, functions, budget_tokens=DEFAULT_BUDGET_TOKENS, max_tokens=800):
    c = condense(jsonl_path, budget_tokens)
    prompt = build_prompt(c, functions)
    raw = llm.complete_json(prompt, max_tokens)
    out = _normalize(raw, functions)
    out["condense_stats"] = c["stats"]
    return out


def classify_batch(llm, jsonl_paths, functions, **kw):
    return {str(p): classify(llm, p, functions, **kw) for p in jsonl_paths}


if __name__ == "__main__":
    # 프롬프트만 확인: python classify.py session.jsonl "sw개발,sw검증,hw설계"
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)
    fns = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
    sys.stdout.write(build_prompt(condense(sys.argv[1]), fns))
