@echo off
setlocal
cd /d "%~dp0"

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

start "" cmd /c "timeout /t 2 >nul & start "" http://localhost:8000"
"%PY%" main.py

pause
