@echo off
setlocal

:: PointCloudSearch one-click launcher
:: Usage:
::   start.bat                          -> launch GUI
::   start.bat --smoke <ply>            -> headless smoke test
::   start.bat --demo <ply> --autoquit N-> demo pipeline

cd /d "%~dp0"

set "BUILD_DIR=build"
set "EXE=%BUILD_DIR%\app\Release\pcsearch_app.exe"

:: Local dependency paths
set "PCL_ROOT=D:\Program Files\PCL 1.13.0"
set "QT_DIR="

if exist "D:\Qt\6.8.3\msvc2022_64\bin\qmake.exe" set "QT_DIR=D:\Qt\6.8.3\msvc2022_64"
if exist "D:\Program Files\Qt\6.8.3\msvc2022_64\bin\qmake.exe" set "QT_DIR=D:\Program Files\Qt\6.8.3\msvc2022_64"

if "%QT_DIR%"=="" (
    echo [PointCloudSearch] Qt 6.8.3 msvc2022_64 not found.
    echo Please install Qt or edit start.bat to set QT_DIR.
    exit /b 1
)

echo [PointCloudSearch] PCL_ROOT=%PCL_ROOT%
echo [PointCloudSearch] QT_DIR=%QT_DIR%

if not exist "%EXE%" (
    echo [PointCloudSearch] Release binary not found, configuring and building...

    where cmake >nul 2>nul
    if errorlevel 1 (
        echo [PointCloudSearch] cmake not found on PATH.
        exit /b 1
    )

    cmake -S . -B "%BUILD_DIR%" -G "Visual Studio 18 2026" -A x64 -DPCL_ROOT="%PCL_ROOT%" -DCMAKE_PREFIX_PATH="%QT_DIR%"
    if errorlevel 1 (
        echo [PointCloudSearch] CMake configure failed.
        exit /b 1
    )

    cmake --build "%BUILD_DIR%" --config Release --target pcsearch_app --parallel 8
    if errorlevel 1 (
        echo [PointCloudSearch] Build failed, see errors above.
        exit /b 1
    )

    echo [PointCloudSearch] Build finished.
)

if "%~1"=="" (
    start "" "%EXE%"
    exit /b 0
)

"%EXE%" %*
exit /b %errorlevel%
