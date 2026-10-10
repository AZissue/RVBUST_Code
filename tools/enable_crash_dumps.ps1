# 启用 WER LocalDumps：python.exe 崩溃时在 C:\CrashDumps 保留完整转储。
# 需要"以管理员身份运行" PowerShell 后执行本脚本：
#   powershell -ExecutionPolicy Bypass -File tools\enable_crash_dumps.ps1
# 之后崩溃会产生 C:\CrashDumps\python.exe_<pid>.dmp，交给开发用 minidump 分析。
$dumpDir = "C:\CrashDumps"
New-Item -ItemType Directory -Path $dumpDir -Force | Out-Null

$key = "HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\python.exe"
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name "DumpFolder" -Value $dumpDir -Type ExpandString
Set-ItemProperty -Path $key -Name "DumpType" -Value 2 -Type DWord   # 2 = 完整转储
Set-ItemProperty -Path $key -Name "DumpCount" -Value 5 -Type DWord

Write-Host "已启用: python.exe 崩溃完整转储将保存到 $dumpDir（保留最近 5 个）"
