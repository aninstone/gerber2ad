@echo off
REM ============================================================
REM  Gerber -> Altium Designer PCB converter
REM
REM  HOW TO USE
REM    Drag a Gerber FOLDER or a .zip file onto this .bat
REM    (or onto its shortcut). Then it just works.
REM
REM  NOTE: keep this file ASCII-only (no Chinese) - cmd.exe
REM        mis-parses multibyte text in parenthesis blocks.
REM ============================================================
setlocal

set "TOOL=%~dp0"
set "VP=%TOOL%env\Scripts\python.exe"
set "TPL=%TOOL%AD_template.PcbDoc"
set "OUTDIR=%TOOL%out"

title Gerber to Altium PCB
cd /d "%TOOL%"

REM ================= no argument: just show how to drag =========
if "%~1"=="" goto :howto

REM ================= environment check =========================
if not exist "%VP%" (
    echo.
    echo [ERROR] Python environment is missing.
    echo         Run setup-env.bat first, then try again.
    goto :done
)
if not exist "%TPL%" (
    echo.
    echo [ERROR] AD template is missing: %TPL%
    goto :done
)

set "SRC=%~1"
set "SRC=%SRC:"=%"
if not exist "%SRC%" (
    echo.
    echo [ERROR] Path not found:
    echo         %SRC%
    goto :done
)
goto :run

REM ================= how-to screen ============================
:howto
echo.
echo ============================================================
echo   Gerber  -^>  Altium Designer PCB   reverse-engineering tool
echo ============================================================
echo.
echo   HOW TO USE
echo.
echo     1. Open the folder that holds your Gerber files
echo        (the one containing .GTL / .GBL / .G1 ... files)
echo.
echo     2. Drag that FOLDER onto this window
echo        ^(or onto the "gerber2ad" shortcut on your desktop^)
echo.
echo     3. Wait a few seconds - the .PcbDoc appears in the
echo        "out" folder next to this file.
echo.
echo   Also works with a .zip that contains Gerber files.
echo.
echo   Alternative: type or paste the path below and press Enter.
echo.
set /p "SRC=Paste path (Enter = quit): "

if "%SRC%"=="" goto :done
set "SRC=%SRC:"=%"
if not exist "%SRC%" (
    echo.
    echo [ERROR] Path not found:
    echo         %SRC%
    goto :done
)

REM ================= run conversion ===========================
:run
for %%I in ("%SRC%") do set "BASE=%%~nI"
if "%BASE%"=="" set "BASE=PCB"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo.
echo Input : %SRC%
echo Output: %OUTDIR%\%BASE%.PcbDoc
echo.
echo Converting, please wait...
echo.

"%VP%" -X dev -m g2adb.main "%SRC%" -o "%OUTDIR%\%BASE%.PcbDoc" --template "%TPL%"

if errorlevel 1 (
    echo.
    echo ============================================================
    echo   [FAILED] Conversion failed. Error shown above.
    echo ============================================================
    goto :done
)

echo.
echo ============================================================
echo   [DONE] %OUTDIR%\%BASE%.PcbDoc
echo.
echo   Open it in Altium Designer.
echo   Net names are inferred (Net1/Net2...), rename them
echo   against your schematic.
echo ============================================================
echo.

:done
echo.
echo Press any key to close this window...
pause >nul
endlocal