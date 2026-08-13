# OBHE — Outcome-Based Human Effort Estimator

[방법론 문서](./OBHE_결과물_기반_Human_Equivalent_Effort_방법론.md)의 구현.

**AI가 만든 결과물 파일을 넣으면 "사람이 혼자 만들었다면 몇 시간"을 계산한다.**
답은 "보통 15시간, 넉넉히 21시간, 믿을 만한 정도 B"처럼 범위로 나온다.

## 어떻게 돌아가나

방법론의 8단계(문서 §2)를 그대로 구현했다. LLM 호출은 **총 1턴**이다.

```
결과물 파일
   │
   ▼  ledger_builder.py — LLM 1턴 (방법론 단계 1~5)
   │   프롬프트: 작업 지시 + 규칙 + 행동 카탈로그(단가 없음) + 결과물 원문
   │   응답:     행동 장부 JSON ("무슨 일을 몇 개" + 근거)
   ▼
   │  rate_engine.py — 코드, LLM 없음 (방법론 단계 6~8)
   │   장부의 수량 × rate_card.json의 단가 → 고쳐쓰기 비용 가산 → 신뢰도 판정
   ▼
P50/P80 시간 리포트 (RHE·HRE·효율 지표)
```

- LLM은 행동과 수량만 답한다. **시간은 LLM이 정하지 않는다** — 단가표가 정한다.
- 단가는 프롬프트에 노출하지 않는다 (LLM이 시간에 맞춰 수량을 역산하는 오염 방지, 문서 §4).
- LLM이 카탈로그에 없는 행동을 지어내면 코드가 걸러낸다.

## 파일 구성

| 파일 | 담당 (방법론 매핑) |
|---|---|
| `rate_card.json` | **외부 설정** — 행동 카탈로그(H1~H9) + 단가 + 어려움 조건 + 고쳐쓰기 비율 (§5) |
| `ledger_builder.py` | 단계 1~5 — 프롬프트 생성, LLM 1턴 호출, 응답 정리·환각 방어 (§4) |
| `rate_engine.py` | 단계 6~8 — 단가 곱셈, 고쳐쓰기 가산, 세 숫자·신뢰도 계산 (§6) |
| `sim_llm.py` | 실제 LLM 미연결 시 데모용 가짜 LLM |
| `estimate.py` | CLI |
| `examples/sample_ledger.json` | 문서 §6 예시를 장부로 옮긴 것 |

## 사용법

```bash
# 1) 결과물 파일에서 바로 계산 (LLM 1턴, 기본은 데모용 SimLLM)
python estimate.py --artifact path/to/report.md --ai-hours 4

# 2) 이미 작성된 장부(JSON)로 계산 (LLM 불필요)
python estimate.py --ledger examples/sample_ledger.json --ai-hours 4

# JSON 저장
python estimate.py --ledger examples/sample_ledger.json --json report.json

# 테스트
python test_obhe.py
```

`--ai-hours` 는 AI 작업에 실제로 든 시간(사람 지시·검토 포함). 넣으면 효율 지표가 같이 나온다.

## 리포트 읽는 법

| 항목 | 뜻 |
|---|---|
| RHE P50 / P80 | 사람이 정상적으로 달성하는 시간 — 보통 / 넉넉히 |
| HRE | 결과물을 통째로 복제하는 시간 |
| Output Inflation | HRE ÷ RHE — AI가 필요 이상으로 만든 정도 |
| 겉보기 효율 | HRE ÷ AI 시간 — 부풀려진 값 |
| 현실화 효율 | RHE ÷ AI 시간 — **믿어야 할 값** |
| Confidence | 결과 추출 / 경로 복원 / 단가표 신뢰도 중 최악값 |

## 행동·단가 바꾸는 법

`rate_card.json`만 고치면 된다. 코드 수정 불필요. `--rates 내파일.json`으로
조직별 단가표 교체 가능.

```jsonc
"actions": {
  "새행동이름": {
    "taxonomy": "H5",            // H1~H9 분류 (문서 §5)
    "label": "설명",
    "unit": "세는 단위",
    "base_min": 10.0,            // 단위당 기본 단가(분)
    "drivers": {                 // 어려움 조건별 추가 단가
      "조건이름": { "add_min": 5.0, "label": "왜 어려운가" }
    }
  }
}
```

- `expected_rework.ratio` — 고쳐쓰기 비용 비율 (단계 7)
- `meta.rate_confidence` — 단가표 신뢰도 (A/B/C)

## 실제 LLM 연결

`ledger_builder.restore_paths(artifact_text, llm, card)` 의 `llm` 에
`complete_json(prompt: str, max_tokens: int) -> dict` 를 구현한 클라이언트를
넘기면 된다 (effort-estimator의 `OnpremLLM` 계약과 동일). 기본 `SimLLM`은
문서 신호(section·표·URL 수)로 장부를 흉내 내는 데모용이다.

## 알려둘 것 — 1턴의 한계

문서 §4의 확장 옵션대로, 품질을 더 보장하려면 "결과 추출"과 "경로 복원"을
LLM 2턴으로 나누는 것이 맞다. 본 구현은 **처리 속도를 위해 한 프롬프트(1턴)에
합쳤다.** 단계 1~5는 프롬프트 지시로 요청될 뿐 구조적으로 보장되지 않으며,
단가 곱셈·고쳐쓰기 가산·범위 출력(단계 6~8)만 코드 레벨에서 보장된다.
