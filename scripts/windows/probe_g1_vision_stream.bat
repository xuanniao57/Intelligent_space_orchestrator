@echo off
setlocal
cd /d "%~dp0\..\.."
echo Probing G1 vision frames through the central hub API.
python -m tongyu_hardware.cli vision-probe --stream-timeout 10
echo.
pause
