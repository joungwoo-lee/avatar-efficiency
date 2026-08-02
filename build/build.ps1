# 빌드 시스템: 단일 바이너리 크로스 빌드 (Windows exe + Linux/WSL)
# 사용: npm run build   (또는 powershell -File build\build.ps1)
# 산출: dist\avatar-efficiency-win-x64.exe, dist\avatar-efficiency-linux-x64  (git 미포함)
param([switch]$SkipSmoke)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$ver = (Get-Content package.json | ConvertFrom-Json).version
Write-Output "build v$ver"

if (Test-Path dist) { Remove-Item -Recurse -Force dist }
New-Item -ItemType Directory dist | Out-Null

# @yao-pkg/pkg: pkg 유지보수 포크 (node22 타깃). 첫 실행 시 타깃별 base 바이너리 다운로드
npx -y @yao-pkg/pkg . -t node22-win-x64 -o dist\avatar-efficiency-win-x64.exe
if ($LASTEXITCODE -ne 0) { Write-Error "win-x64 build failed" }
# 크로스 타깃은 --public 필수: 호스트(win V8)에서 만든 바이트코드를 linux V8이 거부함 → 소스 동봉 방식
npx -y @yao-pkg/pkg . -t node22-linux-x64 --public -o dist\avatar-efficiency-linux-x64
if ($LASTEXITCODE -ne 0) { Write-Error "linux-x64 (WSL) build failed" }

Get-ChildItem dist | ForEach-Object { Write-Output ("  {0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)) }

if (-not $SkipSmoke) {
  # 빌드 산출물 스모크: pkg 스냅샷 경로 함정(6d34592류) 실검증. linux 바이너리는 존재/크기만 확인
  node build\exe-smoke.js dist\avatar-efficiency-win-x64.exe
  if ($LASTEXITCODE -ne 0) { Write-Error "exe smoke failed" }
  $lin = Get-Item dist\avatar-efficiency-linux-x64
  if ($lin.Length -lt 10MB) { Write-Error "linux binary suspiciously small" }
  Write-Output "linux binary ok (smoke는 WSL에서: ./avatar-efficiency-linux-x64 version)"
}

Write-Output "BUILD OK v$ver"
