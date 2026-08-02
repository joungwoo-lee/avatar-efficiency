# 설치: 작업 스케줄러 태스크 등록 + settings.json hook 스니펫 안내
$repo = Split-Path -Parent $PSScriptRoot
$node = (Get-Command node).Source

# on-demand 전용 태스크 (/SC ONCE 과거 시각 → 자동 실행 없음, schtasks /Run으로만 발화)
schtasks /Create /F /TN "avatar-efficiency-sweep" /SC ONCE /ST 00:00 /TR "`"$node`" `"$repo\sweeper\sweep.js`"" | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Output "scheduled task 'avatar-efficiency-sweep' registered." }
else { Write-Output "schtasks 등록 실패 — hook 폴백(직접 스폰)으로도 동작함." }

Write-Output ""
Write-Output "다음 스니펫을 %USERPROFILE%\.claude\settings.json 의 hooks 에 추가:"
Write-Output @"
"hooks": {
  "SessionStart": [{
    "matcher": "startup",
    "hooks": [{ "type": "command",
      "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"$($repo -replace '\\','\\\\')\\hook\\sessionstart-hook.ps1\"" }]
  }]
}
"@
