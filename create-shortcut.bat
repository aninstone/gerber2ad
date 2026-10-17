@echo off
REM ============================================================
REM  Creates the desktop shortcut for gerber2ad.bat
REM  (Run this once. ASCII-only content.)
REM ============================================================
setlocal
set "TOOL=%~dp0"
title Create Gerber2AD desktop shortcut

echo.
echo Creating desktop shortcut...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOL%make-shortcut.ps1"

if errorlevel 1 (
    echo.
    echo [FAILED] Could not create shortcut.
    echo          You can still use the tool by dragging a Gerber
    echo          folder directly onto gerber2ad.bat
) else (
    echo.
    echo [DONE] Drag a Gerber folder or .zip onto the new
    echo        "Gerber2AD-PCB" icon on your desktop.
)

echo.
pause
endlocal