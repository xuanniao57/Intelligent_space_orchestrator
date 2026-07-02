@echo off
setlocal
cd /d "%~dp0\..\.."
echo Opening G1 RGB/Depth visual monitor in the browser.
start "" "http://127.0.0.1:8798/vision-monitor"
python -m tongyu_hardware.cli vision-probe --stream-timeout 3
echo.
pause
