@echo off
setlocal

cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process PowerShell -Verb RunAs -ArgumentList '-NoExit -NoProfile -ExecutionPolicy Bypass -File ""%CD%\scripts\windows\open_tongyu_firewall.ps1"" -PauseAtEnd'"

echo If a UAC window appears, approve it to enable ping and TCP access for the Tongyu central host.
pause
