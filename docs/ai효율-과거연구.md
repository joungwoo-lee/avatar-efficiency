# 생성형 AI 활용 생산성 연구 정리

| 연구 | 최초 공개 / 정식 게재 | 대상·업무 | 연구가 직접 보고한 효율값 | 인간 단독=1.0 환산 |
|---|---|---|---|---:|
| Peng et al. – GitHub Copilot | 2023.02.13 arXiv 공개 | 개발자, JavaScript 코딩 과제 | Copilot 사용군이 과제를 55.8% 더 빠르게 완료 | 시간당 처리량 관점 약 2.26배 |
| Noy & Zhang – ChatGPT 글쓰기 | 2023.03.02 MIT Working Paper / 2023.07.13 Science 온라인 게재 | 전문직 종사자, 보고서·메일 등 작성 | 초판: 작업시간 37% 감소. Science 최종본: 40% 감소, 품질 18% 향상 | 시간 기준 약 1.59~1.67배 |
| Brynjolfsson, Li & Raymond – Generative AI at Work | 2023.04 NBER Working Paper | 고객상담원 5,179명 | 시간당 해결 건수 14% 증가. 초보·저숙련 직원은 34% 증가 | 전체 1.14배, 초보·저숙련 1.34배 |
| Dell’Acqua et al. – BCG/HBS | 2023.09 Working Paper 공개 / HBS 발표 2023.09.21 / 정식 논문 2026.03~04 | BCG 컨설턴트 758명 | AI 적합 과제에서 12.2% 더 많은 과제 완료, 25.1% 더 빠름, 평가 성과 40% 이상 향상 | 시간 기준 약 1.34배 |
| Cui et al. – Microsoft·Accenture 등 | 2024.09.05 SSRN 초판 / 이후 2025년 개정 | 개발자 4,867명, 실제 기업 업무 | AI 코딩 도구 사용 시 완료 업무 26.08% 증가 | 1.26배 |

## 1. Peng et al. — GitHub Copilot

- 최초 공개: 2023년 2월 13일
- 대상: 개발자, JavaScript 코딩 과제
- 결과: Copilot 사용군이 과제를 55.8% 더 빠르게 완료
- 환산: 동일 업무 처리시간 기준 시간당 처리량 약 2.26배
- 주의: 논문이 직접 “2.26배”라고 표현한 것은 아니며, 55.8% 시간 단축을 처리량 기준으로 환산한 값

출처: https://arxiv.org/abs/2302.06590

## 2. Noy & Zhang — ChatGPT 전문직 글쓰기

- MIT Working Paper 공개: 2023년 3월 2일
- Science 온라인 게재: 2023년 7월 13일
- 대상: 전문직 종사자, 보고서·메일 등 작성
- 초판 결과: 작업시간 37% 감소
- Science 최종본: 평균 작업시간 40% 감소, 결과물 품질 18% 상승
- 환산: 시간 기준 약 1.59~1.67배 처리능력

출처:
- https://economics.mit.edu/sites/default/files/inline-files/Noy_Zhang_1.pdf
- https://doi.org/10.1126/science.adh2586

## 3. Brynjolfsson, Li & Raymond — Generative AI at Work

- 최초 공개: 2023년 4월, NBER Working Paper
- 대상: 고객지원 상담원 5,179명
- 결과: 시간당 해결 건수 평균 14% 증가
- 초보·저숙련 직원: 34% 증가
- 환산: 전체 평균 1.14배, 초보·저숙련 집단 1.34배

출처:
- https://www.nber.org/papers/w31161
- https://www.nber.org/system/files/working_papers/w31161/w31161.pdf

## 4. Dell’Acqua et al. — BCG / Harvard

- Working Paper 공개: 2023년 9월
- HBS 연구 소개: 2023년 9월 21일
- 정식 논문: Organization Science, 2026년 3~4월호
- 대상: BCG 컨설턴트 758명
- 결과:
  - 12.2% 더 많은 과제 완료
  - 과제 수행속도 25.1% 향상
  - 인간 평가 기준 성과 40% 이상 향상
- 환산: 25.1% 시간 단축을 동일 시간 내 처리량으로 환산하면 약 1.34배
- 제한: AI 역량 범위를 벗어난 복잡한 과제에서는 AI 사용자가 정답을 낼 확률이 19% 낮았음

출처:
- https://www.hbs.edu/faculty/Pages/item.aspx?num=64700

## 5. Cui et al. — Microsoft·Accenture·Fortune 100

- 초판 공개: 2024년 9월 5일, SSRN
- 이후 2025년 개정
- 대상: Microsoft, Accenture 및 Fortune 100 기업 개발자 총 4,867명
- 결과: AI 코딩 도구 사용 시 완료 업무량 26.08% 증가
- 환산: 약 1.26배 생산성

출처:
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4945566
- https://www.microsoft.com/en-us/research/publication/the-effects-of-generative-ai-on-high-skilled-work-evidence-from-three-field-experiments-with-software-developers/

## 보고서용 요약 문구

2023~2025년 주요 현장·통제실험에서 생성형 AI 활용에 따른 생산성 개선은 평균 14~55.8% 범위로 관찰됐다. 특히 BCG 지식근로자 실험에서 업무 수행속도가 25.1% 개선됐고, 4,867명 개발자를 대상으로 한 기업 현장실험에서는 완료 업무량이 26.08% 증가했다. 이에 따라 일반적인 지식근로 업무의 AI 활용 생산성을 인간 단독 대비 약 1.3배로 가정할 수 있다.

## 1.3배 가정에 가장 직접적인 근거

- BCG/HBS: 약 1.34배
- Microsoft·Accenture 등 개발자 실험: 약 1.26배
- 고객상담 저숙련 집단: 약 1.34배
