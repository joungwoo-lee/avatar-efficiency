# trajectory-cost

Claude Code 트랜스크립트(JSONL)를 읽어 **세션 1건에서 실제로 쓴 모델 호출 비용(USD)** 을 계산한다.
서브에이전트 호출까지 전부 포함하고, 온프렘(사내 구축) 모델 호출은 따로 세되 비용은 0으로 잡는다.

참고: `efficiency-calculator/llm-cost-usd.md`

## 쓰는 법

```bash
# 세션 ID 로
python trajectory_cost.py 1b131c75-92b4-5509-a86f-7a3cae0e4bc9

# 트랜스크립트 파일 경로로
python trajectory_cost.py ~/.claude/projects/C--Users-joung-proj/<세션ID>.jsonl --json

# 프로젝트 폴더 전체 합계
python trajectory_cost.py ~/.claude/projects/C--Users-joung-proj --project

# 사내 모델을 명시적으로 무료 처리
python trajectory_cost.py <세션ID> --onprem-model our-internal-7b
```

## 다른 모듈에서 쓰기 (한 줄 임포트 + 한 줄 호출)

`session_api.py` 가 sys.path 에 `trajectory-cost` 를 등록하므로, session-api 계열
모듈(`record_actions_code_api.py` 등) 안에서는 경로 설정 없이 바로 쓴다.

```python
from trajectory_cost import session_cost_usd      # 한 줄

usd = session_cost_usd(session_path)              # 한 줄 -> 2.904538 (float, USD)
```

입력은 세션 ID 또는 트랜스크립트 `.jsonl` 경로 둘 다 받는다(`record_actions_code_api.measure()`
가 받는 것과 같은 값). 출력은 달러 float 하나. 서브에이전트 포함, 온프렘 0원.
모델별·에이전트별 분해가 필요하면 `session_cost()` 를 쓴다.

session-api 밖에서 쓸 때만 경로 한 줄이 더 필요하다:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "trajectory-cost"))
```

복붙용 최소 예시: `example_usage.py` (`python example_usage.py <세션ID 또는 .jsonl>`)

## 파이썬 API 전체


```python
from trajectory_cost import session_cost, project_cost

d = session_cost("<세션ID>")
d["trajectory_cost_usd"]      # 이 세션 총 비용 (USD)
d["main_agent"]["cost_usd"]   # 메인 에이전트 몫
d["subagents"]["cost_usd"]    # 서브에이전트 몫
d["onprem"]["total_tokens"]   # 온프렘으로 처리한 토큰량 (비용은 0)
d["by_model"], d["by_agent"]  # 모델별 / 에이전트별 분해
```

## 어디서 무엇을 읽나

```
~/.claude/projects/<프로젝트>/
├── <세션ID>.jsonl              ← 메인 에이전트
└── <세션ID>/
    ├── subagents/agent-*.jsonl ← 서브에이전트 (isSidechain:true, agentId, attributionAgent)
    └── tool-results/           ← 무시
```

호출 1건 = `message.usage` 한 덩어리:

```json
{"model":"claude-opus-5","usage":{
  "input_tokens":2,"cache_read_input_tokens":33708,
  "cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":21051},
  "output_tokens":617,"speed":"standard"}}
```

## 계산 규칙

호출마다 그 호출의 모델 단가를 각각 적용한다 (부모 Opus + 서브 Sonnet 혼재가 흔함).

```
cost = input_tokens        × input단가
     + cache_write_5m      × input단가 × 1.25
     + cache_write_1h      × input단가 × 2.0
     + cache_read          × input단가 × 0.1
     + output_tokens       × output단가
     + 웹검색 호출수 × $10/1000
```

단가와 온프렘 판정 규칙은 전부 `rates.json` 에 있다 (`models`, `cache_multipliers`,
`server_tools_usd`, `onprem_patterns`, `free_models`).

### 함정 4개 — 다 처리했다

1. **중복 기록**: 같은 `message.id` 가 콘텐츠 블록 수만큼 반복 기록된다. 실측 세션에서
   usage 레코드 1804건 중 실제 호출은 867건 — 그냥 다 더하면 2배 넘게 부풀려진다.
   `message.id` 기준으로 토큰 합이 가장 큰 레코드만 남긴다.
2. **모델 혼재**: 세션 하나에 단일 요율을 적용하면 안 된다. 호출별로 본다.
3. **캐시 토큰**: 캐시 쓰기/읽기를 일반 input 으로 계산하면 안 된다. 배수가 다르다.
4. **모델 ID 날짜 접미사**: `claude-haiku-4-5-20251001` → `claude-haiku-4-5` 로 정규화.

### 온프렘 구분

`rates.json` 의 `onprem_patterns` 정규식(예: `^onprem/`, `^ollama/`, `qwen`, `llama`,
`exaone`, `gpt-oss` …) 에 걸리면 `provider="onprem"`, 비용 0. 토큰은 그대로 집계되므로
"사내 모델로 얼마나 돌렸나" 는 `d["onprem"]` 으로 볼 수 있다.

추가 지정 방법 두 가지:
- `session_cost(..., onprem_models=["our-internal-7b"])` / CLI `--onprem-model`
- 환경변수 `TRAJECTORY_ONPREM_MODELS=our-internal-7b,sllm-13b`

요율표에도 없고 온프렘 패턴에도 안 걸리는 모델은 **비용 0 + `warnings` 에 기록**한다
(조용히 틀리게 계산하지 않는다).

## 정확도

지표 이름을 `llm_cost_usd` 가 아니라 **`trajectory_cost_usd`** 로 둔 이유:
= "이 trajectory 에서 **관측 가능한** 모델 호출 비용". Claude Code 내부 background
호출(대화 제목 생성 등) 일부는 JSONL 에 안 남아서 `/usage` 합계와 소폭 차이가 날 수 있다.
또한 값은 **API 정가 기준**이며, 구독제로 쓰는 경우 실제 청구액이 아니라 "같은 일을
API 로 했다면" 환산액이다.

## 테스트

```bash
python test_trajectory_cost.py
```

## 요율 갱신

`rates.json` 만 고치면 된다 (2026-08-27 캐시 기준: Fable 5 $10/$50, Opus 5·4.8 $5/$25
(fast mode $10/$50), Sonnet 5 $2/$10, Sonnet 4.6 $3/$15, Haiku 4.5 $1/$5, per MTok).
