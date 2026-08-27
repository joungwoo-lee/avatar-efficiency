19s 동안 처리함

네. 최근 Claude Code 트레젝토리라면 세션 단위 실제 토큰 비용을 거의 정확하게 계산할 수 있습니다. 서브에이전트까지 포함 가능합니다.

핵심은 부모 파일만 읽지 않는 것입니다.

~/.claude/projects/<project>/
├── <session-id>.jsonl
└── <session-id>/
    └── subagents/
        ├── agent-xxx.jsonl
        ├── agent-yyy.jsonl
        └── ...

최근 Claude Code는 부모뿐 아니라 서브에이전트 JSONL에도 각 API 호출의 message.usage를 기록합니다. 

각 호출에서 대략 다음을 뽑으면 됩니다.

{
  "model": "...",
  "usage": {
    "input_tokens": ...,
    "output_tokens": ...,
    "cache_creation_input_tokens": ...,
    "cache_read_input_tokens": ...
  }
}

그리고 모델별·호출별로:

cost =
  input_tokens × 일반 input 요율
+ cache_creation_5m × cache-write-5m 요율
+ cache_creation_1h × cache-write-1h 요율
+ cache_read_input_tokens × cache-read 요율
+ output_tokens × output 요율

현재 Anthropic의 캐시 가격 구조는 일반 input 대비 **5분 write 1.25×, 1시간 write 2×, cache read 0.1×**입니다. 모델마다 기본 input/output 가격은 다릅니다. 

여기서 중요한 게 몇 가지 있습니다.

1. 부모 + 모든 서브에이전트를 재귀적으로 합산

중첩 서브에이전트도 포함해야 합니다.

Agent Team도 같은 subagents/ 계열에 기록될 수 있습니다. 



2. message.id/requestId 중복 제거

스트리밍 때문에 동일 호출이 JSONL에 여러 레코드로 보일 수 있어서 그냥 전부 sum()하면 과대계상될 수 있습니다. 



3. 모델을 호출별로 확인

부모가 Opus이고 서브에이전트가 Sonnet/Haiku일 수 있으므로 세션 전체에 단일 요율을 적용하면 안 됩니다.



4. 캐시 토큰을 일반 input으로 계산하면 안 됨

input + cache_creation + cache_read는 물리적 입력 토큰량 계산에는 맞지만, 비용 계산은 각각 다른 단가를 써야 합니다.



5. 세션 JSONL만으로 Claude Code 전체 과금액과 100% 일치한다고 보기는 어려움

Claude Code 내부의 제목 생성 같은 일부 background 호출이 JSONL에 기록되지 않는 사례가 현재도 보고되어 있습니다. /usage가 잡는 값과 transcript 합계 사이에 작은 차이가 날 수 있습니다. 

따라서 지표 이름은 trajectory_token_cost처럼 두고, **“해당 작업 trajectory에서 관측 가능한 모델 호출 비용”**으로 정의하는 편이 정확합니다.




따라서 지금 만드시는 측정기에 붙인다면 machine_min과 별도로 llm_cost_usd를 상당히 신뢰도 높게 실측값으로 넣을 수 있습니다. 특히 부모 + 서브에이전트 비용을 합친 값은 AI 작업량/ROI 분석에 꽤 좋은 별도 축이 됩니다.