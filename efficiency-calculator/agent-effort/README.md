# agent-effort — 분모(agent_min) 계산 방법론과 모듈

AI 효율(speedup) 산정에서 **분모**를 담당하는 독립 모듈.

```
speedup = human_min ÷ agent_min

분자 = human_min  : 사람이 생성형 AI 없이 직접 하면 걸리는 시간
                    (../human-effort — v0.6 Work Unit 방법론)
분모 = agent_min  : AI 에이전트 + HITL 사람감독을 합쳐서 걸리는 시간
                    (본 모듈 — 구 방식 그대로, primitive count × 요율)
```

사람이 AI 없이 100분 걸릴 일을 AI 써서 10분에 끝나면 효율 10배.

## 분모 계산 방식 (구 방식 그대로 유지, v0.6에서도 안 바꿈)

```
LLM 1회 호출 → agent 경로(기계가 하는 일) + hitl 경로(사람이 감독/개입하는 일)를
              각각 primitive 행동 이름 + count(횟수/단어수)로 분해
코드가 결정적으로 계산 → count × rates.json 요율 = 분
```

```
agent_min = agent_ai_min(기계시간) + agent_human_min(hitl, 사람감독시간)
```

- LLM은 count만 출력한다. 시간·분·요율은 절대 출력하지 않는다.
- 요율은 프롬프트에 노출하지 않는다 (count 역산 오염 방지).
- 카탈로그 밖 primitive·음수 count는 코드가 폐기한다.

## 요율표 (`rates.json`)

### agent (기계) — 사람보다 요율이 훨씬 낮음

| primitive | 의미 | 단위 | 분/단위 |
|---|---|---|---|
| `plan` | 계획 | 건 | 0.5 |
| `search` | 검색 | 쿼리 | 0.5 |
| `read` | 읽기 | 단어 | 0.0005 |
| `classify` | 분류 | 항목 | 0.01 |
| `draft` | 초안작성 | 단어 | 0.002 |
| `edit` | 수정 | 단어 | 0.001 |
| `data_entry` | 입력 | 레코드 | 0.005 |
| `execute` | 도구실행 | 호출 | 0.3 |
| `verify` | 검증 | 증거 | 0.5 |

예: `read`는 사람 0.005분/단어인데 agent는 0.0005분/단어 — 10배 빠름.

### hitl (사람 감독) — "사람이 AI를 부리는 데 드는 오버헤드"

| primitive | 의미 | 단위 | 분/단위 |
|---|---|---|---|
| `instruct` | 지시 작성 | 건 | 1.7 (실측 평균) — 실측 경로는 `0.5 + 0.05×min(단어,60)` 모델 |
| `review` | 검토 | 단어 | 0.006 |
| `approve` | 승인 | 건 | 1.0 |
| `correct` | 수정지시 | 건 | 4.0 |
| `verify` | 수동검증 | 증거 | 3.0 |
| `decide` | 판단 | 건 | 5.0 |
| `draft`/`edit`/`data_entry`/`execute` | 에이전트가 못 해 사람이 직접 마저 하는 잔여 작업 | — | 사람 요율 |

## AI 처리시간(ai_io) — 별도 가산

```
ai_io_minutes = input_words × 0.00002 + output_words × 0.0015   (분)
```

LLM이 실제로 토큰을 읽고/생성하는 시간 (입력 약 3,000자/분 처리, 출력 약 667자/분 생성 속도).

## 최종 합

```
agent_min = (agent primitive count × rates) + ai_io_minutes   ← 기계 시간(agent_ai_min)
          + (hitl primitive count × rates)                     ← 사람 감독 시간(agent_human_min)
```

예: RCA 업무 16.4분 = jira 조회 몇 번(agent search/execute) + AI 응답 처리(ai_io)
+ 사람의 지시·승인·판단(hitl)을 다 합친 값.

## 측정 기조 (분모가 재는 것)

**왜 이렇게 재는가**: AI 에이전트와 사람이 **협업으로 일하는 구도**로 놓는다.
일은 두 주체가 나눠 수행하며, 분모는 이 협업이 소모한 총 에포트 —
**사람이 쓰는 에포트와 AI가 쓰는 에포트를 같은 단위(시간, 분)로 합산**한 값이다.
사람 몫만 세면 AI 자원이 공짜가 되고, AI 몫만 세면 감독 노동이 숨는다.

```
agent_min = agent_human_min(사람 협업자의 에포트, hitl)
          + agent_ai_min(AI 협업자의 에포트, 기계+ai_io)
```

분모 = **"AI를 쓰는 사람의 에포트(분)" + "AI가 실제 소모한 시간"**.

1. **hitl은 wall-clock 측정이 아니라 단서 × 요율 추정이다.** 사람 노동은
   트랜스크립트에 단서(지시 건수, AI 출력 분량)로만 남는다 — 산출물 검토·후작업은
   세션 종료 후 몰아서 할 수 있어 세션 시간을 재는 방식으로는 잡히지 않는다.
   요율 방식은 "이 산출물 분량이면 검토에 이만큼"을 단서에서 추정하므로 세션 밖
   노동까지 포함한다. (타임스탬프는 요율 **값**의 보정 재료로만 쓴다 —
   instruct 보정이 그 예.)
2. **AI 몫은 실제 소모 시간 기준.** 병렬 실행(서브에이전트)은 메인 타임라인에
   이미 흐른 시간이므로 별도 가산하지 않는다. 자원량(총 동작·토큰) 집계가
   필요하면 옵션으로만 켠다.
3. **검토 방식은 산출물이 정한다** (hitl_review_model, seed): 코드는 내용을
   다 읽는 게 아니라 **동작을 돌려 확인**(파일당 2.0분 + 변경분 훑기
   0.002분/단어), 문서·PPT류는 **내용 정독**(0.008분/단어), 설정·데이터는
   표본 확인(파일당 0.5분), 채팅 보고는 **결론(턴 마무리 답변)만 정독**하고
   진행 보고는 훑기(0.002분/단어). Write 재작성은 마지막 판만 과금.
   구식(보고 전량 × 단일 요율)은 모델 없을 때 폴백.
   **검증 위임 강등**: 세션 안에서 자동 테스트가 통과 상태로 끝났으면 코드
   검토가 "직접 돌려 확인(2.0분)"→"결과 서명(0.3분)"으로 강등. 강등 폭은
   커버리지 실측(있으면) 또는 통과 테스트 수÷(수정 코드 파일 수×기대 3건)
   비례 — 형식 테스트 1건으로는 거의 강등되지 않고, 실패 상태면 0.
   없앤 노동은 `automation_saved_min` 필드로 출력된다. 못 재는 것: 테스트의
   실질성(assert 없는 스모크 100개는 통과) — 개수·커버리지는 근사다.
   **구간 계상 (§80)** — `parse_actions(count_window=(A, B))`: 판정(결론
   승격·테스트 상태·확인 시점·파일 첫 쓰기)은 기록 전체, 계상은 사건 시각이
   구간 안인 것만(지시·도구·AI 시간 조각·결론·확인 사건·산출물 단어).
   세션 API `measure(as_of=, window=)`의 분모 몫. 방법서 §5.0.
   **hitl 축약 모드 (§79, §85부터 기본 ON)** — `actual_effort_minutes(hitl_compact=False)`
   / `measure(hitl_compact=False)` / CLI `--hitl-full` 이 §76 전체 모델. 파일 확인을 "확인
   시점에 파일 쓰기 있으면 유형 무관 1건 = min(2.0, 0.5×ln(1+구간 단어/100))"
   로, 테스트 통과 파일은 확인 단어에서 제외, correct 미계상. 이 PC 67세션
   6.09배 → 7.74배. `rates.json hitl_compact_model`.
4. **사람 발화만 지시로 센다.** 긴 세션 기록에는 사람이 타이핑하지 않은
   텍스트가 사용자 메시지 자리에 섞인다 — 문맥 압축 요약(isCompactSummary,
   건당 수천 단어), 시스템 주입 블록(<system-reminder>·<task-notification>·
   명령 출력), 본선 파일에 섞인 병렬 기록(isSidechain). parse_actions가 전부
   제외한다. 실측: 자동 반복 대형 세션에서 이 오염이 "사용자 입력"의 93%,
   제거로 분모 1,160→766분 (CHANGELOG §17).
   단, `<task-notification>`은 지시는 아니지만 **AI 시간의 경계는 아니다**
   (§84): AI가 답을 끝낸 뒤 배경 서브에이전트·배경 명령을 기다린 시간(직전
   AI 기록 → 알림)을 포그라운드 도구 대기와 같은 10분 상한으로 `ai_wall_min`에
   넣는다. 감사용 `bg_wait_min`·`bg_wait_events`·`bg_wait_cut_min`.

## 한계 — 분자·분모 산정 체계 불일치 편향 (해석 주의)

speedup의 분자와 분모는 **서로 다른 산정 체계**로 계산된다:

| | 산정 체계 | 단위 스케일 |
|---|---|---|
| 분자 human_min | v0.6 Work Unit (완성 산출물 단위, 예: 출처 정밀검토 1건=20분급) | 수 분~수십 분/건 |
| 분모 agent_min | primitive 행동 × 저요율 (구 방식) | 초~분/행동 |

같은 업무를 다른 자로 재는 것이므로 **speedup 절대값에는 체계 불일치 편향이 있다** —
v0.6에서 분자 산정만 바뀌어 speedup 배수가 구 버전 대비 계통적으로 커진 것이 그 증상이다
(분모가 "안정적"이어서가 아니라, 두 자가 서로 보정된 적이 없어서다).

따라서:
- speedup 절대값은 실측 보정(human 실측 ↔ catalog.json, agent 실측 trajectory ↔
  rates.json) 전까지 확정치로 쓰지 말 것. 업무 간 **상대 비교** 용도.
- 구 버전 speedup 시계열과 직접 비교 금지 — v0.6 전환 시점에 단절점 표기.
- 보정의 목표는 두 자를 같은 실측 기준(동일 업무의 human-only 실측 시간과
  agent 실측 시간)에 맞추는 것이다.

## 구성

```
agent_effort.py       사전 산정: 업무 설명 → LLM 1회 count 분해 × rates.json → agent_min
transcript_actual.py  실측: Claude Code 트랜스크립트에 기록된 동작을 결정론적으로
                      (LLM 미사용) 세어 기계/HITL 분 환산 — 실행된 세션의 agent_min
rates.json            요율표 (프롬프트 미노출)
test_agent_effort.py  오프라인 테스트
```

## 사용

```bash
python agent_effort.py <spec.txt>            # 업무 설명 → agent_min 리포트 (사전 산정)
python transcript_actual.py <session.jsonl>  # 트랜스크립트 → 실측 agent_min
python agent_effort.py <spec.txt> --json
python test_agent_effort.py                  # 오프라인 테스트 (mock)
```

```python
from agent_effort import estimate_agent_min, speedup
r = estimate_agent_min(llm, spec_text)   # llm: complete_json(prompt, max_tokens)->dict
r["agent_min"], r["agent_ai_min"], r["agent_human_min"]
speedup(human_min, r["agent_min"])       # = human_min / agent_min
```

분자(human_min)는 `../human-effort`의 `HumanEffortEstimator`가 산정한다.
LLM 백엔드는 cursor-proxy(127.0.0.1:18741) — `../human-effort/onprem_llm_sim.py`
계약(`complete_json(prompt, max_tokens) -> dict`)과 동일.

## 요율 합당성 리뷰 (2026-08-16, 실측 보정 전 seed 평가)

**human 카드 — 전반 합당.** 통상 인간 작업속도 범위와 일치:
read 0.005분/단어=정독 200단어/분, draft 0.05분/단어=초안 20단어/분(생각하며 작성),
edit 50단어/분, execute 2분/조작, verify 3분/증거. **catalog.json과 교차 정합 확인**:
document_skim 2~8분/문서 ↔ read×800단어=4분, short_message 5~20분 ↔ draft×200=10분,
section_draft 20~80분 ↔ draft×800=40분 — 두 자(primitive vs Work Unit)가 대략
같은 기준에 앵커돼 있다.

**agent/hitl 카드 — 이슈 3건** (1번은 실측 보정 완료, 2·3번은 표본 확보 후):

1. **hitl.instruct — 실측 보정 완료 (2026-08-16, 표본 1,456건).**
   구 3.0분/건은 실측(검토 몫 제거 net 중앙값 0.61분, 평균 1.74분) 대비 2~5배
   과대였음. 트랜스크립트 타임스탬프(직전 응답→지시 간격)로 보정:
   - 실측 경로(transcript_actual): `instruct = 0.5분(생각 여유) + 0.05분×min(단어수, 60)`
     — 길이 비례 + 생각 여유, 60단어 상한은 붙여넣기(타이핑 아님) 과금 방지
     (실측: 100단어+ 지시의 net 중앙값 0.79분 = 붙여넣기 증거)
   - 사전 추산 경로(agent_effort, 길이 미상): 건당 1.7분(실측 평균)
   rates.json `hitl_instruct_model`에 표본수·출처 기록(source_type=internal_measured).
2. **agent.read/draft ↔ ai_io input/output 경계 모호 (이중 계상 소지).**
   agent_effort는 둘 다 합산한다. 해석 구분: read/draft = 내용 파악·구성 노동,
   ai_io = 순수 토큰 처리 시간. 크기 영향은 작으나(ai_io ≪ trajectory) 보정 시
   통합 검토 대상.
3. agent.search 0.5분/쿼리는 API 호출 자체(수 초)가 아니라 결과 스캔 포함 가정 —
   정의 주석으로 명확화 필요.

human↔agent 배율(read 10배, draft 25배, execute ~7배)은 "AI가 왜 빠른가"의 seed
가정치이며 실측 근거 없음(confidence C) — 절대값 주장에 쓰지 말 것.

## 요율 보정

`rates.json`만 수정 (cold-start seed, confidence C). 실측 trajectory가 쌓이면 교체.
프롬프트에는 절대 넣지 않는다.
