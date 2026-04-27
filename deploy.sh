#!/bin/bash
# CRM_New 部署脚本 - 端口 38000
set -e

echo "=== CRM_New 部署脚本 ==="

# 1. 创建目录
mkdir -p /opt/crm-new
cd /opt

# 2. 解压
if [ -f /opt/crm-new.tar.gz ]; then
  tar -xzvf /opt/crm-new.tar.gz -C /opt/crm-new/ --strip-components=0
  echo "[OK] 解压完成"
else
  echo "[ERR] 未找到 /opt/crm-new.tar.gz"
  exit 1
fi

# 3. 安装依赖
cd /opt/crm-new/server
npm install --production

# 4. 创建 uploads 目录
mkdir -p uploads

# 5. 检查 Node.js
if ! command -v node &> /dev/null; then
  echo "[WARN] Node.js 未安装"
  exit 1
fi

# 6. 安装 PM2
if ! command -v pm2 &> /dev/null; then
  npm install -g pm2
fi

# 7. 防火墙放行 38000
if command -v firewall-cmd &> /dev/null; then
  firewall-cmd --permanent --add-port=38000/tcp 2>/dev/null || true
  firewall-cmd --reload 2>/dev/null || true
fi

# 8. 启动/重启
pm2 delete crm-new 2>/dev/null || true
pm2 start server.js --name crm-new
pm2 save
pm2 startup systemd 2>/dev/null || true

echo "[OK] 部署完成"
echo "[URL] http://$(curl -s icanhazip.com || echo '你的服务器IP'):38000"
