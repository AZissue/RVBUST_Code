# Portable (green) packaging script.
# Produces dist/HandEyeCalibrationTool_<version>/ with everything needed to run
# on a PC that has NO VC++ runtime, RVC or HandEyeSDK installed:
#   - app exe + all runtime DLLs (Qt5, RVC + vendor SDKs, HandEyeSDK, OSG)
#   - platforms/qwindows.dll, osgPlugins-3.6.5/
#   - VC++ runtime DLLs are deployed next to the exe by the CMake post-build
#   - start.bat + 使用说明.txt for the target PC
param(
    [string]$SourceDir = "D:\MyCode\MyHandEyeTools\build\src\Release",
    [string]$OutRoot   = "D:\MyCode\MyHandEyeTools\dist",
    [string]$Version   = "1.0"
)

$ErrorActionPreference = "Stop"
$pkgName = "HandEyeCalibrationTool_v$Version"
$pkgDir  = Join-Path $OutRoot $pkgName

if (-not (Test-Path (Join-Path $SourceDir "HandEyeCalibrationTool.exe"))) {
    Write-Error "App exe not found in $SourceDir — build Release first."
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

# 5) README for the target PC
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "packaging\README.txt") `
          -Destination $pkgDir

# 6) Zip
$zip = Join-Path $OutRoot "$pkgName.zip"
if (Test-Path $zip) { Remove-Item -LiteralPath $zip }
Compress-Archive -Path $pkgDir -DestinationPath $zip -CompressionLevel Optimal

$files = (Get-ChildItem $pkgDir -File | Measure-Object).Count
$mb    = [math]::Round((Get-ChildItem $pkgDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "OK: $pkgDir ($files files, $mb MB)"
Write-Host "ZIP: $zip"
