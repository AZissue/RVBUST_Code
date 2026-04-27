# 上传并部署 CRM_New 到服务器
# 密码通过管道输入

$password = "010921Zj"
$host_ip = "120.55.245.72"
$user = "root"
$local_tar = "D:\RVC_SRC\CRM_New\crm-new.tar.gz"
$local_script = "D:\RVC_SRC\CRM_New\deploy.sh"

# 1. 上传 tar.gz
Write-Host "📤 上传 crm-new.tar.gz ..."
$pinfo = New-Object System.Diagnostics.ProcessStartInfo
$pinfo.FileName = "scp.exe"
$pinfo.Arguments = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $local_tar ${user}@${host_ip}:/opt/crm-new.tar.gz"
$pinfo.RedirectStandardInput = $true
$pinfo.RedirectStandardOutput = $true
$pinfo.RedirectStandardError = $true
$pinfo.UseShellExecute = $false
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $pinfo
$process.Start() | Out-Null
Start-Sleep -Seconds 1
$process.StandardInput.WriteLine($password)
$process.StandardInput.Close()
$output = $process.StandardOutput.ReadToEnd()
$error_output = $process.StandardError.ReadToEnd()
$process.WaitForExit()
Write-Host $output
if ($error_output) { Write-Host "SCP stderr: $error_output" }

# 2. 上传 deploy.sh
Write-Host "📤 上传 deploy.sh ..."
$pinfo2 = New-Object System.Diagnostics.ProcessStartInfo
$pinfo2.FileName = "scp.exe"
$pinfo2.Arguments = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $local_script ${user}@${host_ip}:/opt/deploy.sh"
$pinfo2.RedirectStandardInput = $true
$pinfo2.RedirectStandardOutput = $true
$pinfo2.RedirectStandardError = $true
$pinfo2.UseShellExecute = $false
$process2 = New-Object System.Diagnostics.Process
$process2.StartInfo = $pinfo2
$process2.Start() | Out-Null
Start-Sleep -Seconds 1
$process2.StandardInput.WriteLine($password)
$process2.StandardInput.Close()
$output2 = $process2.StandardOutput.ReadToEnd()
$error2 = $process2.StandardError.ReadToEnd()
$process2.WaitForExit()
Write-Host $output2
if ($error2) { Write-Host "SCP2 stderr: $error2" }

# 3. SSH 执行部署
Write-Host "🚀 执行远程部署 ..."
$commands = @"
cd /opt
bash deploy.sh
"@
$pinfo3 = New-Object System.Diagnostics.ProcessStartInfo
$pinfo3.FileName = "ssh.exe"
$pinfo3.Arguments = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ${user}@${host_ip}"
$pinfo3.RedirectStandardInput = $true
$pinfo3.RedirectStandardOutput = $true
$pinfo3.RedirectStandardError = $true
$pinfo3.UseShellExecute = $false
$process3 = New-Object System.Diagnostics.Process
$process3.StartInfo = $pinfo3
$process3.Start() | Out-Null
Start-Sleep -Seconds 1
$process3.StandardInput.WriteLine($password)
Start-Sleep -Seconds 2
$process3.StandardInput.WriteLine("cd /opt && bash deploy.sh")
Start-Sleep -Seconds 1
$process3.StandardInput.WriteLine("exit")
$process3.StandardInput.Close()
$output3 = $process3.StandardOutput.ReadToEnd()
$error3 = $process3.StandardError.ReadToEnd()
$process3.WaitForExit()
Write-Host "=== SSH 输出 ==="
Write-Host $output3
if ($error3) { Write-Host "SSH stderr: $error3" }

Write-Host "✅ 部署流程结束"
