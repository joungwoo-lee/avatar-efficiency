# SessionStart hook — 스위퍼 트리거. detach 후 즉시 리턴 (세션 기동 블록 금지).
# 훅 재귀 가드: 스위퍼가 부른 claude -p 자식도 이 훅을 발화시키므로 마커 보이면 즉시 종료.
if ($env:SWEEPER_CHILD -eq "1") { exit 0 }

# 1순위: 작업 스케줄러 경유 — 스위퍼가 세션 env를 상속받지 않음 (CLAUDE_CODE_* 누수 원천 차단)
schtasks /Run /TN "avatar-efficiency-sweep" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { exit 0 }

# 폴백: 태스크 미설치 시 직접 detach 스폰 (env는 sweep.js 내부에서 CLAUDE* 스크럽)
$repo = Split-Path -Parent $PSScriptRoot
Start-Process -WindowStyle Hidden node -ArgumentList "`"$repo\sweeper\sweep.js`""
exit 0
