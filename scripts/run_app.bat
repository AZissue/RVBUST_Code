@echo off
rem PointCloudSearch desktop app launcher
setlocal
set "PCS_ROOT=%~dp0.."
set "QT_DIR=D:\Program Files\Qt\6.8.3\msvc2022_64"
set "PCL_DIR=D:\Program Files\PCL 1.13.0"
set "VTK_DIR=D:\Program Files\VTK\bin"

set "PATH=%QT_DIR%\bin;%PCL_DIR%\bin;%PCL_DIR%\3rdParty\Boost\lib;%PCL_DIR%\3rdParty\FLANN\bin;%PCL_DIR%\3rdParty\Qhull\bin;%VTK_DIR%;%PATH%"

if exist "%PCS_ROOT%\build\app\Release\pcsearch_app.exe" (
    start "" "%PCS_ROOT%\build\app\Release\pcsearch_app.exe"
) else (
    echo pcsearch_app.exe not found. Build it first:
    echo   cmake -S "%PCS_ROOT%" -B "%PCS_ROOT%\build" -DPCSEARCH_BUILD_APP=ON
    echo   cmake --build "%PCS_ROOT%\build" --config Release
)
endlocal

