param([string]$OutputDirectory = "$PSScriptRoot/outputs")
$env:PYTHONIOENCODING = 'utf-8'
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' "$PSScriptRoot/app/quick_extrinsic.py" --output $OutputDirectory
exit $LASTEXITCODE
