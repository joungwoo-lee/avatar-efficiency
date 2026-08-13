# OBHE — Outcome-Based Human Effort Estimator

[방법론 문서](./OBHE_결과물_기반_Human_Equivalent_Effort_방법론.md)의 구현.
AI 최종 결과물(artifact)에서 **기준 인간 작업경로(Human Action Ledger)** 를 복원하고,
외부 **Human Action Rate Card** 의 time equation으로 person-hours를 계산한다.

```
Artifact → (LLM) Human Action Ledger → rate_card.json → P50/P80 시간
```

- LLM은 행동·수량·complexity driver·evidence만 추론한다. **시간을 결정하지 않는다** (§11).
- 요율은 프롬프트에 노출하지 않는다 (수량 역산 오염 방지).
- 결과는 P50/P80 범위 + Confidence(A/B/C)로 제공한다 (§18).

## 구성

| 파일 | 역할 (방법론 §21 Layer) |
|---|---|
| `rate_card.json` | **외부 설정**: Human Action 카탈로그(H1~H9) + 요율 + complexity driver + rework 비율 |
| `ledger_builder.py` | Layer 1+2 — Outcome 추출 + Reference/Replication Human Path 복원, 3중 추정 집계 (§17) |
| `rate_engine.py` | Layer 3 — time equation 환산, RHE/HRE/Output Inflation/Confidence 계산 |
| `sim_llm.py` | LLM 미연결 데모용 결정론적 시뮬레이터 |
| `estimate.py` | CLI |
| `examples/sample_ledger.json` | §16 시장분석 보고서 예시 ledger |

## 사용법

```bash
# 1) 작성된 ledger로 계산 (LLM 불필요)
python estimate.py --ledger examples/sample_ledger.json --ai-hours 4

# 2) artifact에서 작업경로 복원(3중 추정) 후 계산
python estimate.py --artifact path/to/report.md --judges 3 --ai-hours 4

# JSON 출력
python estimate.py --ledger examples/sample_ledger.json --json report.json

# 테스트
python test_obhe.py
```

## 행동·요율 커스터마이징

`rate_card.json`만 수정하면 된다. 코드 수정 불필요.

```jsonc
"actions": {
  "새행동이름": {
    "taxonomy": "H5",            // H1~H9 (문서 §6 taxonomy)
    "label": "설명",
    "unit": "수량 단위",
    "base_min": 10.0,            // 단위당 기본시간(분)
    "drivers": {                 // time equation 추가항 (§10)
      "driver이름": { "add_min": 5.0, "label": "왜 어려운가" }
    }
  }
}
```

- `--rates my_rate_card.json` 으로 조직별 카드 교체 가능 (§9 local calibration).
- `expected_rework.ratio` — Normal Human Rework 비율 (§14).
- `meta.rate_confidence` — rate DB 신뢰도. 전체 Confidence는 outcome/path/rate 중 최악값 (§18).

## 실제 LLM 연결

`ledger_builder.restore_paths(artifact_text, llm, card, judges=3)` 의 `llm` 에
`complete_json(prompt: str, max_tokens: int) -> dict` 계약을 만족하는 클라이언트를 넘기면 된다
(effort-estimator의 `OnpremLLM` 계약과 동일).

## 세 숫자 (§19)

| 지표 | 의미 |
|---|---|
| HRE | AI artifact를 사람이 그대로 복제하는 시간 |
| RHE | 동일 유효 결과를 사람이 정상적으로 달성하는 시간 — **효율 계산의 분모** |
| AI Actual Effort | AI 실행 + HIL 비용 |

겉보기 효율(HRE/AI)과 현실화 효율(RHE/AI)의 차이가 AI 산출물 증폭에 의한 과장이다.
