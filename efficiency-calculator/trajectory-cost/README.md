# trajectory-cost

세션 경로 넣으면 그 세션 비용을 달러로 리턴한다.

```python
from trajectory_cost import session_cost_usd

usd = session_cost_usd(r"C:\Users\joung\.claude\projects\C--proj\<세션ID>.jsonl")
# -> 187.98283   (float, USD)
```

세션 ID 만 넘겨도 된다: `session_cost_usd("1b131c75-92b4-...")`

CLI: `python trajectory_cost.py <경로 또는 세션ID>`

## 포함 범위

- 서브에이전트(`<세션ID>/subagents/*.jsonl`) 비용 포함
- 호출별로 그 모델 단가 적용 (한 세션에 opus/sonnet 섞임)
- 캐시 토큰 별도 단가: 저장 5분 1.25배 / 1시간 2배, 읽기 0.1배
- 같은 호출이 파일에 여러 번 적히므로 `message.id` 로 중복 제거
  (실측: usage 레코드 1804줄 = 실제 호출 867건. 안 하면 2배 넘게 부풀려짐)
- 온프렘 모델은 비용 0 (토큰은 집계). 지정: `onprem_models=[...]` 인자,
  환경변수 `TRAJECTORY_ONPREM_MODELS`, 또는 `rates.json` 의 `onprem_patterns`
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
