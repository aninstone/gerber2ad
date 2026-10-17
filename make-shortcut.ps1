# Creates a desktop shortcut for gerber2ad.bat
# Run via: powershell -ExecutionPolicy Bypass -File make-shortcut.ps1
# Save as UTF-8 with BOM so Chinese paths survive.

$ErrorActionPreference = "Stop"

$toolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$target  = Join-Path $toolDir "gerber2ad.bat"

if (-not (Test-Path $target)) {
    Write-Host "[ERROR] gerber2ad.bat not found at: $target"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$link    = Join-Path $desktop "Gerber2AD-PCB.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath       = $target
$sc.WorkingDirectory = $toolDir
$sc.Description      = "Gerber -> Altium PCB: drag a Gerber folder onto this icon"
$sc.IconLocation     = "%SystemRoot%\System32\shell32.dll,3"
$sc.Save()

Write-Host ""
Write-Host "[OK] Desktop shortcut created:"
Write-Host "     $link"
Write-Host ""
Write-Host "Now drag a Gerber folder (or .zip) onto that icon."
Write-Host ""
