@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [PFIS] No .venv found. Creating one with the available Python launcher...
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 -m venv "%ROOT%.venv"
    ) else (
        python -m venv "%ROOT%.venv"
    )
)

if not exist "%PYTHON_EXE%" (
    echo [PFIS] Failed to create .venv. Install Python 3.13+ and try again.
    exit /b 1
)

"%PYTHON_EXE%" "%ROOT%scripts\start.py" %*
exit /b %ERRORLEVEL%
