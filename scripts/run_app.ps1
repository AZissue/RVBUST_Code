param()
$root = Split-Path -Parent $PSScriptRoot
$qt = "D:\Program Files\Qt\6.8.3\msvc2022_64"
$pcl = "D:\Program Files\PCL 1.13.0"
$vtk = "D:\Program Files\VTK\bin"
$env:PATH = "$qt\bin;$pcl\bin;$pcl\3rdParty\Boost\lib;$pcl\3rdParty\FLANN\bin;$pcl\3rdParty\Qhull\bin;$vtk;$env:PATH"
$exe = Join-Path $root "build\app\Release\pcsearch_app.exe"
if (Test-Path $exe) {
    & $exe
} else {
    Write-Error "pcsearch_app.exe not found: $exe"
}
