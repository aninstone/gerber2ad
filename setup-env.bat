@echo off
REM ============================================================
REM  One-time environment setup (Python venv + gerbonara)
REM  Keep ASCII-only - cmd.exe mis-parses multibyte text.
REM ============================================================
setlocal
set "TOOL=%~dp0"
title Setup Gerber2AD environment

echo.
echo ============================================================
echo   Setting up environment...
echo ============================================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
    echo [ERROR] Python not found.
    echo         Install Python 3.9+ from https://www.python.org/downloads/
    echo         IMPORTANT: tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

echo Using: %PY%
%PY% --version
echo.

if exist "%TOOL%env\Scripts\python.exe" (
    echo [SKIP] venv already exists
) else (
    echo [1/2] Creating virtual environment...
    %PY% -m venv "%TOOL%env"
    if errorlevel 1 (
        echo [ERROR] failed to create venv
        pause
        exit /b 1
    )
)

set "VP=%TOOL%env\Scripts\python.exe"

echo [2/2] Installing gerbonara...
"%VP%" -m pip install --upgrade pip --quiet
"%VP%" -m pip install gerbonara --quiet
if errorlevel 1 (
    echo [ERROR] failed to install gerbonara - check your network
    pause
    exit /b 1
)

echo.
echo Verifying...
"%VP%" -c "from gerbonara import GerberFile; print('gerbonara ready')"
if errorlevel 1 (
    echo [ERROR] verification failed
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   [DONE] Now drag a Gerber folder onto gerber2ad.bat
echo ============================================================
echo.
pause
endlocal