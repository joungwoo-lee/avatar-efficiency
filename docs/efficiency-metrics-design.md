# 효율계수 산정 · 집계 송출 · 토큰 가치 산출 설계

[session-matching-design.md](session-matching-design.md)의 SessionStart 스위퍼가 transcript를 잡은 **이후** 단계의 설계.

## 동작 흐름 요약

스위퍼는 먼저 이 PC의 Windows 로그인 ID를 읽어(WSL 안이라도 Windows 값) 해당 아바타 카드를 선별한다.
외부 모듈이 제공하는 아바타·역할·업무 스크립트로 후보 트리를 조립하고, 세션 발췌(첫 프롬프트 + 마지막 대화)와 함께
Haiku에 한 번 물어 **어느 업무의 세션인지 매칭 + 수작업 대비 효율계수 η**를 같이 받는다.
세션 실제 활동시간과 토큰 사용량은 transcript에서 코드로 계산한다. 결과는 아바타/역할/업무 라벨을 붙여
outbox.jsonl에 먼저 기록한 뒤 집계 서버로 비동기 송출(실패 시 다음 스윕 재시도)하고,
서버가 비중 가중합으로 아바타 효율 E와 토큰 가치(V·C·ROI)를 계산한다.

## 1. 입력 — 아바타 선택과 후보 트리

### Windows 로그인 ID 읽기 (WSL 포함)
- 네이티브: `[System.Security.Principal.WindowsIdentity]::GetCurrent().Name` 또는 `$env:USERNAME`
- WSL 안에서도 interop으로 Windows 값을 읽음 (Linux 계정명 아님):
  ```bash
  /mnt/c/Windows/System32/cmd.exe /c "echo %USERNAME%"
  # 또는 powershell.exe -NoProfile -c '$env:USERNAME'
  ```
  전체 경로 호출이면 PATH 공유 꺼져 있어도 동작. 유일 예외: `wsl.conf [interop] enabled=false` — 감지 후 에러 처리

### 외부 모듈이 제공하는 정의 (스위퍼는 소비만)
아바타·역할·업무 각각의 스크립트(설명문)와 비중을 별도 외부 모듈이 제공. 파일/HTTP/MCP 어느 인터페이스든 무방, 계약만 고정:
```json
{ "avatars": [{ "loginId": "skim", "script": "...", "roles": [
    { "id": "rtl-design", "weight": 0.6, "script": "...", "tasks": [
      { "id": "t1", "weight": 0.5, "script": "...(구체적 키워드·도구명·산출물명·수작업 시간 앵커 포함)" } ] } ] }] }
```
- 로그인 ID → `loginId` 일치 아바타 선택
- 매칭 정확도는 업무 스크립트의 구체성이 좌우 — 도구명·산출물명을 적을 것
- 스위퍼 실행 시점마다 fetch(또는 캐시+버전) → 정의 변경 즉시 반영

## 2. 매칭 + 효율계수 η 산정 (Haiku 1패스)

프롬프트 = 후보 트리(아바타/역할/업무 스크립트) + 세션 발췌(첫 user 프롬프트 + 마지막 N개 메시지 또는 summary 라인).
구조화 출력(JSON 강제) 한 번으로 매칭과 측량을 같이:

```json
{ "taskId": "t2", "confidence": 0.9,
  "manualHoursEst": 10, "quality": 0.95,
  "eta": 4.8, "rationale": "..." }
```

- **"해당 없음" 선택지 필수** — 잡담·무관 세션 억지 매칭 방지. 미매칭이면 η 산정 스킵, 해당 업무는 기준값 1.0 유지

### η = 수작업 예상시간 ÷ 세션 실제시간 (품질 보정)

| 항 | 산출 주체 | 방법 |
|---|---|---|
| 분모: 세션 실제시간 | 코드 (LLM 아님) | transcript 레코드 timestamp로 **활동 시간** 합산. 턴 간격 15분 초과 gap 제외 — 방치 시간 포함하면 η가 부당하게 낮아짐 |
| 분자: 수작업 예상시간 | Haiku 시뮬 | 세션의 실제 산출물·수정 파일·해결 문제 기준 "사람이 수작업으로 몇 시간?" 추정 |
| 품질 보정 | Haiku 동일 패스 | 완료도 판정 quality 0~1 곱. 미완·재작업 필요면 할인, 실패 세션은 η < 1 가능 |

분자의 일관성 장치 (LLM 시간 추정은 절대값 한계 → **상대 지표로 운용**):
- 업무 스크립트에 기준 앵커 명시 (예: "린트 위반 1건 수작업 수정 ≈ 5분") — 업무별 캘리브레이션
- 동일 프롬프트 템플릿·동일 모델 유지 — 세션 간 비교 가능성이 절대값보다 중요

## 3. 집계 서버 송출 — 라벨 부착 · 비동기 · 무손실

### 페이로드
```json
{ "sessionUuid": "44db9999-…", "loginId": "skim",
  "avatarId": "kim-seolgye", "roleId": "rtl-design", "taskId": "t2",
  "eta": 4.8, "quality": 0.95, "manualHoursEst": 10, "sessionHoursActive": 2.0,
  "confidence": 0.9, "tokens": { "input": 120000, "output": 8500, "cacheRead": 90000 },
  "matchedAt": "2026-08-02T21:00:00+09:00", "cwd": "C--Users-joung-…", "schemaVer": 1 }
```

### 논블로킹 보장 — 이중 구조
1. **구조적 안전**: 스위퍼 자체가 detach 백그라운드 → 발송이 느려도 클로드 세션·사용자 작업 블록 원천 불가
2. **스위퍼 내부도 논블로킹**:
   - **outbox.jsonl 단일 파일이 처리 원장 겸 발송 스풀** (`{uuid, offset, result, sent}`) —
     장부 이원화로 인한 유실·이중 처리 자체가 불가능 (중복 방지 상세: [session-matching-design.md](session-matching-design.md) §2-1)
   - Haiku 호출 직전 in-progress 마킹 → 응답 즉시 결과 확정 기록 (크래시 시 재호출 낭비 유계)
   - 발송은 별도 단계: HTTP POST, 짧은 타임아웃(2~3s), 실패해도 매칭 작업 계속
   - 다음 스윕 때 `sent=false` 재시도 — **at-least-once** (재발송은 Haiku 재호출 아님, 토큰 비용 0)

### 서버 규칙
- `sessionUuid` 기준 **idempotent upsert** — 재시도·resume 재매칭 중복 자동 해소
- 가중합 집계(역할 효율 E_r = Σw_t·η_t, 아바타 효율 E = Σw_r·E_r)는 **서버 책임** — 스위퍼는 raw 레코드만, 비중 w는 서버가 외부 모듈에서 조회

## 4. 토큰 가치 산출

### 재료
| 재료 | 출처 |
|---|---|
| η, manualHoursEst, sessionHoursActive, quality | §2 산정 결과 |
| 사람 시간당 단가 rate | **PM Plan 배분액 ÷ 기간** (돈 앵커) |
| 토큰 사용량 | transcript JSONL의 assistant 메시지별 usage(input/output/cache) 합산 — 스위퍼가 코드로 계산, 추가 비용 0 |
| 토큰 단가 | 모델별 API 정가, cache hit 반영 |

### 산출식
```
절감 가치 V  = (manualHoursEst × rate × quality) − (sessionHoursActive × rate_감독)
토큰 비용 C  = Σ(usage × 모델 단가)
ROI          = V ÷ C            (투입 1원당 창출 가치)
토큰당 가치  = V ÷ tokens       (업무·모델별 비교용)
```

### 가능해지는 집계
- **업무별 토큰당 가치** — 어느 업무에 AI를 태우는 게 남는 장사인지 (η=5.1 린트 클린업은 고가치, η≈1 업무는 토큰 낭비)
- **모델별 ROI** — 업무마다 Haiku로 충분한지 상위 모델이 필요한지 데이터로 결정
- **아바타/프로젝트 롤업** — "실효 코스트 = 배분액 ÷ E"를 실측 토큰 비용 포함 총비용으로 정교화

### 정직성 원칙 2개
1. manualHoursEst가 LLM 추정 → V의 절대값보다 **업무 간·기간 간 상대 비교**로 운용 (η와 동일 원칙)
2. 구독제면 토큰 비용은 실지출이 아니라 **API 정가 환산 기회비용** — 환산 기준을 명시하고 일관 유지
