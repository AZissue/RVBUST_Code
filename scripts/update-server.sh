#!/bin/bash
# CRM_New 服务器端更新脚本
# 位置: /opt/crm-new/scripts/update-server.sh
# 用法: bash /opt/crm-new/scripts/update-server.sh

set -e

PROJECT_DIR="/opt/crm-new"
APP_NAME="crm-new"
PORT="38000"

echo "=== CRM_New 服务器更新 ==="

# 1. 进入项目目录
cd "$PROJECT_DIR"

# 2. 拉取最新代码
echo "[1/4] 拉取 GitHub 最新代码..."
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "    代码已是最新，无需更新"
    exit 0
fi

echo "    本地: ${LOCAL:0:8} → 远程: ${REMOTE:0:8}"
git reset --hard origin/master

# 3. 安装依赖
echo "[2/4] 安装依赖..."
cd project
npm install --production

# 4. 确保目录结构
echo "[3/4] 确保目录结构..."
mkdir -p uploads
mkdir -p logs

# 5. 重启服务
echo "[4/4] 重启 PM2 服务..."
pm2 restart "$APP_NAME" 2>/dev/null || pm2 start server.js --name "$APP_NAME" -- --port "$PORT"
pm2 save

echo ""
echo "[OK] 更新完成"
echo "[URL] http://$(curl -s icanhazip.com || echo '服务器IP'):$PORT"
echo "[PM2] pm2 status"
pm2 status
