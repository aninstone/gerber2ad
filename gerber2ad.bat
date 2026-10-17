@echo off
REM ============================================================
REM  Gerber - Altium Designer PCB converter
REM  Drag a Gerber FOLDER or a .zip onto this file.
REM  Or double-click and paste a path.
REM ============================================================
setlocal

set "TOOL=%~dp0"
set "VP=%TOOL%env\Scripts\python.exe"
set "TPL=%TOOL%AD_template.PcbDoc"
set "OUTDIR=%TOOL%out"

title Gerber to Altium PCB
cd /d "%TOOL%"

if "%~1"=="" goto :howto

if not exist "%VP%" (
    echo.
    echo [ERROR] Python environment is missing.
    echo         Run setup-env.bat first, then try again.
    goto :done
)
if not exist "%TPL%" (
    echo.
    echo [ERROR] AD template is missing:
    echo         %TPL%
    goto :done
)

set "SRC=%~1"
if not defined SRC goto :howto
set "SRC=%SRC:"=%"
if not defined SRC goto :howto
if not exist "%SRC%" (
    echo.
    echo [ERROR] Path not found:
    echo         %SRC%
    goto :done
)
goto :run

:howto
echo.
echo ============================================================
echo   Gerber  -^>  Altium Designer PCB   reverse-engineering tool
echo ============================================================
echo.
echo   HOW TO USE
echo.
echo     Drag a Gerber FOLDER or a .zip onto this window,
echo     then press Enter. The .PcbDoc appears in the "out"
echo     folder next to this file.
echo.
echo   The folder should contain .GTL / .GBL / .G1 files,
echo   or a zip that contains them.
echo.
set /p "SRC=Drag path here, or paste it, then Enter: "

REM Check with `if not defined`, never with if "%SRC%"=="" :
REM a pasted path arrives WITH quotes, and the classic check
REM would expand to if ""D:\..."" == "" which crashes cmd.
if not defined SRC goto :done
set "SRC=%SRC:"=%"
if not defined SRC goto :done
if not exist "%SRC%" (
    echo.
    echo [ERROR] Path not found:
    echo         %SRC%
    goto :done
)

:run
for %%I in ("%SRC%") do set "BASE=%%~nI"
if not defined BASE set "BASE=PCB"
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
echo   Net names are inferred, rename them per schematic.
echo ============================================================
echo.

:done
echo.
echo Press any key to close this window...
pause >nul
endlocal
