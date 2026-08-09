# -*- coding: utf-8 -*-
"""사전 에이전트화 에포트 추정기 (TAEE Phase 1 MVP).

입력: '할일+역할+작업+스킬 작업 지침서' 자유 텍스트
출력: human_only(사람 AI 미사용 에포트), agent(machine + hitl 에포트)

원칙 (docs/effort-estimation/task_agentization_effort_estimator_design.md §37):
  - LLM은 primitive action 수량만 제안한다. 시간을 직접 출력하지 않는다.
  - 시간 = 수량 x 보정요율(rates.json). 요율은 프롬프트에 노출하지 않는다.
  - agent 경로의 사람 시간(HITL)은 machine 시간과 분리해 계산한다.

LLM 계약: OnpremLLM.complete_json(prompt: str, max_tokens: int) -> dict
"""
import json
import sys
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
        return None, ["LLM 응답이 dict가 아님"], True
    if "human" not in raw or "agent" not in raw:
        return None, ["필수 키(human/agent) 누락"], True
    parsed = {
        "human": _validate_path(raw.get("human"), rates["human"], "human", notes),
        "agent": _validate_path(raw.get("agent"), rates["agent"], "agent", notes),
        "hitl": _validate_path(raw.get("hitl", []), rates["hitl"], "hitl", notes),
        "ai_io": raw.get("ai_io") or {},
        "rationale": raw.get("rationale", ""),
    }
    if not parsed["human"] or not parsed["agent"]:
        return None, notes + ["유효 human/agent 항목 0개"], True
    if not parsed["hitl"]:
        notes.append("hitl 비어 있음 — 감독시간 0으로 계산됨(과대평가 위험)")
    return parsed, notes, False


def trajectory_minutes(actions, card):
    """수량 x 요율 환산. breakdown 포함 반환."""
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


class EffortEstimator:
    """llm: complete_json(prompt, max_tokens) -> dict 를 가진 객체 (OnpremLLM 계약)."""

    def __init__(self, llm, rates_path=DEFAULT_RATES_PATH, max_tokens=2000):
        self.llm = llm
        self.max_tokens = max_tokens
        with open(rates_path, encoding="utf-8") as f:
            self.rates = json.load(f)

    def estimate(self, spec_text):
        prompt = build_prompt(spec_text, self.rates)
        raw = self.llm.complete_json(prompt, self.max_tokens)
        parsed, notes, fatal = validate_llm_output(raw, self.rates)
        if fatal:
            retry_prompt = (prompt + "\n\n[재시도] 직전 응답이 유효하지 않았다: "
                            + "; ".join(notes) + "\n스키마를 정확히 지켜 다시 출력하라.")
            raw = self.llm.complete_json(retry_prompt, self.max_tokens)
            parsed, notes2, fatal = validate_llm_output(raw, self.rates)
            notes = notes + ["1회 재시도 수행"] + notes2
            if fatal:
                raise ValueError("LLM 출력 검증 2회 실패: " + "; ".join(notes))

        human_min, human_bd = trajectory_minutes(parsed["human"], self.rates["human"])
        agent_traj_min, agent_bd = trajectory_minutes(parsed["agent"], self.rates["agent"])
        io = ai_io_minutes(parsed["ai_io"], self.rates)
        rf = float(self.rates.get("agent_revision_factor", 1.0))
        machine_min = round((agent_traj_min + io["minutes"]) * rf, 2)
        hitl_min, hitl_bd = trajectory_minutes(parsed["hitl"], self.rates["hitl"])

        leverage = round(human_min / hitl_min, 2) if hitl_min > 0 else None
        automation_share = round(1 - hitl_min / human_min, 3) if human_min > 0 else None

        agent_total = round(machine_min + hitl_min, 2)
        return {
            "human_only": {
                "minutes": human_min,
                "hours": round(human_min / 60, 2),
                "breakdown": human_bd,
            },
            "agent": {
                "minutes": agent_total,
                "hours": round(agent_total / 60, 2),
                "machine": {
                    "minutes": machine_min,
                    "hours": round(machine_min / 60, 2),
                    "breakdown": agent_bd,
                    "ai_io": io,
                    "revision_factor": rf,
                },
                "hitl": {
                    "minutes": hitl_min,
                    "hours": round(hitl_min / 60, 2),
                    "breakdown": hitl_bd,
                },
            },
            "metrics": {
                "human_labor_leverage": leverage,
                "automation_share": automation_share,
            },
            "rationale": parsed["rationale"],
            "confidence": "C (cold-start seed rates, 미보정)",
            "confidence_notes": notes,
        }


def _format_report(result):
    lines = []
    h = result["human_only"]
    a = result["agent"]
    m = result["metrics"]
    lines.append(f"Human-only effort : {h['minutes']:>8.1f} min ({h['hours']} h)")
    lines.append(f"Agent effort      : {a['minutes']:>8.1f} min ({a['hours']} h)")
    lines.append(f"  - machine       : {a['machine']['minutes']:>8.1f} min ({a['machine']['hours']} h)")
    lines.append(f"  - hitl(human)   : {a['hitl']['minutes']:>8.1f} min ({a['hitl']['hours']} h)")
    if m["human_labor_leverage"] is not None:
        lines.append(f"Labor leverage    : {m['human_labor_leverage']}x")
    if m["automation_share"] is not None:
        lines.append(f"Automation share  : {m['automation_share'] * 100:.1f}%")
    lines.append(f"Confidence        : {result['confidence']}")
    if result["rationale"]:
        lines.append(f"Rationale         : {result['rationale']}")
    for n in result["confidence_notes"]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    if not args:
        print("usage: python estimator.py <spec.txt> [--json]", file=sys.stderr)
        return 2
    spec_text = Path(args[0]).read_text(encoding="utf-8")

    from onprem_llm_sim import OnpremLLM
    est = EffortEstimator(OnpremLLM())
    result = est.estimate(spec_text)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
