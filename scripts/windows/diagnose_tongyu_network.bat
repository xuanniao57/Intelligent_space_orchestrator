@echo off
setlocal

cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\windows\diagnose_tongyu_network.ps1"
