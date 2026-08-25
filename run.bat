@echo off
setlocal

set "BUILD_DIR=%~dp0build\src\Release"
set "EXE=%BUILD_DIR%\HandEyeCalibrationTool.exe"

REM === Deploy Qt5 + OpenCV (one-time) ===
if not exist "%BUILD_DIR%\Qt5Core.dll" (
    echo Copying Qt5 x64 runtime...
    copy /Y "D:\Program Files\Qt\5.14.2\msvc2017_64\bin\Qt5Core.dll" "%BUILD_DIR%\"
    copy /Y "D:\Program Files\Qt\5.14.2\msvc2017_64\bin\Qt5Gui.dll" "%BUILD_DIR%\"
    copy /Y "D:\Program Files\Qt\5.14.2\msvc2017_64\bin\Qt5Widgets.dll" "%BUILD_DIR%\"
)
REM === Qt5 platform plugin ===
if not exist "%BUILD_DIR%\platforms" mkdir "%BUILD_DIR%\platforms"
if not exist "%BUILD_DIR%\platforms\qwindows.dll" (
    echo Copying Qt5 platform plugin...
    copy /Y "D:\Program Files\Qt\5.14.2\msvc2017_64\plugins\platforms\qwindows.dll" "%BUILD_DIR%\platforms\"
)

REM === RVC + HandEyeSDK DLLs are auto-deployed by CMake post-build ===

REM === Verify critical runtime DLLs before launch ===
set "MISSING="
if not exist "%BUILD_DIR%\RVC.dll"                 set "MISSING=%MISSING% RVC.dll"
if not exist "%BUILD_DIR%\HandEyeSDK.dll"          set "MISSING=%MISSING% HandEyeSDK.dll"
if not exist "%BUILD_DIR%\Qt5Core.dll"             set "MISSING=%MISSING% Qt5Core.dll"
if not exist "%BUILD_DIR%\platforms\qwindows.dll"  set "MISSING=%MISSING% platforms\qwindows.dll"
if defined MISSING (
    echo.
    echo [ERROR] Missing runtime DLLs:%MISSING%
    echo Please build first:  cmake --build build --config Release
    echo or copy the DLLs next to HandEyeCalibrationTool.exe.
    pause
    exit /b 1
)

echo.
echo === Starting HandEyeCalibrationTool ===
echo.
cd /d "%~dp0"
"%EXE%"

echo.
echo === Exit code: %ERRORLEVEL% ===
pause
