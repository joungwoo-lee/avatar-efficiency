# -*- coding: utf-8 -*-
"""분자 모듈: Claude Code 트랜스크립트 → 실제 수행된 기계·HITL 동작 × 요율 (분).

측정 기조: 분모 = "AI를 쓰는 사람의 에포트(분)" + "AI가 실제 소모한 시간".
- hitl(사람 몫)은 wall-clock이 아니라 **단서 × 요율**로 추정한다 — 사람 노동은
  트랜스크립트에 단서(지시 건수·AI 출력 분량)로만 남고, 산출물 검토·후작업은
  세션 종료 후 몰아서 할 수 있어 세션 시간 측정으로는 잡히지 않는다.
- AI 몫은 실제 소모 시간 기준 — 병렬 실행(서브에이전트)은 메인 타임라인에
  이미 흐른 시간이므로 별도 가산하지 않는다(합산은 session_api에서 옵션).

LLM을 쓰지 않는다 — 트랜스크립트에 기록된 동작을 결정론적으로 세고
rates.json의 agent/hitl 카드 요율을 곱한다.

동작 → 요율 매핑 (rates.json):
  기계(machine):
    execute  = tool_use 블록 수            × agent.execute (tool_call_count)
    read     = tool_result 내용 단어수      × agent.read    (word_count)
    draft    = assistant 텍스트 단어수      × agent.draft   (word_count)
  사람(hitl):
    instruct = 사용자 텍스트 메시지 수       × hitl.instruct (instruction_count)
    review   = assistant 텍스트 단어수      × hitl.review   (word_count)
               (사람이 읽어야 하는 AI 출력)
    correct  = 사용자 중단(interrupt) 횟수  × hitl.correct  (correction_count)

집계 제외: thinking 블록(사용자 비노출), meta·snapshot 라인, tool_result만 있는
user 턴(사람 발화 아님). sidechain(서브에이전트)은 기계 동작으로 포함.
"""
import json
from pathlib import Path

try:
    from .agent_effort import DEFAULT_RATES_PATH, load_rates
except ImportError:
    from agent_effort import DEFAULT_RATES_PATH, load_rates


def _words(text):
    return len(text.split()) if isinstance(text, str) else 0


def _content_blocks(message):
    content = (message or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _result_words(block):
    """tool_result 내용 단어수 — 문자열 또는 blocks 리스트."""
    content = block.get("content")
    if isinstance(content, str):
        return _words(content)
    total = 0
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                total += _words(c.get("text", ""))
    return total


def parse_actions(jsonl_path):
    """트랜스크립트 1개 → 동작 카운트. 반환 dict:
    tool_calls, tool_result_words, assistant_words, user_instructions,
    user_words, interrupts, session_id, first_ts, last_ts
    """
    counts = {"tool_calls": 0, "tool_result_words": 0, "assistant_words": 0,
              "user_instructions": 0, "user_words": 0, "interrupts": 0,
              "instruction_word_list": [],
              "session_id": None, "first_ts": None, "last_ts": None}
    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            counts["session_id"] = counts["session_id"] or rec.get("sessionId")
            ts = rec.get("timestamp")
            if ts:
                counts["first_ts"] = counts["first_ts"] or ts
                counts["last_ts"] = ts
            rtype = rec.get("type")
            if rtype not in ("user", "assistant") or rec.get("isMeta"):
                continue
            blocks = _content_blocks(rec.get("message"))

            if rtype == "assistant":
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        counts["tool_calls"] += 1
                    elif b.get("type") == "text":
                        counts["assistant_words"] += _words(b.get("text", ""))
                continue

            # user 턴: 사람 발화 vs tool_result 구분
            human_text = ""
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    counts["tool_result_words"] += _result_words(b)
                elif b.get("type") == "text":
                    human_text += b.get("text", "") + " "
            human_text = human_text.strip()
            if human_text:
                if human_text.startswith("[Request interrupted"):
                    counts["interrupts"] += 1
                else:
                    counts["user_instructions"] += 1
                    w = _words(human_text)
                    counts["user_words"] += w
                    counts["instruction_word_list"].append(w)
    return counts


def actual_effort_minutes(counts, rates=None):
    """동작 카운트 × rates.json 요율 → 분. 반환:
    {machine_min, hitl_min, total_min, breakdown{...}}
    """
    r = rates or load_rates(DEFAULT_RATES_PATH)
    a, h = r["agent"], r["hitl"]
    machine = {
        "execute": counts["tool_calls"] * a["execute"]["min_per_unit"],
        "read": counts["tool_result_words"] * a["read"]["min_per_unit"],
        "draft": counts["assistant_words"] * a["draft"]["min_per_unit"],
    }
    im = r.get("hitl_instruct_model")
    if im:  # 실측 보정 모델: base + per_word×min(단어수, cap) — 붙여넣기 과금 방지
        wl = counts.get("instruction_word_list") or              [0] * counts["user_instructions"]
        instruct_min = sum(im["base_min"]
                           + im["per_word_min"] * min(w, im["word_cap"])
                           for w in wl)
    else:  # 폴백: 건당 평균 요율
        instruct_min = counts["user_instructions"] * h["instruct"]["min_per_unit"]
    hitl = {
        "instruct": instruct_min,
        "review": counts["assistant_words"] * h["review"]["min_per_unit"],
        "correct": counts["interrupts"] * h["correct"]["min_per_unit"],
    }
    machine_min = round(sum(machine.values()), 2)
    hitl_min = round(sum(hitl.values()), 2)
    return {
        "machine_min": machine_min,
        "hitl_min": hitl_min,
        "total_min": round(machine_min + hitl_min, 2),
        "breakdown": {
            "machine": {k: round(v, 2) for k, v in machine.items()},
            "hitl": {k: round(v, 2) for k, v in hitl.items()},
        },
        "counts": counts,
    }


def measure(jsonl_path, rates_path=DEFAULT_RATES_PATH):
    """편의 함수: 파일 경로 → actual_effort_minutes 결과."""
    return actual_effort_minutes(parse_actions(jsonl_path),
                                 load_rates(rates_path))


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        m = measure(p)
        c = m["counts"]
        print(f"{Path(p).name}: machine={m['machine_min']}min "
              f"hitl={m['hitl_min']}min total={m['total_min']}min "
              f"(tools={c['tool_calls']}, instr={c['user_instructions']}, "
              f"aw={c['assistant_words']})")
