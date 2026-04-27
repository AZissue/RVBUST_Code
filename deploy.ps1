# CRM_New 一键部署脚本
# 用法：.\deploy.ps1
# 功能：本地 push → GitHub → SSH 触发服务器拉取更新

param(
    [string]$CommitMessage = "Update CRM_New",
    [string]$ServerIP = "120.55.245.72",
    [string]$ServerUser = "root",
    [string]$ServerPass = "010921Zj",
    [int]$ServerPort = 38000
)

$ErrorActionPreference = "Stop"

Write-Host "=== CRM_New 一键部署 ===" -ForegroundColor Cyan

# 1. 检查是否在正确的目录
$repoPath = "D:\RVC_SRC\CRM_New"
if (-not (Test-Path "$repoPath\.git")) {
    Write-Error "未找到 Git 仓库，请确认目录: $repoPath"
    exit 1
}

Set-Location $repoPath

# 2. 检查改动
Write-Host "[1/5] 检查 Git 状态..." -ForegroundColor Yellow
$status = git status --short
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "    没有未提交的改动，直接推送现有代码" -ForegroundColor Gray
} else {
    Write-Host "    发现未提交改动:" -ForegroundColor Yellow
    $status | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }
    
    # 3. 提交
    Write-Host "[2/5] 提交改动..." -ForegroundColor Yellow
    git add -A
    git commit -m "$CommitMessage"
    Write-Host "    提交完成" -ForegroundColor Green
}

# 4. 推送到 GitHub
Write-Host "[3/5] 推送到 GitHub (master)..." -ForegroundColor Yellow
try {
    git push origin master --force 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    Write-Host "    推送完成" -ForegroundColor Green
} catch {
    Write-Error "GitHub 推送失败: $_"
    exit 1
}

# 5. SSH 到服务器执行更新
Write-Host "[4/5] 连接服务器并更新..." -ForegroundColor Yellow

# 使用 sshpass 或直接 ssh（如果配置了密钥）
# 方案 A: 如果服务器有 SSH 密钥免密登录
# ssh ${ServerUser}@${ServerIP} "cd /opt/crm-new && git fetch origin && git reset --hard origin/master && cd project && npm install && pm2 restart crm-new"

# 方案 B: 使用明文密码（需要安装 sshpass 或 plink）
# 这里先用 echo 管道方式
$sshCommand = @"
cd /opt/crm-new && \
git fetch origin && \
git reset --hard origin/master && \
cd project && \
npm install && \
pm2 restart crm-new && \
echo '[OK] 更新完成'
"@

# 尝试 SSH 连接（使用 sshpass 或 expect）
try {
    # 使用 Windows 自带的 ssh + echo 管道传递密码
    $sshCmd = "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 ${ServerUser}@${ServerIP} `"${sshCommand}`""
    Write-Host "    执行: $sshCmd" -ForegroundColor Gray
    
    # 由于需要密码交互，这里提示用户手动执行或配置密钥
    Write-Host "    ⚠️ 需要服务器密码: $ServerPass" -ForegroundColor Yellow
    Write-Host "    如果 SSH 密钥已配置，会自动连接" -ForegroundColor Yellow
    
    # 尝试执行
    $result = Invoke-Expression $sshCmd 2>&1
    $result | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
} catch {
    Write-Warning "SSH 连接失败: $_"
    Write-Host "    请手动在服务器执行:" -ForegroundColor Cyan
    Write-Host "    $sshCommand" -ForegroundColor White
}

# 6. 验证
Write-Host "[5/5] 验证部署..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

try {
    $response = Invoke-WebRequest -Uri "http://${ServerIP}:${ServerPort}/api/health" -TimeoutSec 10 -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        Write-Host "    ✅ 服务正常运行" -ForegroundColor Green
    } else {
        Write-Host "    ⚠️ 服务返回状态码: $($response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "    ⚠️ 无法连接到服务，请稍后手动检查" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 部署流程结束 ===" -ForegroundColor Cyan
Write-Host "访问地址: http://${ServerIP}:${ServerPort}" -ForegroundColor White
Write-Host ""
Write-Host "如果 SSH 更新失败，请手动执行:" -ForegroundColor Yellow
Write-Host "  ssh ${ServerUser}@${ServerIP}" -ForegroundColor White
Write-Host "  bash /opt/update-crm.sh" -ForegroundColor White
