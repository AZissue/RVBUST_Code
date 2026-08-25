@echo off
setlocal
cd /d "%~dp0"

set "BUILD_DIR=build"
set "EXE=%BUILD_DIR%\app\Release\pcsearch_app.exe"

if not exist "%EXE%" (
    echo [PointCloudSearch] Release binary not found, building...
    where cmake >nul 2>nul
    if errorlevel 1 (
        echo [PointCloudSearch] cmake not found on PATH.
        exit /b 1
    )
    cmake -S . -B "%BUILD_DIR%" -G "Visual Studio 18 2026" -A x64 -DPCL_ROOT="D:/Program Files/PCL 1.13.0"
    if errorlevel 1 (
        echo [PointCloudSearch] CMake configure failed.
        exit /b 1
    )
    cmake --build "%BUILD_DIR%" --config Release --target pcsearch_app
    if errorlevel 1 (
        echo [PointCloudSearch] Build failed, see errors above.
        exit /b 1
    )
    echo [PointCloudSearch] Build finished.
)

if "%~1"=="" (
    rem Double-click: launch app window and close this console.
    start "" "%EXE%"
    exit /b 0
)

rem With arguments (--smoke / --demo / --autoquit ...): run in foreground.
"%EXE%" %*
exit /b %errorlevel%
