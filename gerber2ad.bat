@echo off
REM ============================================================
REM  Gerber -> Altium Designer PCB  (one-click converter)
REM  USAGE: drag a Gerber FOLDER or .zip onto this .bat file
REM  NOTE: keep this file ASCII-only (no Chinese) - cmd.exe
REM        mis-parses multibyte text in parentheses blocks.
REM ============================================================
setlocal enabledelayedexpansion

set "TOOL=%~dp0"
set "VP=%TOOL%env\Scripts\python.exe"
set "TPL=%TOOL%AD_template.PcbDoc"
set "OUTDIR=%TOOL%out"

title Gerber to Altium PCB

echo.
echo ============================================================
echo   Gerber  -^>  Altium Designer PCB   reverse-engineering tool
echo ============================================================
echo.

if not exist "%VP%" (
    echo [ERROR] Python env not found: %VP%
    echo         Run "setup-env.bat" first.
    echo.
    pause
    exit /b 1
)
if not exist "%TPL%" (
    echo [ERROR] AD template not found: %TPL%
    echo.
    pause
    exit /b 1
)

set "SRC=%~1"
if "%SRC%"=="" (
    set /p "SRC=Paste path to Gerber folder or .zip, then Enter: "
)
if "%SRC%"=="" (
    echo [ERROR] no input path
    pause
    exit /b 1
)
set "SRC=%SRC:"=%"
if not exist "%SRC%" (
    echo [ERROR] path not found: %SRC%
    pause
    exit /b 1
)

for %%I in ("%SRC%") do set "BASE=%%~nI"
if "%BASE%"=="" set "BASE=PCB"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo Input : %SRC%
echo Output: %OUTDIR%\%BASE%.PcbDoc
echo.
echo Converting, please wait...
echo.

"%VP%" -X dev -m g2adb.main "%SRC%" -o "%OUTDIR%\%BASE%.PcbDoc" --template "%TPL%"

if errorlevel 1 (
    echo.
    echo ============================================================
    echo   [FAILED] see error above
    echo ============================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   [DONE] %OUTDIR%\%BASE%.PcbDoc
echo.
echo   Open it in Altium Designer. Net names are inferred
echo   (Net1/Net2...), rename them against your schematic.
echo ============================================================
echo.

explorer "%OUTDIR%"
pause
endlocal