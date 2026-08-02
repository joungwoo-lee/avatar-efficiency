# avatar-efficiency

아바타 효율성 파이프라인 구현. 설계 문서: [docs/](docs/)
([session-matching-design.md](docs/session-matching-design.md) · [efficiency-metrics-design.md](docs/efficiency-metrics-design.md) · 구조도 [상세](docs/avatar-structure-map.html)/[조망](docs/avatar-overview-map.html))

클로드 세션 종료 후, 다음 클로드 기동 시점(SessionStart)에 백그라운드 스위퍼가:
Windows 로그인 ID로 **아바타 선별** → 미처리 transcript를 골라 **Haiku(`claude -p`, 구독)로 업무 매칭 + 효율계수 η 산정**
→ 라벨 붙여 **집계 서버로 비동기 송출** → 서버가 **아바타 효율 E·토큰 가치(V/C/ROI)** 를 계산한다.

## 구성

```
config.json                 스위퍼 설정 (경로·스로틀·모델). AE_* env로 오버라이드
avatars.sample.json         외부 모듈 계약 샘플 (loginId·역할/업무 script·비중 w·수작업 앵커)
sweeper/sweep.js            메인: 락 → 스로틀 → 스캔 → 매칭+η → outbox → 송출
sweeper/lib/login-id.js     Windows 로그인 ID (WSL interop 포함)
sweeper/lib/transcripts.js  ~/.claude/projects 스캔·발췌·활동시간·토큰 합산
sweeper/lib/ledger.js       outbox.jsonl 단일 파일 = 처리 원장 겸 발송 스풀
sweeper/lib/haiku.js        claude -p --model haiku (전용 cwd·CLAUDE* 스크럽·SWEEPER_CHILD)
sweeper/lib/sender.js       비동기 POST (3s 타임아웃, at-least-once)
hook/sessionstart-hook.ps1  SessionStart hook (재귀 가드 → schtasks 경유 → 폴백 스폰)
hook/install.ps1            schtasks 등록 + settings.json 스니펫 출력
server/server.js            집계 서버: POST /records (uuid 멱등), GET /efficiency, /health
server/value-config.json    가치 단가 (rate, 토큰 정가 환산)
test/smoke.js               전 구간 스모크 (mock Haiku + 실서버, dedup·증분 검증)
```

## 설치 / 실행

```powershell
# 1. 아바타 정의 준비 (외부 모듈 자리 — 지금은 파일 계약)
copy avatars.sample.json avatars.json   # loginId를 이 PC 계정으로 수정
# config.json avatarsPath를 avatars.json으로 변경

# 2. 집계 서버
node server/server.js                    # 127.0.0.1:18220

# 3. 훅 설치
powershell -File hook\install.ps1        # schtasks 등록 + settings.json 스니펫 안내

# 수동 1회 실행 (스로틀 무시)
$env:AE_FORCE="1"; node sweeper\sweep.js

# 집계 조회
curl http://127.0.0.1:18220/efficiency
```

## 테스트

```
node test/smoke.js
```
mock Haiku + 실서버 기동으로 검증: 매칭·η 산정·송출·서버 집계(E, ROI), 재스윕 중복 0건(책갈피),
새 턴 append 후 증분 재매칭.

## 설계 대응표 (중복 처리 방지 4종)

| 설계 | 구현 |
|---|---|
| 오프셋 책갈피 | `ledger` offset + `hasNewTurns()` — mtime 갱신만으론 재매칭 안 함 |
| in-progress 마킹 | Haiku 호출 직전 기록, stale(1h) 후에만 재시도 |
| 단일 원장 | `outbox.jsonl` 하나가 원장 겸 스풀 (`sent` 마킹) |
| 자기 꼬리 재귀 차단 | `claude -p`를 전용 cwd(`~/.sweeper/analysis`)에서 실행, 해당 인코딩 폴더 스캔 제외 |
| 훅 재귀 가드 | 자식에 `SWEEPER_CHILD=1`, hook 첫 줄에서 즉시 종료 |

## 미구현 (설계 대비)

- 외부 모듈: 현재 로컬 JSON 파일 계약만 (HTTP/MCP 인터페이스 추후)
- 증분 재매칭 프롬프트(이전 결과+새 꼬리만) — 현재는 재매칭 시 전체 발췌 재전송
- 서버 영속화는 JSONL fold — 규모 커지면 DB 교체 지점
