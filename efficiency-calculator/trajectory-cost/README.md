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
   1시간 캐시 쓰기는 그 2배: $10 / $4 / $2. 안 적힌 모델은 input×배수로 계산.
   Fable 5.1 / Mythos 5.1 은 input $10 / output $50, 쓰기 $12.50 / 1시간 $20 인데
   읽기만 $0.25 — 다른 모델의 0.1x 가 아니라 0.025x 라 배수 계산으로는 안 나온다.
   Fable 5 / Mythos 5 는 같은 단가에 읽기 $1.00)
- 같은 호출이 파일에 여러 번 적히므로 `message.id` 로 중복 제거
  (실측: usage 레코드 1804줄 = 실제 호출 867건. 안 하면 2배 넘게 부풀려짐)
- 요율표에 없는 모델은 온프렘으로 간주해 비용 0 (토큰은 집계).
  요율표에 있어도 온프렘으로 지정 가능: `onprem_models=[...]` 인자,
  환경변수 `TRAJECTORY_ONPREM_MODELS`, 또는 `rates.json` 의 `onprem_patterns`
- `<synthetic>` 등 `free_models` 레코드(실제 LLM 호출 아님)는 `by_provider["free"]` 에만 남기고
  `total`/`main_agent`/`by_model` 호출 수에서 제외 (message.id 가 UUID 든 문자열이든 동일)
- `min_version`/`max_version`: 세션 레코드의 Claude Code 버전 범위 (usage 포맷 드리프트 추적용)
- 기본 요율표는 `rates.json`. 공식 가격은 별도로 자동 갱신한다.

## 공식 요금 자동 갱신

계산은 저장된 가격으로 바로 진행한다. 인터넷 연결이나 다운로드 완료를 기다리지 않는다.

- 기본 요율표와 마지막 저장본을 읽어 계산한다. 확인 후 24시간이 지났으면
  별도 프로세스가 [Anthropic 공식 요금표](https://platform.claude.com/docs/en/about-claude/pricing.md)를 받는다.
- 계산 명령이 먼저 끝나도 갱신 작업은 계속된다. Windows에서는 창을 띄우지 않는다.
- 다운로드와 가격 검증을 모두 마친 뒤 저장본을 교체한다. 완료된 가격은 **다음 계산부터** 적용한다.
  한 계산 안에서는 같은 요율표를 사용한다. 프로젝트 합계도 동일하다.
- 인터넷 연결 실패, 요금표 형식 변경, 저장 실패 시 기존 가격을 유지한다.
  실패 후에는 15분이 지난 뒤 실행되는 계산에서 다시 갱신을 시도한다.
- 저장본이 없거나 손상됐으면 기본 `rates.json`을 쓴다.
  표에 없는 모델은 온프렘으로 간주해 비용 0으로 계산한다.
- 입력·출력·5분/1시간 캐시 쓰기·캐시 읽기·빠른 응답·검색 요금을 갱신한다.
  입력 길이에 따라 가격이 달라지는 모델도 반영한다. 입력 길이는 일반 입력과
  캐시 쓰기·읽기 토큰을 합산하며 출력 토큰은 포함하지 않는다.
- 결과의 `pricing.source`와 `pricing.checked_at`에 적용한 가격의 출처와 확인 시각을 남긴다.
  이는 요금 적용 시작일이 아니다. 과거 세션도 선택된 요율표의 가격으로 환산한다.

저장 위치: Windows는 `%LOCALAPPDATA%/trajectory-cost/rates.json`,
그 외에는 `$XDG_CACHE_HOME/trajectory-cost/rates.json` 또는 `~/.cache/trajectory-cost/rates.json`.
`TRAJECTORY_RATES_CACHE` 환경변수로 저장 위치를 바꿀 수 있다. 원본 `rates.json`은 바꾸지 않는다.

갱신 없이 저장된 가격만 쓰려면 `load_rates(auto_update=False)` 또는
`TRAJECTORY_RATES_AUTO_UPDATE=0`을 사용한다. `load_rates(path)`는 지정한 파일만 읽고
자동 갱신이나 저장본을 사용하지 않는다. 요율표를 고정하려면
`session_cost(session, rates=load_rates(path))`로 호출한다.

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

테스트: `python test_trajectory_cost.py`, `python test_rate_updates.py`.
테스트에서는 실제 인터넷을 사용하지 않는다. 다운로드를 멈춘 상태에서 계산 명령이
끝나는지, 명령이 끝난 후 갱신 작업이 완료되는지도 확인한다.
