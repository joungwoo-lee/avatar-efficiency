# OBHE — Outcome-Based Human Effort Estimator

[방법론 문서](./OBHE_결과물_기반_Human_Equivalent_Effort_방법론.md)의 구현.

## 이 방법이 하는 일 — 쉬운 설명

**질문은 하나다: "AI가 만든 이 결과물, 사람이 혼자 만들었다면 몇 시간 걸렸을까?"**

AI가 만든 분량을 그대로 사람 시간으로 바꾸면 안 된다. AI는 필요 없는 것까지
잔뜩 만들기 때문에, 그걸 다 사람이 만든 셈 치면 AI가 실제보다 훨씬 대단해 보인다.
그래서 다음 순서로 계산한다.

| 순서 | 하는 일 | 쉽게 말하면 | 처리 주체 |
|---|---|---|---|
| 1 | 진짜 쓰인 것만 남긴다 | AI가 만들다 버린 것, 중간 산출물, 안 읽을 분량은 계산에서 뺀다 (§3) | LLM **턴1** |
| 2 | 두 가지 시간을 구분한다 | "저걸 통째로 따라 만드는 시간"과 "같은 목적을 사람답게 달성하는 시간"은 다르다. 계산에는 후자를 쓴다 (§4) | LLM **턴2** |
| 3 | 결과물을 알맹이 단위로 센다 | 페이지 수가 아니라 "확인된 사실 31개, 결론 6개, 차트 5개"처럼 센다 (§5) | LLM **턴1** |
| 4 | 사람이 밟았을 길을 그린다 | "자료 찾고 → 읽고 → 비교하고 → 쓰고 → 검토한다" — AI가 실제로 한 방식이 아니라 사람의 정상적인 일 순서다 (§6) | LLM **턴2** |
| 5 | 각 일의 양을 센다 | "자료 15건, 확인할 주장 31개"처럼 결과물에서 셀 수 있는 숫자로 남긴다. 나중에 근거를 따질 수 있다 (§7) | LLM **턴2** |
| 6 | 양 × 단가로 시간을 낸다 | "주장 1개 확인 = 3분"처럼 일마다 단가표가 있고, 어려우면 추가 시간이 붙는다. 단가표는 외부 파일(rate_card.json)이라 조직 데이터로 바꿀 수 있다 (§8·§10) | 코드 |
| 7 | 사람다운 비용도 넣는다 | 사람도 검토하고, 사람도 고쳐 쓴다. 그 시간을 따로 더한다 (§13·§14) | LLM 턴2(검토 행동 포함) + 코드(고쳐쓰기 시간 가산) |
| 8 | 답은 범위로 준다 | "정확히 17.3시간"이 아니라 "보통 15시간, 넉넉히 21시간, 믿을 만한 정도 B" (§17·§18) | 코드 |

**턴1/턴2 표기의 의미**: 품질을 보장하려면 LLM 호출을 두 턴으로 나누는 것이 맞다 —
**턴1**에서 "무엇이 달성됐나"(1·3단계)만 추출하고, **턴2**에서 그 결과만 입력으로
"사람의 작업경로"(2·4·5단계)를 복원하는 구조다. 그래야 잉여물 제거 결과가 독립
산출물로 남아 검사할 수 있고, 턴2가 원문 분량에 끌려가는 오염도 막힌다.
**실제 구현은 처리 속도를 위해 턴1+턴2를 한 프롬프트에 합쳐, LLM 호출은 총 1턴이다.**

**가장 중요한 규칙**: AI(LLM)에게는 "무슨 일을 몇 개 해야 했나"만 묻는다.
**시간은 AI가 정하지 않는다** — 사람 데이터로 만든 단가표가 정한다 (§11).
AI의 시간 감각은 믿을 수 없다는 게 여러 연구의 결론이기 때문이다.

## 구현 개요

AI 최종 결과물(artifact)에서 **기준 인간 작업경로(Human Action Ledger)** 를 복원하고,
외부 **Human Action Rate Card** 의 time equation으로 person-hours를 계산한다.

```
Artifact → (LLM) Human Action Ledger → rate_card.json → P50/P80 시간
```

- LLM은 행동·수량·complexity driver·evidence만 추론한다. **시간을 결정하지 않는다** (§11).
- 요율은 프롬프트에 노출하지 않는다 (수량 역산 오염 방지).
- 결과는 P50/P80 범위 + Confidence(A/B/C)로 제공한다 (§17).

> **구현 노트 — 1턴 vs 2턴**: 방법론 §20은 Layer 1(무엇이 달성됐나 추출)과
> Layer 2(사람의 작업경로 복원)를 별도 층으로 둔다. 품질을 보장하려면 이 둘을
> LLM 2턴으로 분리하는 것이 맞다 — 잉여물 제거 결과가 독립 산출물로 남아 감사
> 가능하고, 2턴째에 원문 대신 추출된 결과만 주면 잉여 분량에 끌려가는 오염도
> 차단된다. 본 구현은 **처리 속도를 위해 두 층을 한 프롬프트에 합쳐 LLM 호출이
> 총 1턴이다.** 1~5단계는 프롬프트 지시로 요청될 뿐 구조적으로 보장되지 않으며,
> 요율 계산·rework 가산·범위 출력만 코드 레벨에서 보장된다.

## 구성

| 파일 | 역할 (방법론 §20 Layer) |
|---|---|
| `rate_card.json` | **외부 설정**: Human Action 카탈로그(H1~H9) + 요율 + complexity driver + rework 비율 |
| `ledger_builder.py` | Layer 1+2 — Outcome 추출 + Reference/Replication Human Path 복원 (LLM 1턴) |
| `rate_engine.py` | Layer 3 — time equation 환산, RHE/HRE/Output Inflation/Confidence 계산 |
| `sim_llm.py` | LLM 미연결 데모용 결정론적 시뮬레이터 |
| `estimate.py` | CLI |
| `examples/sample_ledger.json` | §16 시장분석 보고서 예시 ledger |

## 사용법

```bash
# 1) 작성된 ledger로 계산 (LLM 불필요)
python estimate.py --ledger examples/sample_ledger.json --ai-hours 4

# 2) artifact에서 작업경로 복원(LLM 1턴) 후 계산
python estimate.py --artifact path/to/report.md --ai-hours 4

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
- `meta.rate_confidence` — rate DB 신뢰도. 전체 Confidence는 outcome/path/rate 중 최악값 (§17).

## 실제 LLM 연결

`ledger_builder.restore_paths(artifact_text, llm, card)` 의 `llm` 에
`complete_json(prompt: str, max_tokens: int) -> dict` 계약을 만족하는 클라이언트를 넘기면 된다
(effort-estimator의 `OnpremLLM` 계약과 동일).

## 세 숫자 (§18)

| 지표 | 의미 |
|---|---|
| HRE | AI artifact를 사람이 그대로 복제하는 시간 |
| RHE | 동일 유효 결과를 사람이 정상적으로 달성하는 시간 — **효율 계산의 분모** |
| AI Actual Effort | AI 실행 + HIL 비용 |

겉보기 효율(HRE/AI)과 현실화 효율(RHE/AI)의 차이가 AI 산출물 증폭에 의한 과장이다.
