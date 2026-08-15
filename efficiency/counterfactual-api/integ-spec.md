# 기존 Counterfactual API 통합 스펙

## 1. LLM 계약 (필수 — 이것만 지키면 백엔드 교체 자유)

```python
class OnpremLLM:  # 또는 동등 인터페이스
    def complete_json(self, prompt: str, max_tokens: int) -> dict:
        """LLM 호출 → JSON dict 반환. 실패 시 예외 raise."""
```
- 실환경: `mm_app/onprem-llm/onprem_llm.py`
- 신규 산정기는 반드시 이 시그니처(`complete_json(prompt, max_tokens) -> dict`)만 구현하면 어댑터가 통째로 교체 가능.

## 2. Estimator 레벨 계약 (`compat.py` 패턴)

```python
class CounterfactualEstimator:
    def __init__(self, llm=None, rates_path=DEFAULT_RATES_PATH, max_tokens=2000): ...

    def estimate_task(self, title: str, context: str, role: str,
                      skill_names: list[str], detail: str) -> dict:
        """반드시 예외 raise 금지 — 실패 시 error 필드에 문자열."""
```

**입력** (전부 자유 텍스트/리스트, None 불허 → 빈 문자열/빈 리스트로):
| 필드 | 타입 | 설명 |
|---|---|---|
| `title` | str | 업무 제목 |
| `context` | str | 업무 맥락 |
| `role` | str | 소속 역할명 |
| `skill_names` | list[str] | 연결된 스킬 이름 목록(중복 허용) |
| `detail` | str | 업무 상세본문 |

**출력 스키마 (반드시 이 키 전부 존재, 값 없으면 `None`)**:
```json
{
  "error": null,
  "human_min": 25.0,
  "agent_min": 20.57,
  "agent_human_min": 12.0,
  "agent_ai_min": 8.57,
  "saved_min": 4.43,
  "speedup": 1.22,
  "human_breakdown": {"search": 10.0, "read": 2.5, "...": "..."},
  "agent_breakdown": {"plan": 0.5, "...": "...",
    "ai_io": {"input_words": 1000.0, "output_words": 700.0, "minutes": 4.22}},
  "rationale": "한 줄 근거 문자열",
  "confidence": "C (cold-start seed rates, 미보정)",
  "confidence_notes": []
}
```
- `speedup = human_min / agent_min` (agent_min>0 아니면 `null`)
- `saved_min = human_min - agent_min`
- 실패 시: `{"error": "메시지", "human_min": null, "agent_min": null, ...전부 null}`

## 3. 계산 카탈로그 계약 (`rates.json` 형식 — 신규 방법론도 이 구조를 채워야 함)

```json
{
  "human":  {"<primitive>": {"unit": "<count단위>", "min_per_unit": <float>}, ...},
  "agent":  {"<primitive>": {"unit": "...", "min_per_unit": <float>}, ...},
  "hitl":   {"<primitive>": {"unit": "...", "min_per_unit": <float>}, ...},
  "ai_io":  {"input_words_min_per_word": <float>, "output_words_min_per_word": <float>},
  "agent_revision_factor": 1.0
}
```
**규칙**: 이 rate/unit 값은 **LLM 프롬프트에 절대 노출 금지**(count 역산 오염 방지) — LLM은 primitive 이름과 count(수량)만 출력, minutes 환산은 코드가 rates.json으로 계산.

**LLM 출력 스키마(내부, `build_prompt`가 강제)**:
```json
{
  "human": [{"primitive": "search", "count": 3}, ...],
  "agent": [{"primitive": "draft", "count": 40}, ...],
  "hitl":  [{"primitive": "instruct", "count": 1}, ...],
  "ai_io": {"input_words": 1000, "output_words": 700},
  "rationale": "..."
}
```
- primitive 이름은 반드시 `rates.json`의 human/agent/hitl 카탈로그에 등록된 이름만 (카탈로그 밖 이름 폐기)

## 4. Analyzer 레벨 계약 (`analysis_cf.py::CounterfactualAvatarAnalyzer`)

```python
class CounterfactualAvatarAnalyzer:
    def __init__(self, avatars: AvatarSource, estimator=None, max_workers=5): ...
    def analyze_card(self, card_id: str, force: bool = False) -> dict: ...
    def average_cards(self, card_summaries, progress=None, prev=None) -> dict: ...
```

- `avatars: AvatarSource` — `interfaces.py` Protocol 준수 (`card()/role()/task()` 메서드로 카드→역할→업무 계층 조회)
- 카드 안의 모든 (role, task)를 펼쳐 `estimator.estimate_task()` 를 **ThreadPoolExecutor(max_workers)** 로 병렬 호출
- 캐시: `cache/counterfactual_single/{card_id}.json`, `content_updated_at` 동일하면 LLM 재호출 skip

**`analyze_card()` 출력 스키마**:
```json
{
  "card": {"id": "...", "name": "...", "responsibility": "..."},
  "roles": [
    {"role_id": "...", "title": "...",
     "tasks": [{"task_id": "...", "title": "...", "skills": [...], **estimate_task 출력}]}
  ],
  "summary": {
    "method": "counterfactual (human manual vs skill-agent, local-LLM)",
    "total_tasks": 1,
    "human_total_min": 25.0,
    "agent_total_min": 20.6,
    "saved_total_min": 4.4,
    "overall_speedup": 1.22
  },
  "_content_updated_at": "2026-07-16T02:28:27.253374Z",
  "_from_cache": false
}
```
- `overall_speedup = tot_human_min / tot_agent_min` (합산 기준, 개별 task speedup 평균 아님)
- 전체 업무 실패(`human_total_min==0`)면 캐시 쓰지 않음(재시도 유도)

## 5. HTTP API 계약 (`server.py`)

```
GET /api/cards/{card_id}/counterfactual?force=<bool>
Header: X-AFT-Key: <key>   (없으면 config.AFQ_KEY → AFT_KEY 폴백)

200 → analyze_card() 반환 그대로
502 → {"detail": "<예외 메시지>"}
```

## 6. 필수 준수사항 (신규 개발 시)

1. **시간 출력 LLM 금지** — LLM은 수량(count)만, 분(minutes) 환산은 결정적 코드
2. **rate/unit 프롬프트 미노출**
3. **estimate_task() 시그니처·출력 키 100% 동일 유지** — 다른 값이어도 키 누락 불가
4. **speedup 필드 채우기 필수** — `agent_min`을 반드시 계산(v0.5처럼 `None` 반환하면 `analyze_card`의 `tot_a += out["agent_min"]` 이 `TypeError`)
5. `analyze_card`/`average_cards`의 summary 키(`human_total_min`, `agent_total_min`, `saved_total_min`, `overall_speedup`) 이름·의미 그대로

이 스펙대로 새 산정기를 짜면 `compat.py`만 교체(또는 `CounterfactualEstimator` 클래스를 그대로 구현)해서 **`analysis_cf.py`/`server.py`/`app.js` 전부 무수정으로 drop-in 교체** 가능.