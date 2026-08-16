# human-effort — 사람 w/o 생성형AI 시간 (분자)

방법론: [doc/requirement_based_human_effort_service_design.md](doc/requirement_based_human_effort_service_design.md) (v0.6)
· 설계 근거: [doc/DESIGN.md](doc/DESIGN.md)
· 프롬프트 설계 근거: [doc/PROMPT_DESIGN.md](doc/PROMPT_DESIGN.md)
· 개선 이력·실측 결과: [../CHANGELOG.md](../CHANGELOG.md)

## 방식 3종

| 방식 | 흐름 | 폴더 | 쓰임 |
|---|---|---|---|
| **요구사항·산출물** | 할일 추출 → 산출물 단위(명사) × 카탈로그 시간분포 → Monte Carlo **P50/P80** | `requirement-based/` | 분포·보수치가 필요한 정식 산정. 카탈로그에 사람의 선별적 읽기가 단위 정의로 내장 |
| **요구사항·행동** | 할일 추출 → 사람 행동(동사) 분해 → × 사람 단가. **숫자는 코드가 닻으로 확정** | `requirement-actions/` | 분모와 같은 단가 체계 — 세션 측정의 분자 후보. 단일호출 모드(`estimate_actions_single`) 있음 |
| **세션기록·행동** | 기록 신호에서 바로 사람 행동 시뮬 × 단가 (할일 안 거침) | `record-actions/` | 교차확인용 — 흔적 없는 노동(조사·판단)을 못 보는 한계 |

공용: `shared/` — 할일 추출기(트랜스크립트 §23 복원 / 아바타는 requirement-based의 A-avatar), 정규화, LLM 시뮬.

## 핵심 설계 3가지

1. **시간은 LLM이 못 정한다** — LLM은 "무엇을 몇 번"만. 시간은 카탈로그(catalog.json)
   또는 단가표(rates.json)를 코드가 곱한다. LLM 출력에 시간 필드가 있으면 자동 제거.
2. **숫자 닻** — 규모 숫자의 결정권을 코드가 가진다:
   - 목표: 할일에 적힌 수량("2,000단어"), 완료조건 개수(=검증 건수),
     할일 건수 × 선별 정독량(사람은 필요한 부분만 읽음)
   - 목표(기록 있을 때): **항해 구조 환산** — AI는 전수 탐색으로 읽고 사람은
     전략적으로 항해한다(논문 "Strategic Navigation or Stochastic Search?").
     기록에서 읽힌 파일을 3등급 — 기여 자료(정독 300단어/건)·훑은 후보(스캔
     60단어/건)·헛읽기(기여 확보 후 시행착오, **0**) — 으로 코드만으로 갈라
     사람 읽기량으로 환산. LLM 0회. 기여 판별 5신호 = 편집·이름 언급·재방문·
     탐색 착지·내용 겹침, 신호는 미래 턴 포함 세션 전체로 판정
     (PROMPT_DESIGN.md).
   - 상한: AI가 실제 읽고 쓴 실측량 — **AI의 과대 탐색·장황함은 천장이지 목표가 아님**
   - 읽기 닻 우선순위: 할일 명시 건수 > 항해 구조 환산 > 실측 상한만
   - 효과: 반복 실행 편차 ±0.1~4%
3. **입력 신호 규칙** — "어떻게 했나"(도구 호출 경로)는 빼고, "뭐가 요구·검토·
   생산됐나"(할일 수량, 검토 자료량, 산출물 순계, 보고 분량, 작업 구조 요약)는 넣는다.

## 할일(요구사항) 단계의 효과 — 14세션 실측 요약

| 업무 유형 | 할일 거침 vs 안 거침 | 판단 |
|---|---|---|
| 조사·분석·대응 (흔적 얇음) | 거침이 2~4배 ↑ — 놓친 노동 복원 | **거침 필수** (존재 이유) |
| 번복·오해 많은 세션 | 거침이 번복 조각을 걸러냄 — 의도 전달 비용은 분모에서만 계상 | 거침 필수 |
| 대형 코딩·문서 (실측 닻 두꺼움) | 무차이 ±20% — 닻이 지배 | 어느 쪽이든 가능 |
| 초소형·잡담 | 측정 무의미 | session-api 게이트가 자동 제외 |

## 사용

```bash
cd requirement-based && python estimator.py ../examples/sample_spec.txt   # 산출물 방식
cd record-actions && python primitive_effort.py <spec.txt>                # 기록·행동 방식
python test_estimator.py                                                  # 전체 테스트 (+ --live)
```

```python
# 산출물 방식 (P50/P80)
from estimator import HumanEffortEstimator
r = HumanEffortEstimator(llm).estimate(avatar_text)
r["effort"]["p50_minutes"], r["effort"]["p80_minutes"]

# 트랜스크립트 → 할일 복원 → 공용 2단계
from transcript_requirements import extract_requirements
req, _ = extract_requirements(llm, transcript_text)
HumanEffortEstimator(llm).estimate_from_requirements(req)

# 요구사항·행동 방식 (닻)
from requirement_actions import estimate_actions_from_requirements, collect_record_stats
estimate_actions_from_requirements(llm, req, record_stats=collect_record_stats(jsonl))
```

## 한계 (현재)

- 카탈로그·단가 대부분 미보정 시드(confidence C) — 절대값은 상대 비교 용도.
  사람 실측 정답지 확보가 최우선 (../CHANGELOG.md 미해결 절).
- AI 장황함: 문서 대량 생성형은 행동 방식이 과대 — 산출물 방식을 쓸 것.
- 판단 깊이: 건당 고정 시간이라 채점형은 어느 방식이든 과소 경향.
