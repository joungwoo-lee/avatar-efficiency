# trajectory-cost

세션 경로 넣으면 그 세션 비용을 달러로 리턴한다.

```python
from trajectory_cost import session_cost_usd

usd = session_cost_usd(r"C:\Users\joung\.claude\projects\C--proj\<세션ID>.jsonl")
# -> 187.98283   (float, USD)
```

세션 ID 만 넘겨도 된다: `session_cost_usd("1b131c75-92b4-...")`

CLI: `python trajectory_cost.py <경로 또는 세션ID> [--from A] [--to B] [--json] [--project]`

## 구간 계산 (`record_actions_code_api.py` 의 `--from/--to` 와 같은 규약)

```python
usd = session_cost_usd(path, window=("2026-09-03T11:00", "2026-09-03T12:00"))
usd = session_cost_usd(path, window=(1756873200, None))     # epoch 초, 끝까지
d = session_cost(path, window=(None, "2026-09-03T12:00:00+09:00"))   # 처음부터
d["window"]   # {"start", "end", "calls_in", "calls_out"}  (구간 없으면 None)
d["first_ts"], d["last_ts"]   # 세션 전체 기록 시각 범위 (epoch 초)
```

```bash
python trajectory_cost.py <세션.jsonl> --from "2026-09-03T11:00" --to "2026-09-03T12:00"
python trajectory_cost.py <프로젝트 폴더> --project --from 1756873200
```

- 호출 레코드의 `timestamp` 가 닫힌 구간 `[A, B]` 안인 호출만 달러로 합산
- `A`/`B` 는 epoch 초 또는 ISO 8601 (tz 없는 ISO 는 로컬 시각). 한쪽 생략 가능
- 시각 없는 레코드는 같은 파일의 직전 시각을 물려받음. 서브에이전트 파일도 같은 구간으로 거름
- 중복 제거(`message.id`)를 먼저 하고 구간을 자르므로, 구간을 나눠 더하면 전체와 같다
- 비용은 뒤 기록에 따라 달라지는 판정이 없어 `--as-of` 는 없다 (`--to B` 가 그 역할)

`record_actions_code_api.py` 에 붙이는 호출부 예시(임포트·호출 넣을 자리 표시):
`callsite_example.py` — 원본을 고치지 않고 그대로 실행해 확인할 수 있다.
```bash
python callsite_example.py <세션.jsonl 경로>
```

## 포함 범위

- 서브에이전트(`<세션ID>/subagents/*.jsonl`) 비용 포함
- 호출별로 그 모델 단가 적용 (한 세션에 opus/sonnet 섞임)
- 캐시 토큰 별도 단가: `rates.json` 에 모델마다 직접 적혀 있다
  (Opus 5 쓰기 $6.25 / 읽기 $0.50, Sonnet 5 $2.50 / $0.20, Haiku 4.5 $1.25 / $0.10.
   1시간 캐시 쓰기는 그 2배: $10 / $4 / $2. 안 적힌 모델은 input×배수로 계산)
- 같은 호출이 파일에 여러 번 적히므로 `message.id` 로 중복 제거
  (실측: usage 레코드 1804줄 = 실제 호출 867건. 안 하면 2배 넘게 부풀려짐)
- 온프렘 모델은 비용 0 (토큰은 집계). 지정: `onprem_models=[...]` 인자,
  환경변수 `TRAJECTORY_ONPREM_MODELS`, 또는 `rates.json` 의 `onprem_patterns`
- `<synthetic>` 등 `free_models` 레코드(실제 LLM 호출 아님)는 `by_provider["free"]` 에만 남기고
  `total`/`main_agent`/`by_model` 호출 수에서 제외 (message.id 가 UUID 든 문자열이든 동일)
- `min_version`/`max_version`: 세션 레코드의 Claude Code 버전 범위 (usage 포맷 드리프트 추적용)
- 요율표는 `rates.json`. 코드에 숫자 없음

## 분해가 필요할 때

```python
from trajectory_cost import session_cost

d = session_cost(session)
d["trajectory_cost_usd"]        # 전체
d["main_agent"]["cost_usd"]     # 메인 / d["subagents"]["cost_usd"] 서브에이전트
d["by_model"], d["by_agent"], d["onprem"], d["warnings"]
```

`project_cost(폴더)` 는 프로젝트 폴더의 전 세션 합계.

## 주의

값은 API 정가 환산이다(구독제 실청구액 아님). 대화 제목 생성 같은 내부 호출은
트랜스크립트에 안 남아 `/usage` 와 소폭 차이 난다.

테스트: `python test_trajectory_cost.py`
