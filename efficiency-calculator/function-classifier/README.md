# function-classifier — 긴 트랜스크립트 → 펑션(부서 내 업무 구분) 분류

세션 기록 전체를 LLM에 넣으면 토큰 낭비. `condense.py`가 원본의 **1~2%**(실측)로 줄이고,
`classify.py`가 주어진 펑션 목록(예: sw개발·sw검증·hw설계)으로 **비율 분류**한다.

```python
from classify import classify
r = classify(llm, "session.jsonl", ["sw개발", "sw검증", "hw설계", "문서작성"])
# {"shares": {"sw개발": 55, "sw검증": 30, "문서작성": 15}, "primary": "sw개발",
#  "evidence": "...", "condense_stats": {"ratio": 0.0082, "est_tokens": 10312, ...}}
```
LLM 계약은 레포 공통 `llm.complete_json(prompt, max_tokens) -> dict`. 호출 1회.

## 구간 옵션 (trajectory-cost / record_actions_code_api 와 같은 규약)

```python
c = condense("session.jsonl", window=("2026-09-03T11:00", "2026-09-03T12:00"))
c = condense("session.jsonl", window=(1756873200, None))          # epoch 초, 끝까지
r = classify(llm, "session.jsonl", fns, window=(None, "2026-09-03T12:00:00+09:00"))
c["meta"]["window"]              # {"start": epoch, "end": epoch|None} (없으면 None)
c["meta"]["records_in_window"]   # 구간 안 레코드 수 / meta.records 전체
```
```bash
python condense.py session.jsonl --from "2026-09-03T11:00" --to "2026-09-03T12:00" --text
```
- 레코드 `timestamp`가 닫힌 구간 `[A, B]` 안인 것만. A/B는 epoch 초 또는 ISO 8601(tz 없으면 로컬), 한쪽 생략 가능
- 시각 없는 레코드는 직전 시각 상속 (trajectory_cost.normalize_window/in_window/parse_time 재사용)
- META 히스토그램·USER·ASSISTANT·FINAL 전부 구간 안 레코드로만 구성 → 구간별 펑션 비중을 따로 낼 수 있다
- 실측: 1.1MB 세션의 15분 구간 → 648 레코드 중 168, 추정 2.2k 토큰

```bash
python condense.py session.jsonl              # JSON 출력 (구조체)
python condense.py session.jsonl --text       # LLM 투입 텍스트 그대로
python condense.py session.jsonl --from A --to B   # 구간
python classify.py session.jsonl "sw개발,sw검증,hw설계"   # 프롬프트만 출력(LLM 미호출)
python test_condense.py                       # 단위 테스트 (summarize_match는 runner 주입, CLI 미호출)
python test_condense.py --real                # ~/.claude/projects 실파일 감량률
```

## 하이쿠 서머리+매칭 (summarize_match.py) — 호출한 클로드 설정 그대로

```bash
python summarize_match.py --pid <claude PID> --condensed c.json --functions org.json [--out r.json]
python summarize_match.py --pid <PID> --transcript session.jsonl --functions org.json [--from A --to B]
```
```python
from summarize_match import summarize_match
r = summarize_match(pid, "c.json", "functions.example.json")
# {"summary": "...", "functions": {"hw검증": 80, "hw설계": 20}, "primary": "hw검증",
#  "products": ["UART IP"], "evidence": "...", "meta": {"exe", "cwd", "config_dir", "usage", ...}}
```

| 보장 | 방법 | 실기동 검증(2026-09-04) |
|---|---|---|
| 그 클로드의 설정 | PID → 실행파일(WMI)·cwd·환경변수(PEB 메모리 읽기, Linux는 /proc) 상속. CLAUDE_CONFIG_DIR·ANTHROPIC_* 그대로, 중첩 세션 마커만 제거 | exe·config_dir 정확 |
| 하이쿠 | `--model haiku`, 상위 세션 `ANTHROPIC_MODEL` 제거 | claude-haiku-4-5 |
| 트랜스크립트 안 만듦 | `--no-session-persistence` | ~/.claude/projects jsonl 1344 → 1344 |
| 캐시 안 씀 | `DISABLE_PROMPT_CACHING=1` | cache_creation 0 / cache_read 0 |
| 부수효과 없음 | `--tools ""` `--strict-mcp-config` `--setting-sources user`(프로젝트 훅 무시) | |
| 토큰 절감 | `--system-prompt` 한 줄, `--effort low`, `MAX_THINKING_TOKENS=0` | 아래 표 |

| 설정 | 입력 | 출력(thinking) | 비용 | 시간 |
|---|---|---|---|---|
| 기본 -p | 14.8k | 5.9k (5.6k) | $0.046 | 57s |
| + 시스템프롬프트 한 줄 + effort low | 8.2k | 4.5k (4.2k) | $0.033 | 44s |
| + MAX_THINKING_TOKENS=0 | 8.2k | 0.3k (0) | $0.012 | 4.7s |

전처리본 0.5k 토큰 기준. 남은 입력 8k는 CLI 고정 부담(전처리본 크기와 무관). 캐시 미사용은 환경변수로
클라이언트가 안 요청하는 것이고, 서버 측 적중까지 막는다는 보장은 없다.

펑션 파일(`functions.example.json`): `{"org", "functions": [{"name","desc"}], "products": [{"name","desc"}]}`.
출력의 functions 키·products 이름은 파일에 있는 것만 남기고(`기타` 허용) 합계 100 보정.

## 전처리 규칙 (condense)

| 블록 | 내용 | 원본 대비 |
|---|---|---|
| META | 툴 호출 수, 파일 확장자·최상위 디렉터리 분포, 대표 경로 30개, 턴 수·시간 범위 | ≈0 |
| USER | 사용자 발화 **전부**. `<system-reminder>`·`[Request interrupted]`·`[Image:]`·10자 미만 제거, 발화당 300자 캡 | 0.02~0.1% |
| ASSISTANT | 에이전트 발화 **전부**. ``` 코드블록만 `[code omitted]`로 치환, 캡 없음 | 0.6~2.4% |
| FINAL | 마지막 300자 이상 에이전트 발화(결론 밀도 최고) | — |

제외: 툴 결과(파일 읽기·명령 출력, 원본 7~22%) · 툴 입력(파일에 쓴 코드, 4~12%) · JSON 껍데기(60~70%).
파일에 쓴 코드는 분류에 불필요 — 어떤 파일을 만졌는지는 META의 경로·확장자로 잡힌다.

**예산**: 기본 60k 토큰. 초과 시 ASSISTANT만 1000자→500자 캡 순으로 축소. META·USER·FINAL은 절대 안 자름.
토큰은 라이브러리 없이 보수 추정(ASCII 4자/토큰, 그 외 1.5자/토큰).

### 왜 앞뒤만 자르지 않나
실측(8세션, 0.4~18MB): 첫/끝 30턴만 남기면 0.1~0.9%까지 줄지만
- 한 세션이 "실험 → 원인 분석 → 논문 페이지 작성"처럼 중간에 업무가 바뀜 → 놓침
- 첫/끝 발화가 "너 모델 뭐야", "그래" 같은 노이즈
- 사용자 말은 "돌려라", "마저해서 값줘" 식이라 실체는 에이전트 설명과 파일 종류에 있음

사용자 발화는 원래 원본의 0.1%뿐이라 전부 넣어도 싸다. 에이전트 발화 전부 넣어도 1~2%.

## 실측 (test_condense.py --real, 2026-09-04)

| 원본 | 비율 | 문자 | 추정 토큰 | 캡 |
|---|---|---|---|---|
| 18.19MB | 0.73% | 132k | 48k | 500 (예산 초과 축소) |
| 6.65MB | 2.04% | 135k | 51k | 없음 |
| 4.36MB | 2.35% | 102k | 43k | 없음 |
| 3.32MB | 0.82% | 27k | 10k | 없음 |
| 1.35MB | 0.91% | 12k | 4k | 없음 |
| 0.43MB | 2.08% | 8k | 3k | 없음 |

## 서머리 등 다른 용도
같은 압축본을 세션 요약·회고 입력으로 써도 입력 토큰은 동일하게 1~2%. 단 코드는 `[code omitted]`라
"무슨 코드를 짰나"는 META.paths(파일명)까지만 나온다. 코드 내용까지 요약하려면 `_strip_code` 끄고
Edit/Write 입력을 별도 블록으로 넣어야 하며 그 경우 원본의 1.3~4.7%.

## 분류 출력
단일 라벨 금지. 펑션별 비중(합 100) + `primary` + 근거 한두 문장. 목록 밖 업무는 `기타`.
`_normalize`가 합계 100 보정·미허용 키 제거·primary 재계산.

## 검증 절차 (다음 단계, 미수행)
1. 30~50 세션 사람 라벨
2. (a) 원본 전체 투입 vs (b) 압축본 투입 → primary 일치율. 90% 미만이면 ASSISTANT 캡 완화
3. 불일치 건은 USER/ASSISTANT/FINAL 중 어디서 빠졌는지 눈으로 확인해 규칙 보정
