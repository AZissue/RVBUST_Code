@echo off
setlocal enabledelayedexpansion

REM Switch to script directory (project root)
cd /d "%~dp0"

set "BUILD_DIR=build\src\Release"
set "EXE=%BUILD_DIR%\HandEyeCalibrationTool.exe"
set "CMAKE_CACHE=build\CMakeCache.txt"

:: ============================================================
:: 0. Locate Qt 5.x msvc64 root (auto + manual, REQUIRED for build)
:: ============================================================
:find_qt
set "QT_ROOT="
set "QT_FOUND=0"

if not "%QT_ROOT_DIR%"=="" (
    set "QT_ROOT=%QT_ROOT_DIR%"
    set "QT_FOUND=1"
    echo [INFO] Using Qt from env QT_ROOT_DIR: !QT_ROOT!
    goto :qt_done
)

for /f "delims=" %%i in ('qmake -query QT_INSTALL_PREFIX 2^>nul') do (
    set "QT_ROOT=%%i"
    set "QT_FOUND=1"
    echo [INFO] Found Qt via qmake: !QT_ROOT!
    goto :qt_done
)

set "SEARCH_ROOTS=C:\Qt D:\Program Files\Qt D:\Qt E:\Qt"
for %%r in (!SEARCH_ROOTS!) do (
    if exist "%%r" (
        for /d %%v in ("%%r\5.*\msvc2017_64") do (
            if exist "%%v\bin\Qt5Core.dll" (
                set "QT_ROOT=%%v"
                set "QT_FOUND=1"
                goto :qt_done
            )
        )
        for /d %%v in ("%%r\5.*\msvc*_64") do (
            if exist "%%v\bin\Qt5Core.dll" (
                set "QT_ROOT=%%v"
                set "QT_FOUND=1"
                echo [WARN] Found non-2017 MSVC Qt: %%v
                echo        Your EXE was built with VS2017, this may cause subtle issues.
                echo        Recommend setting QT_ROOT_DIR to an exact 2017 path.
                goto :qt_done
            )
        )
    )
)

:qt_manual
echo [ERROR] Cannot locate Qt 5.x automatically.
echo Please enter the full path to your Qt 5.x msvc64 root folder.
echo (This is required for both building and running.)
echo Example: C:\Qt\5.15.2\msvc2019_64
echo.
:ask_again
set /p "USER_QT=Qt path: "
if "!USER_QT!"=="" (
    echo [ERROR] Qt path is required. Please provide a valid path.
    goto :ask_again
)
set "USER_QT=!USER_QT:"=!"
if exist "!USER_QT!\bin\Qt5Core.dll" if exist "!USER_QT!\lib\cmake\Qt5\Qt5Config.cmake" (
    set "QT_ROOT=!USER_QT!"
    set "QT_FOUND=1"
    echo [INFO] Valid Qt path: !QT_ROOT!
    goto :qt_done
) else (
    echo [ERROR] Invalid Qt path. Missing either bin\Qt5Core.dll or lib\cmake\Qt5\Qt5Config.cmake.
    echo Please check the path and try again.
    goto :ask_again
)

:qt_done
if "!QT_FOUND!"=="0" (
    echo [ERROR] Failed to locate Qt. Cannot proceed.
    pause
    exit /b 1
)

:: ============================================================
:: 1. Auto-build if EXE missing or CMakeCache missing
:: ============================================================
if not exist "%EXE%" (
    echo [INFO] Executable not found. Running CMake configure and build...
    goto :do_build
)
if not exist "%CMAKE_CACHE%" (
    echo [INFO] CMake cache missing. Running CMake configure...
    goto :do_build
)
goto :skip_build

:do_build
echo [INFO] Configuring project with Qt path: !QT_ROOT!
cmake -B build -S . -DCMAKE_PREFIX_PATH="!QT_ROOT!"
if errorlevel 1 (
    echo [ERROR] CMake configuration failed.
    pause
    exit /b 1
)

echo [INFO] Building project (Release)...
cmake --build build --config Release
if errorlevel 1 (
    echo [ERROR] CMake build failed.
    pause
    exit /b 1
)
echo [INFO] Build completed successfully.
:skip_build

:: ============================================================
:: 2. Deploy Qt runtime (only if missing) - reuse QT_ROOT
:: ============================================================
if not exist "%BUILD_DIR%\Qt5Core.dll" (
    echo Copying Qt5 x64 runtime...
    copy /Y "!QT_ROOT!\bin\Qt5Core.dll" "%BUILD_DIR%\"
    copy /Y "!QT_ROOT!\bin\Qt5Gui.dll" "%BUILD_DIR%\"
    copy /Y "!QT_ROOT!\bin\Qt5Widgets.dll" "%BUILD_DIR%\"
)

if not exist "%BUILD_DIR%\platforms" mkdir "%BUILD_DIR%\platforms"
if not exist "%BUILD_DIR%\platforms\qwindows.dll" (
    echo Copying Qt5 platform plugin...
    copy /Y "!QT_ROOT!\plugins\platforms\qwindows.dll" "%BUILD_DIR%\platforms\"
)

:: ============================================================
:: 3. Deploy SDK from third_party (if missing)
:: ============================================================
if not exist "%BUILD_DIR%\RVC.dll" (
    if exist "third_party\RVC\runtime\RVC.dll" (
        echo Copying RVC.dll from third_party...
        copy /Y "third_party\RVC\runtime\RVC.dll" "%BUILD_DIR%\"
    )
)

if not exist "%BUILD_DIR%\HandEyeSDK.dll" (
    if exist "third_party\HandEyeSDK\bin\HandEyeSDK.dll" (
        echo Copying HandEyeSDK.dll from third_party...
        copy /Y "third_party\HandEyeSDK\bin\HandEyeSDK.dll" "%BUILD_DIR%\"
    )
)

:: ============================================================
:: 4. Verify all critical DLLs
:: ============================================================
set "MISSING="
if not exist "%BUILD_DIR%\RVC.dll"                 set "MISSING=%MISSING% RVC.dll"
if not exist "%BUILD_DIR%\HandEyeSDK.dll"          set "MISSING=%MISSING% HandEyeSDK.dll"
if not exist "%BUILD_DIR%\Qt5Core.dll"             set "MISSING=%MISSING% Qt5Core.dll"
if not exist "%BUILD_DIR%\platforms\qwindows.dll"  set "MISSING=%MISSING% platforms\qwindows.dll"

if defined MISSING (
    echo.
    echo [ERROR] Missing runtime DLLs:%MISSING%
    echo Please ensure the following:
    echo   - Qt DLLs are available (set QT_ROOT_DIR or provide path manually)
    echo   - SDK DLLs are in third_party\RVC\runtime and third_party\HandEyeSDK\bin
    echo   - Or run CMake build manually: cmake --build build --config Release
    pause
    exit /b 1
)

:: ============================================================
:: 5. Launch application
:: ============================================================
echo.
echo === Starting HandEyeCalibrationTool ===
echo.
"%EXE%"

echo.
echo === Exit code: %ERRORLEVEL% ===
pause