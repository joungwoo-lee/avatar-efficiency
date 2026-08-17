@echo off
rem 전 세션 효율 리포트 (윈도우) — 더블클릭으로 실행.
rem 이 PC 홈(%USERPROFILE%\.claude\projects)의 세션 전체를 LLM 0회로 측정해
rem %USERPROFILE%\session-efficiency-report.md 로 저장한다.
chcp 65001 >nul
cd /d "%~dp0"
set "OUT=%USERPROFILE%\session-efficiency-report.md"
where python >nul 2>nul
if %errorlevel%==0 (
  python record_actions_code_api_all_sessions.py --out "%OUT%"
) else (
  py -3 record_actions_code_api_all_sessions.py --out "%OUT%"
)
echo.
echo 리포트 저장: %OUT%
pause
