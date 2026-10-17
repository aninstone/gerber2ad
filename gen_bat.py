"""生成 gerber2ad.bat（纯 ASCII + CRLF 行尾，杜绝 cmd 解析问题）。

规则（本机实测教训）：
  1. bat 内容只允许 ASCII —— 中文/特殊符号会让 cmd 语法错乱
  2. REM 注释里也不要放引号对、未配对引号、非 ASCII（上一版 ⚠ + 引号注释
     直接把 bat 弄崩，报 'M' is not recognized）
  3. 判断变量用 if not defined VAR（不要 if "%VAR%"==""）——
     粘贴的路径自带引号，%VAR% 展开会把引号配对炸掉（exit 255 闪退）
  4. 所有出口统一 goto :done，末尾单一 pause，保证窗口不闪退
"""
import io

BAT = r"""@echo off
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
"""

# 写为 CRLF + 纯 ASCII
text = BAT.replace("\r\n", "\n").replace("\n", "\r\n")
assert all(ord(c) < 128 for c in text), "non-ASCII found!"

OUT = r"C:\Users\Simon\Desktop\杂项\Gerber转AD-PCB\gerber2ad.bat"
with open(OUT, "wb") as f:
    f.write(text.encode("ascii"))
print("written:", OUT, len(text), "bytes (ASCII/CRLF)")

# 同步一份到项目源目录
SRC = r"D:\workbuddy\2026-10-13-15-00-34\gerber2pcb\gerber2ad.bat"
with open(SRC, "wb") as f:
    f.write(text.encode("ascii"))
print("synced :", SRC)
