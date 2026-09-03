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

```bash
python condense.py session.jsonl              # JSON 출력 (구조체)
python condense.py session.jsonl --text       # LLM 투입 텍스트 그대로
python classify.py session.jsonl "sw개발,sw검증,hw설계"   # 프롬프트만 출력(LLM 미호출)
python test_condense.py                       # 단위 테스트
python test_condense.py --real                # ~/.claude/projects 실파일 감량률
```

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

## 분류 출력
단일 라벨 금지. 펑션별 비중(합 100) + `primary` + 근거 한두 문장. 목록 밖 업무는 `기타`.
`_normalize`가 합계 100 보정·미허용 키 제거·primary 재계산.

## 검증 절차 (다음 단계, 미수행)
1. 30~50 세션 사람 라벨
2. (a) 원본 전체 투입 vs (b) 압축본 투입 → primary 일치율. 90% 미만이면 ASSISTANT 캡 완화
3. 불일치 건은 USER/ASSISTANT/FINAL 중 어디서 빠졌는지 눈으로 확인해 규칙 보정
