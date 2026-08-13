# -*- coding: utf-8 -*-
"""human_workload_estimator — LLM 구간 (방법론 §9~§10, 1회 호출).

STEP 1: 완료 결과 단위 분할 (독립적으로 완료/미완료 판정 가능한 최소 단위)
STEP 2: 결과별 최소 인간 행동 + workload 수량화

규칙(§10): 시간 출력 금지, 요율 비노출, before-state에 있던 것 비용 제외,
공유 행동 중복 금지, 수량화 불가 항목은 MEASUREMENT_REQUIRED.

LLM 계약: llm.complete_json(prompt: str, max_tokens: int) -> dict
"""
import json

_MAX_TOKENS = 8000
_MAX_PROMPT_ARTIFACTS = 30  # 초과분은 프롬프트에서 생략하고 생략 사실을 명시 (silent cap 금지)
MANIFEST_BEGIN = "<<<ARTIFACT_MANIFEST_JSON>>>"
MANIFEST_END = "<<<END_ARTIFACT_MANIFEST_JSON>>>"


def build_prompt(manifest, rates):
    actions = "\n".join(f"- {k}: {v}" for k, v in rates["actions"].items())
    units = "\n".join(f"- {k}: {v['label']}" for k, v in rates["units"].items())
    lean = {k: v for k, v in manifest.items() if k != "artifacts"}
    arts = manifest["artifacts"]
    lean["artifacts"] = [dict(a) for a in arts[:_MAX_PROMPT_ARTIFACTS]]
    if len(arts) > _MAX_PROMPT_ARTIFACTS:
        lean["artifacts_omitted"] = (
            f"{len(arts) - _MAX_PROMPT_ARTIFACTS}개 artifact 생략됨 — "
            f"경로만: {[a['path'] for a in arts[_MAX_PROMPT_ARTIFACTS:]]}")
    manifest_json = json.dumps(lean, ensure_ascii=False, indent=1)
    return f"""너의 목적은 AI가 만든 최종 산출물을 기준으로, AI 없이 숙련된 사람이 동일한 유효 결과를
만들었다면 필요했을 인간 작업량을 산출하는 것이다.

[원래 작업 요청]
{json.dumps(manifest["task_requests"], ensure_ascii=False)}

[최종 Artifact Manifest — 최종 파일/net diff 포함]
{MANIFEST_BEGIN}
{manifest_json}
{MANIFEST_END}

반드시 다음 순서로 분석하라.

STEP 1. 완료 결과 단위 분할
최종 산출물에서 원래 작업 요청을 충족하는 결과를, 각각 독립적으로 완료/미완료를 판정할 수 있는
최소 단위로 분할하라.
규칙:
1. 파일 수, LOC, 페이지 수 같은 외형으로 나누지 않는다.
2. '이 결과만 실패하고 다른 결과는 성공할 수 있는가?'가 YES이면 별도 결과로 분리한다.
3. 원래 작업 요청에 필요하지 않은 추가 산출물은 제외한다.
4. 최종 net artifact에 남지 않은 목업·초안·폐기안·시행착오는 세지 않는다.
5. 다른 결과의 중간재만으로 존재하는 것은 독립 결과로 세지 않는다.
6. 각 결과가 최종 artifact의 어느 부분에서 확인되는지 근거를 명시한다.

STEP 2. 인간 행동 및 작업량 환산
STEP 1의 각 완료 결과에 대해, AI 없이 숙련된 사람이 처음부터 수행했을 정상적인 최소
작업경로를 계산하라.
사용 가능한 인간 행동 (이 이름만 사용):
{actions}
사용 가능한 workload 단위 (이 이름만 사용):
{units}
규칙:
1. AI가 실제 수행한 시행착오 경로를 재현하지 않는다.
2. 최종 결과에 반드시 필요한 최소 인간 행동만 포함한다.
3. 작업 시작 상태(before-state)에 이미 존재하던 것은 새로 만드는 비용으로 세지 않는다.
4. 각 행동의 workload는 artifact에서 근거를 찾을 수 있게 수량화하고 근거를 적어라.
5. 여러 결과가 같은 선행 행동을 공유하면 한 행으로만 적고 shared를 true로 표시한다.
6. 결과물만으로 수량화할 수 없는 항목은 숫자를 지어내지 말고 measurement_required에 적어라.
7. 시간·분·시급을 출력하지 마라.
8. complexity는 low|normal|high 중 하나로 표시한다.

JSON만 출력하라:
{{
  "completed_outcomes": [
    {{"outcome_id": "O1", "outcome": "...", "done_criteria": "...", "evidence": "..."}}
  ],
  "action_ledger": [
    {{"action_id": "A1", "outcome_id": "O1", "action": "행동 이름", "workload_unit": "단위 이름",
      "workload": N, "complexity": "normal", "evidence": "...", "shared": false}}
  ],
  "excluded_outputs": [{{"item": "...", "reason": "..."}}],
  "measurement_required": [{{"item": "...", "needed_info": "..."}}]
}}"""


def _clean_ledger(rows, rates):
    """카탈로그 밖 행동/단위 방어. 무효 행은 measurement_required로 강등."""
    valid, demoted = [], []
    for r in rows or []:
        try:
            workload = float(r.get("workload", 0))
        except (TypeError, ValueError):
            workload = 0
        if (r.get("action") in rates["actions"]
                and r.get("workload_unit") in rates["units"] and workload > 0):
            valid.append({
                "action_id": r.get("action_id", ""),
                "outcome_id": r.get("outcome_id", ""),
                "action": r["action"],
                "workload_unit": r["workload_unit"],
                "workload": workload,
                "complexity": r.get("complexity", "normal"),
                "evidence": r.get("evidence", ""),
                "shared": bool(r.get("shared", False)),
            })
        else:
            demoted.append({"item": json.dumps(r, ensure_ascii=False)[:200],
                            "needed_info": "카탈로그에 없는 행동/단위 또는 수량 없음"})
    return valid, demoted


def estimate_workload(manifest, llm, rates, retries=1):
    """LLM 호출 → 검증된 estimation dict.

    호출 실패(HTTP/JSON) 또는 유효 ledger 0행이면 retries회까지 재시도.
    재시도까지 실패하면 마지막 예외를 올린다 — 숫자를 지어내지 않는다.
    """
    prompt = build_prompt(manifest, rates)
    last_err = None
    for attempt in range(1 + max(0, retries)):
        try:
            result = llm.complete_json(prompt, max_tokens=_MAX_TOKENS)
        except (RuntimeError, ValueError) as e:
            last_err = e
            continue
        ledger, demoted = _clean_ledger(result.get("action_ledger"), rates)
        if not ledger and manifest.get("artifacts") and attempt < retries:
            last_err = ValueError("유효한 action_ledger 0행 — 재시도")
            continue
        return {
            "completed_outcomes": result.get("completed_outcomes") or [],
            "action_ledger": ledger,
            "excluded_outputs": result.get("excluded_outputs") or [],
            "measurement_required": (result.get("measurement_required") or []) + demoted,
        }
    raise RuntimeError(f"LLM workload 산정 실패 (재시도 {retries}회 포함): {last_err}")
