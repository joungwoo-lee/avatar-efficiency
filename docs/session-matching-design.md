# 세션 → 업무 매칭 트리거 설계

아바타 효율성 구조(→ [avatar-overview-map.html](avatar-overview-map.html) · [avatar-structure-map.html](avatar-structure-map.html))에서
"세션 종료 시 Haiku가 세션 내용을 읽어 역할·업무에 매칭하고 효율계수 η를 산정"하는 작업의 실행 설계.
매칭 이후 단계(η 산정·집계 송출·토큰 가치 산출)는 [efficiency-metrics-design.md](efficiency-metrics-design.md).

**채택안: 클로드 세션 시작 시점에 백그라운드 스위퍼를 띄워, 시작 시점 이전의 미처리 transcript를 소급 처리한다.**

## 1. 분석 대상 파일 — transcript

- 위치: `~/.claude/projects/<cwd 인코딩 폴더>/<세션uuid>.jsonl`
- **작업폴더(cwd)별 폴더 분리 저장**. 인코딩 규칙: 절대경로의 `[^a-zA-Z0-9]` 전부 `-` 치환

```
C--Users-joung                                ← C:\Users\joung
C--Users-joung-agent-gateway-discord          ← C:\Users\joung\agent-gateway-discord
C--Users-joung-agent-gateway-discord-web-ui   ← …\agent-gateway-discord\web-ui  (하위 폴더도 별개)
C--Users-joung-skill-eval-platform            ← C:\Users\joung\skill-eval-platform
```

- 세션 1개 = JSONL 1개 (파일명 = 세션 uuid). resume 시 같은 파일에 이어 씀
- 내용: user/assistant 메시지 레코드 + `type:"summary"` 요약 라인
- `%USERPROFILE%\.claude\projects\` 루트가 **PC 로그인 계정당 하나** → 로그인 ID 기준 아바타 선별과 자연스럽게 일치
- Haiku 매칭 입력은 파일 전체가 아니라 **첫 user 프롬프트 + 마지막 N개 메시지(또는 summary 라인)** 만 — 토큰 절약

참고: SessionEnd hook은 정상 종료(exit, `/clear`, logout)에서만 발화한다.
방치·강제 종료·크래시에서 안 걸리므로 종료 이벤트 기반 수집은 채택하지 않았다.
세션 시작을 트리거로 쓰면 "이전에 어떻게 끝났든" 다음 기동 때 반드시 잡힌다.

## 2. 채택 설계 — SessionStart 스위퍼

1. settings.json에 SessionStart hook 등록 (matcher `startup` — resume/clear 제외)
2. hook은 스위퍼 스크립트를 **detach 스폰 후 즉시 리턴**
   (hook이 안 끝나면 세션 기동이 블록됨 → `Start-Process -WindowStyle Hidden` 필수)
3. 스위퍼: `~/.claude/projects/` 전체에서 다음 조건의 transcript만 골라 Haiku 매칭 → 처리 원장(ledger)에 기록

**처리 대상 조건 (세션 시작 시점 기준):**
- `mtime < 이번 세션 시작 시각`
- AND 원장에 없는 uuid, 또는 **원장의 처리 오프셋(책갈피) 이후에 실질 턴(user+assistant 쌍)이 새로 있는 uuid** — resume 재매칭.
  mtime 갱신만으로 재매칭하면 안 됨: resume으로 열었다 턴 없이 닫아도 마커 append로 mtime이 바뀌어
  내용 변화 없는 전체 재분석 = 토큰 낭비. 재매칭도 이전 결과 + 오프셋 이후 새 꼬리만 주는 증분 프롬프트로 절감
- AND mtime이 최근 30분 이내가 아님 (다른 진행 중 세션 제외)
- AND 자기 자신 uuid 아님
- AND **스위퍼 전용 cwd 폴더(`projects\C--Users-joung--sweeper\`)가 아님** (아래 자기 꼬리 재귀 참조)

```json
"hooks": {
  "SessionStart": [{
    "matcher": "startup",
    "hooks": [{ "type": "command",
      "command": "powershell -Command \"Start-Process powershell -WindowStyle Hidden -ArgumentList '-File C:\\Users\\joung\\sweep-transcripts.ps1'\"" }]
  }]
}
```

**필수 가드 (실행 순서 고정: 락 획득 → 스로틀 확인 → 원장 읽기):**
1. **락파일 단일 인스턴스** — 세션 동시 다발 기동 시 스위퍼 중복 방지.
   스로틀을 락 밖에서 읽으면 동시 기동 레이스로 이중 실행 가능 → 반드시 락 안에서 확인
2. **스로틀** — 마지막 스윕 후 N시간 경과 시에만 실행 (원장에 lastSweep 기록)
3. **진행 중 세션 제외** — mtime 최근 30분 이내 스킵 + 자기 자신 uuid 제외
4. **훅 재귀 가드** — `claude -p` 헤드리스도 SessionStart hook을 발화시킴 → 스위퍼가 부른 클로드가
   또 스위퍼를 깨우는 루프 가능. 스위퍼가 자식 호출에 `SWEEPER_CHILD=1` env를 심고,
   hook 스크립트 첫 줄에서 이 값 보이면 즉시 종료 (락·스로틀은 2차 방어)

## 2-1. 중복 처리 방지 — 토큰 낭비 차단 4종

| 구멍 | 증상 | 차단책 |
|---|---|---|
| mtime 트리거 과발화 | 내용 그대로인데 전체 재분석 | 원장에 **처리 오프셋(책갈피)** 저장, 오프셋 이후 실질 턴 있을 때만 재매칭 |
| Haiku 호출 후 원장 기록 전 크래시 | 다음 스윕이 같은 세션 재호출 | 호출 **직전 in-progress 마킹**(시각 포함) → 응답 즉시 확정 기록. 오래된(1h+) in-progress만 재시도 허용 — 낭비가 크래시당 1콜로 유계 |
| 원장·스풀 이원화 불일치 | 유실 또는 이중 처리 | **단일 파일 통합**: outbox.jsonl이 원장 겸 스풀 (`{uuid, offset, result, sent}`) — 진실 원천 하나면 어긋날 상대 없음 |
| 자기 꼬리 재귀 | 스위퍼의 `claude -p` 호출이 만든 transcript를 다음 스윕이 또 분석 → 무한 증식 | 분석 호출은 항상 **전용 cwd**(`C:\Users\joung\.sweeper`)에서 실행 → transcript가 한 폴더에만 쌓임 → 그 폴더를 스캔에서 제외. 주기 청소는 선택 |

**공통 원칙:** 매칭 결과는 **세션 uuid 기준 upsert** (resume으로 이어진 세션은 다음 스윕에서 재매칭·갱신),
처리 이력은 **단일 원장(outbox.jsonl)** 하나로 — 이중 매칭 없음.

장점: 크론·스케줄러 등록 불필요, 클로드를 쓰는 날에만 돎 — 사용자가 클로드를 켜는 행위 자체가 배치 트리거.
한계: 클로드를 안 켜는 날은 처리 지연 (다음 기동 때 소급 처리되므로 누락은 아님).

## 3. 진행 중 세션 무간섭 근거

1. **읽기 전용** — transcript는 읽기만. Claude의 JSONL append는 공유 읽기 허용이라 쓰기 락 충돌 없음
2. **자기 세션 제외** — 새로 켠 세션 transcript는 mtime 최신 + 자기 uuid 명시 제외
3. **다른 진행 중 세션** — mtime 30분 가드로 스킵. 30분 넘게 idle인 열린 세션은 읽혀도 무해, 이어가면 다음 스윕에서 upsert 갱신
4. **기동 지연 없음** — detach 스폰 후 hook 즉시 리턴
5. **원장/락은 스위퍼 전용 경로** — 클로드가 보는 파일 아님

### ⚠ 유일한 실전 함정 — `CLAUDE_CODE_*` env 누수
SessionStart hook의 자식 프로세스는 부모 클로드 세션의 환경변수를 물려받는다.
스위퍼가 Haiku 매칭을 `claude -p`로 돌리면 nested 마커가 새서 자식 클로드가 중첩 세션으로
오판·이상동작할 수 있음 (launcher-restarter에서 동일 문제로 6개 변수 스크럽한 실측 전례).

**해결법 — 100% 해소 가능. 채택: `claude -p` 유지 + 상속 고리 절단.**

Haiku 매칭은 `claude -p --model haiku`(구독)로 실행한다. API 직접 호출은 기술적으로는
문제를 원천 소멸시키지만(자식 CLI 자체가 없음) **별도 API 키·과금이 필요해 불채택** — 클로드 구독으로 운용.

1. **상속 고리 절단 (채택안, 구조적 완전)** — hook에서 스위퍼를 직접 스폰하지 말고
   `schtasks /Run /TN sweep`으로 Windows 작업 스케줄러 경유: 스위퍼가 스케줄러 서비스의
   자식으로 떠서 세션 env를 아예 상속받지 않음. 또는 .NET `ProcessStartInfo`로
   EnvironmentVariables를 비우고 재구성해 클린 env 스폰.
   클린 env로 뜬 스위퍼가 자식 `claude -p` 호출에 `SWEEPER_CHILD=1`만 직접 세팅(훅 재귀 가드용).
2. **열거식 스크럽 (비권장, 100% 아님)** — 알려진 변수 이름을 지우는 방식은 취약.
   실측 전례: 처음 4개 스크럽 → 누락 발견돼 6개 추가. CLI 버전업마다 마커가 늘 수 있어
   목록 유지보수 싸움이 됨. `CLAUDE*` 와일드카드 일괄 제거도 미래의 다른 prefix 마커에는 뚫림.

`claude -p` 운용 유의: 구독 쿼터를 소모하므로 `--model haiku` 명시 — 매칭당 입력 수천 토큰 수준이라 부담 미미.
