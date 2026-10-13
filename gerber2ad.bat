@echo off
REM ============================================================
REM  Gerber -> Altium Designer PCB converter
REM  Double-click: a folder picker opens, no typing needed.
REM  Or drag a Gerber folder / .zip onto this file.
REM  Keep ASCII-only: cmd.exe mis-parses multibyte text.
REM ============================================================
setlocal

set "TOOL=%~dp0"
set "VP=%TOOL%env\Scripts\python.exe"
set "TPL=%TOOL%AD_template.PcbDoc"
set "OUTDIR=%TOOL%out"

title Gerber to Altium PCB
cd /d "%TOOL%"

echo.
echo ============================================================
echo   Gerber  -^>  Altium Designer PCB   reverse-engineering tool
echo ============================================================
echo.

if not exist "%VP%" (
    echo [ERROR] Python environment missing.
    echo         Run setup-env.bat first.
    goto :done
)
if not exist "%TPL%" (
    echo [ERROR] AD template missing: %TPL%
    goto :done
)

set "SRC=%~1"
if "%SRC%"=="" goto :picker
set "SRC=%SRC:"=%"
if not exist "%SRC%" (
    echo [ERROR] Path not found:
    echo         %SRC%
    goto :done
)
goto :run

rem ---- folder picker (no typing needed) ----
:picker
echo Opening folder picker...
echo.
set "PICK="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Select the Gerber folder'; if($d.ShowDialog() -eq 'OK'){Write-Output $d.SelectedPath}"`) do set "PICK=%%I"
if not "%PICK%"=="" (
    set "SRC=%PICK%"
    goto :run
)
echo.
echo No folder selected. You can paste the path instead.
set /p "SRC=Paste path to Gerber folder or .zip, then Enter: "
if "%SRC%"=="" goto :done
set "SRC=%SRC:"=%"

rem ---- run conversion ----
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