# -*- coding: utf-8 -*-
"""Agent 경로(machine + hitl) 산정 — doc/integ-spec.md §3 계약.

구 Counterfactual API 호환에 필요한 agent_min/agent_human_min/agent_ai_min을
primitive count × rates.json 요율로 산정한다. LLM은 count만 출력하고,
분 환산은 이 모듈이 결정론적으로 수행한다(요율 프롬프트 미노출).

human 경로 count도 스펙 §3 LLM 출력 스키마대로 함께 받지만, human_min의
공식 산정은 v0.5 Work Unit 엔진(estimator.HumanEffortEstimator)이 담당한다 —
여기의 human 결과는 교차확인·폴백 참고용으로만 반환한다.
"""
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_RATES_PATH = _HERE / "rates.json"

_FEW_SHOT = """예시 입력:
  업무 제목: 메일 회신 초안 작성
  업무 상세: 첨부 보고서(약 800단어) 검토 후 부서장 승인 요청 회신(200단어 내외) 작성
  소속 역할: PM
  연결된 스킬: mail-draft, summarize

예시 출력:
{
  "human": [
    {"primitive": "read", "count": 800},
    {"primitive": "draft", "count": 200},
    {"primitive": "verify", "count": 1}
  ],
  "agent": [
    {"primitive": "read", "count": 800},
    {"primitive": "draft", "count": 200},
    {"primitive": "verify", "count": 1}
  ],
  "hitl": [
    {"primitive": "instruct", "count": 1},
    {"primitive": "review", "count": 200},
    {"primitive": "approve", "count": 1}
  ],
  "ai_io": {"input_words": 900, "output_words": 250},
  "rationale": "AI가 보고서를 읽고 초안 생성, 사람은 지시 1회와 초안 검토·승인만 수행"
}"""


def load_rates(rates_path=DEFAULT_RATES_PATH):
    with open(rates_path, encoding="utf-8") as f:
        return json.load(f)


def _catalog_lines(card):
    return "\n".join(f"- {name}({spec['unit']})" for name, spec in card.items())


def build_prompt(spec_text, rates):
    """요율(min_per_unit)은 절대 포함하지 않는다 — 수량 역산 오염 방지."""
    return f"""너는 업무 에포트 산정을 위한 작업 분해 엔진이다.
아래 작업 지침서를 읽고, 같은 완료상태에 도달하는 두 실행경로를 primitive action 수량으로 분해하라.

1. human: AI를 전혀 쓰지 않는 기준 숙련자가 합리적 최단 경로로 수행할 때의 행동과 수량
2. agent: AI 에이전트(연결된 스킬 사용)가 기계로 수행하는 행동과 수량
3. hitl: agent 경로에서 사람이 수행하는 모든 행동과 수량 — 감독 행동(지시 작성, 출력 검토, 승인, 수정지시, 수동검증)뿐 아니라, 에이전트가 수행할 수 없어 사람이 직접 마저 해야 하는 잔여 작업(직접 작성 draft, 수정 edit, 입력 data_entry, 실행 execute, 판단 decide)도 반드시 포함하라

규칙:
- 두 경로는 같은 업무 범위·품질·검증 수준을 만족해야 한다. agent 경로에서 검증을 생략하지 마라.
- 시간·분·시급을 출력하지 마라. 오직 primitive 이름과 count만 출력한다.
- count는 지침서에 언급된 실제 수량(단어수, 문서수, 항목수 등)에 근거해야 한다. 근거 없는 큰 수를 지어내지 마라.
- 아래 카탈로그에 없는 primitive 이름을 쓰지 마라.

human용 primitive 카탈로그 (이름(수량단위)):
{_catalog_lines(rates["human"])}

agent용 primitive 카탈로그:
{_catalog_lines(rates["agent"])}

hitl용 primitive 카탈로그:
{_catalog_lines(rates["hitl"])}

ai_io: 에이전트 LLM 호출의 대략적 입력/출력 단어수 총합을 {{"input_words": N, "output_words": N}}로 추정하라.

{_FEW_SHOT}

출력은 위 예시와 같은 구조의 JSON 오브젝트 하나만. 다른 텍스트 금지.

--- 작업 지침서 ---
{spec_text}
--- 끝 ---"""


def _validate_path(items, card, path_name, notes):
    """카탈로그 검증. 유효 항목만 반환, 문제는 notes에 축적."""
    valid = []
    if not isinstance(items, list):
        notes.append(f"{path_name}: 리스트가 아님 -> 빈 목록 처리")
        return valid
    for it in items:
        if not isinstance(it, dict) or "primitive" not in it or "count" not in it:
            notes.append(f"{path_name}: 형식 불량 항목 폐기 {it!r}")
            continue
        name = it["primitive"]
        if name not in card:
            notes.append(f"{path_name}: 미등록 primitive 폐기 '{name}'")
            continue
        try:
            count = float(it["count"])
        except (TypeError, ValueError):
            notes.append(f"{path_name}: count 숫자 아님 폐기 {it!r}")
            continue
        if count < 0:
            notes.append(f"{path_name}: 음수 count 폐기 {it!r}")
            continue
        valid.append({"primitive": name, "count": count})
    return valid


def validate_llm_output(raw, rates):
    """반환: (parsed, notes, fatal). fatal=True면 재호출 권장."""
    notes = []
    if not isinstance(raw, dict):
        return None, ["agent-path LLM 응답이 dict가 아님"], True
    if "agent" not in raw:
        return None, ["필수 키(agent) 누락"], True
    parsed = {
        "human": _validate_path(raw.get("human", []), rates["human"], "human", notes),
        "agent": _validate_path(raw.get("agent"), rates["agent"], "agent", notes),
        "hitl": _validate_path(raw.get("hitl", []), rates["hitl"], "hitl", notes),
        "ai_io": raw.get("ai_io") or {},
        "rationale": raw.get("rationale", ""),
    }
    if not parsed["agent"]:
        return None, notes + ["유효 agent 항목 0개"], True
    if not parsed["hitl"]:
        notes.append("hitl 비어 있음 — 감독시간 0으로 계산됨(과대평가 위험)")
    return parsed, notes, False


def trajectory_minutes(actions, card):
    """수량 x 요율 환산. (total, breakdown) 반환."""
    total = 0.0
    breakdown = []
    for a in actions:
        spec = card[a["primitive"]]
        minutes = a["count"] * spec["min_per_unit"]
        total += minutes
        breakdown.append({
            "primitive": a["primitive"],
            "count": a["count"],
            "unit": spec["unit"],
            "minutes": round(minutes, 2),
        })
    return round(total, 2), breakdown


def ai_io_minutes(ai_io, rates):
    """반환: {"input_words", "output_words", "minutes"}."""
    r = rates["ai_io"]
    try:
        inp = float(ai_io.get("input_words", 0) or 0)
        out = float(ai_io.get("output_words", 0) or 0)
    except (TypeError, ValueError):
        inp = out = 0.0
    minutes = round(inp * r["input_words_min_per_word"] + out * r["output_words_min_per_word"], 2)
    return {"input_words": inp, "output_words": out, "minutes": minutes}


def estimate_agent_path(llm, spec_text, rates, max_tokens=2000):
    """LLM 1회 호출(+검증 실패 시 1회 재시도) → agent 경로 분 산정.

    반환: {
      "machine_min", "hitl_min", "agent_min",
      "machine_breakdown", "hitl_breakdown", "human_ref_breakdown",
      "ai_io", "revision_factor", "rationale", "notes"
    }
    """
    prompt = build_prompt(spec_text, rates)
    raw = llm.complete_json(prompt, max_tokens)
    parsed, notes, fatal = validate_llm_output(raw, rates)
    if fatal:
        retry_prompt = (prompt + "\n\n[재시도] 직전 응답이 유효하지 않았다: "
                        + "; ".join(notes) + "\n스키마를 정확히 지켜 다시 출력하라.")
        raw = llm.complete_json(retry_prompt, max_tokens)
        parsed, notes2, fatal = validate_llm_output(raw, rates)
        notes = notes + ["agent-path: 1회 재시도 수행"] + notes2
        if fatal:
            raise ValueError("agent-path LLM 출력 검증 2회 실패: " + "; ".join(notes))

    agent_traj_min, agent_bd = trajectory_minutes(parsed["agent"], rates["agent"])
    io = ai_io_minutes(parsed["ai_io"], rates)
    rf = float(rates.get("agent_revision_factor", 1.0))
    machine_min = round((agent_traj_min + io["minutes"]) * rf, 2)
    hitl_min, hitl_bd = trajectory_minutes(parsed["hitl"], rates["hitl"])
    _, human_ref_bd = trajectory_minutes(parsed["human"], rates["human"])

    return {
        "machine_min": machine_min,
        "hitl_min": hitl_min,
        "agent_min": round(machine_min + hitl_min, 2),
        "machine_breakdown": agent_bd,
        "hitl_breakdown": hitl_bd,
        "human_ref_breakdown": human_ref_bd,  # 참고용 — 공식 human_min은 v0.5 엔진
        "ai_io": io,
        "revision_factor": rf,
        "rationale": parsed["rationale"],
        "notes": notes,
    }
