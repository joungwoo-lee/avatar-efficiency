# Provider Interface Spec — 아바타·역할·업무 정의 공급 계약 (v1)

외부 모듈(조직의 기획/인사/PM 시스템 = **provider**)이 아바타·역할·업무 디스크립션을 공급하고,
스위퍼(= **consumer**)가 그것으로 세션을 매칭하기 위한 인터페이스 정의.
이 문서만 읽고 provider를 구현하면 연동이 완결되도록 작성됨. 형식 검증용 스키마: [avatars.schema.json](avatars.schema.json)

## 0. 역할 분담

| 주체 | 책임 |
|---|---|
| provider (외부 모듈) | 아바타 정의 데이터의 생성·갱신·정합성. 비중 w, 업무 script, 코스트 배분 |
| consumer (스위퍼) | 데이터 소비만. 로그인 ID로 아바타 선택 → 후보 트리 조립 → 매칭·η 산정 |
| 집계 서버 | 결과 수신(멱등 upsert)·가중합 집계. 비중 w는 provider 데이터에서 조회 |

## 1. 데이터 모델

최상위 문서 하나. JSON, UTF-8.

```json
{
  "schemaVer": 1,
  "avatars": [
    {
      "avatarId": "kim-seolgye",
      "loginId": "skim",
      "script": "자동차용 반도체 팹리스 ADAS SoC팀. 디지털 설계·검증 담당. …",
      "costAllocation": { "amount": 300000000, "currency": "KRW", "share": 0.25, "plannedHours": 3000 },
      "roles": [
        {
          "id": "rtl-design",
          "name": "RTL 설계 엔지니어",
          "weight": 0.6,
          "script": "ADAS SoC 디지털 블록 설계. Verilog RTL, 린트·CDC, 합성·타이밍.",
          "tasks": [
            {
              "id": "t1",
              "name": "CAN-FD IP RTL 설계",
              "weight": 0.5,
              "script": "CAN-FD 프로토콜 엔진, AXI4-Lite 인터페이스, 클록 게이팅. 산출물: Verilog RTL. 앵커: 모듈 1개 초안 수작업 ≈ 8h, 인터페이스 연결 ≈ 2h."
            }
          ]
        }
      ]
    }
  ]
}
```

### 필드 의미와 제약

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `schemaVer` | int | ✔ | 현재 `1`. consumer는 모르는 상위 버전이면 처리 거부 |
| `avatars[]` | array | ✔ | 1개 이상 |
| `avatarId` | string | ✔ | 전역 유일. **한 번 발급하면 변경 금지** — 집계 연속성의 키 |
| `loginId` | string | ✔ | OS(Windows) 로그인 계정명. **문서 내 유일** (아바타 선택 키, §2) |
| `script` (아바타) | string | ✔ | 이 사람의 업무 범위 한 문단. 저지 프롬프트의 최상위 컨텍스트 |
| `costAllocation` | object | – | PM Plan 배분. `amount`(배분액)·`currency`·`share`(프로젝트 내 비중)·`plannedHours`(기간 환산 시간 — 시간당 단가 ρ = amount ÷ plannedHours 도출용) |
| `roles[].id`, `tasks[].id` | string | ✔ | 아바타 내 유일, `[a-z0-9-]+`, **변경 금지** (η 이력이 이 id로 귀속됨). **`misc`는 예약어** — provider 사용 금지 (미매칭 세션의 기타 업무 라벨) |
| `roles[].weight` | number | ✔ | 아바타 내 역할 비중. **합 = 1.0 (±0.001)** |
| `tasks[].weight` | number | ✔ | 역할 내 업무 비중. **역할별 합 = 1.0 (±0.001)** |
| `roles[].script` | string | ✔ | 역할 설명 1~2문장 |
| `tasks[].script` | string | ✔ | **매칭 정확도와 η 품질의 전부.** 작성 규칙 §3 |
| `tasks[].name`, `roles[].name` | string | ✔ | 사람용 표시명 (매칭에도 프롬프트로 전달됨) |

알 수 없는 추가 필드는 consumer가 **무시**한다(전방 호환). 예약 필드: `loginAliases[]`(복수 계정 매핑, v2 예정), `disabled`(업무 비활성).

## 2. 아이디 → 아바타 선택 규칙

1. consumer는 실행 PC의 **Windows 로그인 계정명**을 읽는다
   - 네이티브: `%USERNAME%` (또는 `WindowsIdentity.GetCurrent()`)
   - WSL 내부: interop으로 Windows 값을 읽음 (`/mnt/c/Windows/System32/cmd.exe /c "echo %USERNAME%"`) — Linux 계정명 아님
2. `avatars[]`에서 `loginId`가 **대소문자 무시 정확 일치**하는 아바타 1개를 선택
3. 일치 0개 → 그 PC에서는 아무것도 처리하지 않음 (정상 종료, 에러 아님)
4. 일치 2개 이상 → 문서 결함. consumer는 처리 거부하고 로그 남김. **provider는 loginId 유일성을 보장할 것**
5. 도메인 계정(`DOMAIN\user`) 환경이면 provider는 `user` 부분만 기재

## 3. 업무 script 작성 규칙 (provider 필수 준수)

저지는 이 텍스트만 보고 매칭·수작업 시간 추정을 한다. 반드시 포함:

1. **구체적 키워드**: 도구명(Spyglass, UVM…), 산출물명(Verilog RTL, FMEDA…), 파일/시스템 이름 — 세션 대화에 등장할 어휘와 겹치게
2. **수작업 앵커 1개 이상**: `앵커: <작업 단위> 수작업 ≈ <시간>` 형태. 예: "린트 위반 1건 수작업 ≈ 5분". η 분자(수작업 예상시간) 추정의 캘리브레이션 기준 — 앵커 없는 업무는 η 신뢰도가 떨어짐
3. 다른 업무와 **구별되는 서술**: 두 업무 script가 비슷하면 매칭이 흔들림. 겹치는 일은 업무를 합치거나 경계를 명시
4. 길이: 업무당 1~3문장. 트리 전체가 저지 프롬프트에 들어가므로 장문 금지

## 4. 전달 방식

### A. 파일 (현행 구현)
- 경로: `~/.sweeper/avatars.json` (consumer 설정 `avatarsPath`로 변경 가능, env `AE_AVATARS_PATH` 우선)
- consumer는 **스윕 실행 시마다 다시 읽음** — 핫 리로드, 재시작 불필요
- provider 갱신 규칙: **원자적 교체** (임시 파일에 쓰고 rename). 부분 쓰기 상태가 읽히면 그 스윕은 스킵됨
- 배포 채널은 provider 자유 (동기화 에이전트, 로그인 스크립트, 사내 배포 등)

### B. HTTP (예약 — v2, 미구현)
- `GET {providerUrl}/avatars` → §1 문서 그대로. `ETag`/`If-None-Match` 캐시 지원 권장
- consumer 설정 `avatarsUrl` 지정 시 파일보다 우선. 네트워크 실패 시 마지막 성공 캐시 사용

### C. MCP (예약)
- `avatars_get` 툴 하나로 §1 문서 반환. 계약 동일

## 5. consumer 측 검증 (처리 거부 조건)

consumer는 읽기 시점에 다음을 검사하고, 실패 시 **해당 스윕 전체를 중단**(부분 처리로 오염시키지 않음):
- JSON 파싱 실패 / `schemaVer` 미지원
- `loginId` 중복, `avatarId`·`id` 중복
- weight 합 오차 > 0.001 (역할 합, 역할별 업무 합)

> 참조 구현 현황: 파싱 실패·avatar 미발견은 처리됨. weight/중복 검증은 스펙 선행 — 구현 예정.

## 6. 결과 수신 인터페이스 (집계 서버 = 또 다른 consumer)

provider가 정의한 id들이 결과 레코드의 라벨로 되돌아온다. 서버 연동 시 참고:

**`POST {serverUrl}/records`** — 스위퍼 → 서버. body:
```json
{
  "sessionUuid": "44db9999-…",          ← 멱등 upsert 키 (재전송·재매칭 중복 해소)
  "loginId": "skim",
  "avatarId": "kim-seolgye",
  "roleId": "rtl-design",                ← misc(기타 업무)면 null
  "taskId": "t1",                        ← 미매칭 세션은 "misc" — 버려지지 않고 항상 송신됨
  "workSummary": "세션이 실제 수행한 일 1~2문장 (misc의 신규 업무 설명 겸용)",
  "confidence": 0.9,
  "manualHoursEst": 10,
  "quality": 0.95,
  "sessionHoursActive": 2.0,
  "eta": 4.75,
  "tokens": { "input": 120000, "output": 8500, "cacheRead": 90000, "cacheCreation": 0 },
  "cwd": "C--Users-joung-…",
  "matchedAt": "2026-08-02T21:00:00+09:00",
  "rationale": "한 문장 근거",
  "schemaVer": 1
}
```
응답: `200 {"ok":true}` / `400 {"error":…}`. 서버는 `sessionUuid` 기준 last-write-wins upsert.

**`GET {serverUrl}/efficiency?avatarId=…`** — 집계 조회. 역할·업무별 η̄, E_r, E, 가치(V/C/ROI/토큰당 가치) 반환.
가중합에 쓰는 w는 서버가 provider 문서에서 읽는다 — **provider 문서와 서버가 보는 문서는 동일 버전이어야 함**.

## 7. 버전·변경 정책

- `schemaVer`는 **호환 깨질 때만** 증가. 필드 추가는 같은 버전에서 허용(무시 규칙)
- `avatarId`·`roleId`·`taskId`는 **불변**. 개명은 `name`만 변경. 업무 폐지는 삭제 대신 `disabled: true`(예약) — 과거 η 이력의 귀속처를 보존
- weight 변경은 자유 (집계 시점의 문서 기준으로 계산됨). 큰 개편 시 서버 집계의 기간 구분은 서버 정책
