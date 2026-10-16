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

# 2) the app exe + all runtime DLLs (drop Debug Qt and test artifacts).
# Ship exactly one .exe: test targets (unit_tests / measure_truth / circle_truth)
# are console apps and must not leak into the delivery. Matching on the app exe
# rather than on a blocklist keeps this correct as new test targets appear.
# Debug-variant vendor DLLs: the CMake deploy step copies the Debug Efort SDK and
# its dependencies too. Verified by a byte scan of every shipped exe/dll that only
# EftSdkd.dll references them - the Release delivery never loads them.
$debugVendorDlls = @(
    "EftSdkd.dll", "log4cpp-d.dll", "rlibcpp-bcc-d.dll", "rlibcpp-tool-d.dll"
)
Get-ChildItem $SourceDir -File | Where-Object {
    $_.Name -eq "HandEyeCalibrationTool.exe" -or
    ($_.Extension -eq ".dll" -and
     $_.Name -notin $debugVendorDlls -and
     $_.Name -notmatch "^Qt5\w*d\.dll$" -and   # Qt5Cored/Guid/Widgetsd
     $_.Name -ne "Qt5Test.dll")
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $pkgDir
}

# 2b) Vendor runtime DATA files (not DLLs) -- the step above only matches the exe
# and *.dll, which is exactly how log4cpp.conf went missing from the test2.4 drop
# the customer received. EftSdk.dll calls
# log4cpp::PropertyConfigurator::configure("log4cpp.conf") before it opens any
# socket, and the overload it uses THROWS when the file is absent; the field then
# sees "connect failed" and goes hunting for a network/port problem while the real
# cause is an incomplete package. log4cpp.conf names NTEventLogAppender.dll, so
# both ship together (the DLL already comes along via step 2).
$vendorDataFiles = @("log4cpp.conf")
foreach ($f in $vendorDataFiles) {
    $src = Join-Path $SourceDir $f
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Error "Vendor runtime file missing from the build output: $src (run the Release build first)"
    }
    Copy-Item -LiteralPath $src -Destination $pkgDir -Force
}

# 3) Qt platform plugin + OSG plugins (must sit next to the exe)
Copy-Item -LiteralPath (Join-Path $SourceDir "platforms") -Destination $pkgDir -Recurse
Copy-Item -LiteralPath (Join-Path $SourceDir "osgPlugins-3.6.5") -Destination $pkgDir -Recurse

# 3a) Refuse to ship an incomplete package. Everything here has bitten us or would
# be a silent field failure: a missing exe/DLL is an obvious crash, but a missing
# log4cpp.conf reads as "the robot won't connect" (see 2b), and a missing
# platforms\qwindows.dll reads as "the tool won't start at all".
$mustShip = @(
    "HandEyeCalibrationTool.exe",
    "log4cpp.conf",             # EftSdk.dll throws without it (2b)
    "EftSdk.dll",
    "log4cpp.dll",
    "NTEventLogAppender.dll",   # referenced by log4cpp.conf
    "rlibcpp-bcc.dll",
    "rlibcpp-tool.dll",
    "HandEyeSDK.dll",
    "Qt5Core.dll",
    "Qt5Widgets.dll",
    "platforms\qwindows.dll"
)
$missing = @($mustShip | Where-Object { -not (Test-Path -LiteralPath (Join-Path $pkgDir $_)) })
if ($missing.Count -gt 0) {
    Write-Error ("Package incomplete -- missing: " + ($missing -join ", ") + " (source: $SourceDir)")
}

# 3b) Field diagnostic scripts (tools\*.ps1). They run on the robot PC and are
# the only way to answer "what does this robot actually send" without a rebuild
# -- the UR realtime/RTDE probe printed the packet that exposed the wrong byte
# offset on 2026-10-10. ASCII folder name on purpose (see the note at the top).
$toolsDir = Join-Path $PSScriptRoot "tools"
if (Test-Path $toolsDir) {
    $probes = Get-ChildItem $toolsDir -Filter *.ps1 -File
    if ($probes.Count -gt 0) {
        $probeDir = Join-Path $pkgDir "tools"
        New-Item -ItemType Directory -Path $probeDir -Force | Out-Null
        $probes | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $probeDir }
    }
}

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
