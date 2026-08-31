@echo off
REM diff-effort UI launcher. ASCII only on purpose: cmd.exe mis-seeks batch files
REM that contain multibyte text after "chcp 65001". Korean guidance is printed by ui_server.py.
REM   run-ui.bat                local mode  (server reads files on THIS PC; no browser file dialog needed)
REM   run-ui.bat server         server mode (multi-user, 0.0.0.0, fixed ratios.json in this folder)
REM   run-ui.bat 9000           custom port
REM   run-ui.bat server 9000    server mode + custom port
REM   run-ui.bat open           local mode but bound to 0.0.0.0 (reachable from other PCs).
REM                             WARNING: exposes THIS PC's folders/files to anyone who connects.
REM   any combination:          run-ui.bat open 9000   /   run-ui.bat server open
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set MODE=local
set PORT=8765
set OPEN=
for %%A in (%*) do (
  if /I "%%A"=="server" set MODE=server
  if /I "%%A"=="open" set OPEN=--open
  echo %%A| findstr /R "^[0-9][0-9]*$" >nul && set PORT=%%A
)

REM ---- find python: "py -3" -> python -> python3 (Store alias stub fails the version check)
set PY=
for %%C in ("py -3" "python" "python3") do (
  if not defined PY (
    %%~C -c "import sys;assert sys.version_info>=(3,7)" >nul 2>&1 && set PY=%%~C
  )
)
if not defined PY (
  echo.
  echo [ERROR] Python 3.7+ not found.
  echo   Install: https://www.python.org/downloads/windows/   ^(check "Add python.exe to PATH"^)
  echo   or Microsoft Store: "Python 3.12".  Then run this file again.
  echo.
  pause
  exit /b 1
)

REM ---- if the port is busy, move to the next one
:findport
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [INFO] port %PORT% busy, trying next
  set /a PORT+=1
  goto findport
)

REM ---- external access: add an inbound firewall rule (needs admin; silently skipped otherwise)
if "%MODE%"=="server" set OPEN=--open
if defined OPEN (
  netsh advfirewall firewall show rule name="diff-effort UI %PORT%" >nul 2>&1
  if errorlevel 1 (
    netsh advfirewall firewall add rule name="diff-effort UI %PORT%" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
    if errorlevel 1 (
      echo [INFO] could not add a firewall rule ^(not admin^). If other PCs cannot connect, run this as administrator once:
      echo        netsh advfirewall firewall add rule name="diff-effort UI %PORT%" dir=in action=allow protocol=TCP localport=%PORT%
    ) else (
      echo [INFO] firewall rule added: "diff-effort UI %PORT%" ^(TCP %PORT% inbound^)
    )
  )
)

if "%MODE%"=="server" (
  if not exist "ratios.json" (
    echo [ERROR] server mode needs ratios.json here. Measure a repo first in local mode ^(run-ui.bat, box 1^).
    pause
    exit /b 2
  )
  %PY% ui_server.py --server --config ratios.json --port %PORT%
) else (
  %PY% ui_server.py --port %PORT% %OPEN%
)
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo [exit code %RC%] see the message above. Press any key to close.
  pause
)
endlocal
