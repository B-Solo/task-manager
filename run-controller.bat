@echo off
rem Launch the Controller (the operator's Windows laptop) from cmd.exe.
rem Usage:  run-controller.bat            connect to BESOLOMO-M-WDKQ.local
rem         run-controller.bat 192.168.1.42   or a raw IP / other host
setlocal
cd /d "%~dp0"

set "VIEWER=%~1"
if "%VIEWER%"=="" set "VIEWER=BESOLOMO-M-WDKQ.local"

if not exist ".venv\Scripts\activate.bat" (
    echo No virtualenv at .venv. Create it once with:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r controller\requirements.txt
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python controller\src\app.py --host %VIEWER%
