# effort-estimator — 사전 에이전트화 에포트 추정기 (TAEE Phase 1 MVP)

설계: [../docs/effort-estimation/task_agentization_effort_estimator_design.md](../docs/effort-estimation/task_agentization_effort_estimator_design.md)

**입력**: `할일+역할+작업+스킬` 작업 지침서 자유 텍스트
**출력**: `human_only`(사람 AI 미사용 에포트) · `agent.machine`(기계 에포트) · `agent.hitl`(에이전트 운용에 필요한 사람 에포트) + leverage/automation share

핵심 원칙 (설계서 §37):
- LLM은 primitive action **수량만** 제안. 시간을 직접 출력하지 않음.
- 시간 = 수량 × 보정요율(`rates.json`). **요율은 프롬프트에 미노출** (count 역산 오염 방지).
- HITL을 machine과 분리 — 감독시간을 숨기면 leverage 과대평가.

## 구성

```
estimator.py        핵심: 프롬프트 생성 → LLM 1회 호출(+검증실패 시 1회 재시도) → 수량×요율 환산
rates.json          primitive 요율표 (cold-start seed, confidence C — 실측으로 보정할 것)
onprem_llm_sim.py   OnpremLLM.complete_json(prompt, max_tokens)->dict 시뮬 (cursor-proxy 백엔드)
test_estimator.py   단위테스트(mock) + --live 프록시 실호출 테스트
examples/           샘플 작업 지침서
```

## 사용

```bash
python estimator.py examples/sample_spec.txt          # 리포트 출력
python estimator.py examples/sample_spec.txt --json   # JSON 출력
python test_estimator.py                              # 오프라인 테스트
python test_estimator.py --live                       # + 프록시 라이브 테스트
```

env: `AE_LLM_BASE`(기본 `http://127.0.0.1:18741/v1`), `AE_LLM_MODEL`(기본 `gpt-5-mini`)

## 실환경(mm_app) 연결

`onprem_llm_sim.OnpremLLM`은 실환경 `mm_app/onprem-llm/onprem_llm.py`의
`OnpremLLM.complete_json(prompt: str, max_tokens: int) -> dict` 계약과 동일.
교체는 `EffortEstimator(OnpremLLM())`에 실물 인스턴스를 주입하면 끝.

## 한계 (MVP)

- P50 점추정만. P80/Monte Carlo/DAG는 Phase 2~3 (설계서 §36).
- `rates.json`은 seed 값 — 절대값은 confidence C, 업무 간 상대 비교 용도로 유효.
- 큰 업무는 단발 수량 추정이 흔들림 — Work Unit 분해 2회 체인은 추후.
