# Portable (green) packaging script.
# Produces dist/HandEyeCalibrationTool_<version>/ with everything needed to run
# on a PC that has NO VC++ runtime, RVC or HandEyeSDK installed:
#   - app exe + all runtime DLLs (Qt5, RVC + vendor SDKs, HandEyeSDK, OSG)
#   - platforms/qwindows.dll, osgPlugins-3.6.5/
#   - VC++ runtime DLLs are deployed next to the exe by the CMake post-build
#   - start.bat + usage/install notes (Chinese file name) for the target PC
#
# NOTE: this file is intentionally pure ASCII. Windows PowerShell 5.1 parses a
# BOM-less UTF-8 .ps1 as ANSI, so Chinese text lives in packaging\README.txt
# (UTF-8) and non-ASCII file names are built from code points below.
param(
    [string]$SourceDir = "D:\MyCode\MyHandEyeTools\build\src\Release",
    [string]$OutRoot   = "D:\MyCode\MyHandEyeTools\dist",
    [string]$Version   = "1.0",
    # Package (and zip) base name. Empty -> HandEyeCalibrationTool_v<Version>.
    # Use e.g. -Name HandEyeCalibrationTool_test2.0 for a pre-release test drop.
    [string]$Name      = ""
)

$ErrorActionPreference = "Stop"
$pkgName = if ([string]::IsNullOrWhiteSpace($Name)) { "HandEyeCalibrationTool_v$Version" } else { $Name }
$pkgDir  = Join-Path $OutRoot $pkgName

# Usage note file name: code points U+4F7F U+7528 U+8BF4 U+660E + ".txt".
$readmeName = -join ([char]0x4F7F, [char]0x7528, [char]0x8BF4, [char]0x660E, '.txt')

if (-not (Test-Path (Join-Path $SourceDir "HandEyeCalibrationTool.exe"))) {
    Write-Error "App exe not found in $SourceDir - build Release first."
}

# 1) Fresh package directory
if (Test-Path $pkgDir) { Remove-Item -LiteralPath $pkgDir -Recurse }
New-Item -ItemType Directory -Path $pkgDir | Out-Null

# 2) exe + DLLs (drop Debug Qt and test artifacts)
Get-ChildItem $SourceDir -File | Where-Object {
    $_.Extension -in ".exe", ".dll" -and
    $_.Name -notin @("unit_tests.exe") -and
    $_.Name -notmatch "^Qt5\w*d\.dll$" -and   # Qt5Cored/Guid/Widgetsd
    $_.Name -ne "Qt5Test.dll"
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $pkgDir
}

# 3) Qt platform plugin + OSG plugins (must sit next to the exe)
Copy-Item -LiteralPath (Join-Path $SourceDir "platforms") -Destination $pkgDir -Recurse
Copy-Item -LiteralPath (Join-Path $SourceDir "osgPlugins-3.6.5") -Destination $pkgDir -Recurse

$bat = @"
@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0HandEyeCalibrationTool.exe" (
    echo [ERROR] Missing HandEyeCalibrationTool.exe
    pause
    exit /b 1
)
echo Starting HandEye Calibration Tool ...
start "" "%~dp0HandEyeCalibrationTool.exe"
"@
Set-Content -Path (Join-Path $pkgDir "start.bat") -Value $bat -Encoding ASCII

# 5) README for the target PC (template filled with version + packaging date)
$readmeTpl = Join-Path $PSScriptRoot "packaging\README.txt"
$readmeTxt = (Get-Content -LiteralPath $readmeTpl -Raw -Encoding UTF8).
                 Replace("@VERSION@", $pkgName).
                 Replace("@DATE@", (Get-Date -Format "yyyy-MM-dd"))
Set-Content -LiteralPath (Join-Path $pkgDir $readmeName) -Value $readmeTxt -Encoding UTF8

# 6) Zip
$zip = Join-Path $OutRoot "$pkgName.zip"
if (Test-Path $zip) { Remove-Item -LiteralPath $zip }
Compress-Archive -Path $pkgDir -DestinationPath $zip -CompressionLevel Optimal

$files = (Get-ChildItem $pkgDir -File | Measure-Object).Count
$mb    = [math]::Round((Get-ChildItem $pkgDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "OK: $pkgDir ($files files, $mb MB)"
Write-Host "ZIP: $zip"
