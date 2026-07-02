@echo off
setlocal EnableExtensions

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  echo Approve the UAC window, then read the elevated window output.
  pause
  exit /b
)

cd /d "%~dp0..\.."
echo Running as administrator.
echo Project: %CD%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\windows\open_tongyu_firewall.ps1" -PauseAtEnd

echo.
echo Finished.
pause
