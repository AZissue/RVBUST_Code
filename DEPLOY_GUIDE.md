# Tech Support CRM - 部署指南

## 📋 一、项目概况

- **项目路径**: `D:\RVC_SRC\TechSupportCRM`
- **后端**: FastAPI + SQLite (单文件数据库)
- **前端**: Vue 3 + Element Plus
- **环境**: Conda `Tech` 环境
- **默认端口**: 后端 `38000`，前端 `5173`（开发）

---

## 🚀 二、启动流程

### 方式A：开发模式（前后端分离，推荐开发用）

#### 步骤1：启动后端（PowerShell/CMD）

```powershell
# 1. 激活 Conda 环境
conda activate Tech

# 2. 进入后端目录
cd D:\RVC_SRC\TechSupportCRM\backend

# 3. 启动后端服务
uvicorn main:app --host 0.0.0.0 --port 38000 --reload

# 或简写（脚本已写好）
D:\RVC_SRC\TechSupportCRM\start_backend.bat
```

后端启动成功后，访问 http://localhost:38000/api/health 应返回：
```json
{"code":200,"message":"success","data":{"status":"ok","time":"..."}}
```

#### 步骤2：启动前端（另一个 PowerShell/CMD 窗口）

```powershell
# 1. 进入前端目录
cd D:\RVC_SRC\TechSupportCRM\frontend

# 2. 启动开发服务器
npm run dev

# 或简写（脚本已写好）
D:\RVC_SRC\TechSupportCRM\start_frontend.bat
```

前端启动后，访问 http://localhost:5173

#### 步骤3：一键启动（推荐）

双击运行：
```
D:\RVC_SRC\TechSupportCRM\start_all.bat
```

会自动弹出两个 CMD 窗口分别运行前后端。

---

### 方式B：生产模式（单端口部署，推荐部署用）

#### 步骤1：构建前端

```powershell
cd D:\RVC_SRC\TechSupportCRM\frontend
npm run build
```

构建完成后，会在 `frontend/dist` 目录生成静态文件。

#### 步骤2：启动后端（自动托管前端）

```powershell
# 1. 激活环境
conda activate Tech

# 2. 进入后端目录
cd D:\RVC_SRC\TechSupportCRM\backend

# 3. 启动服务
uvicorn main:app --host 0.0.0.0 --port 38000

# 或简写（脚本已写好）
D:\RVC_SRC\TechSupportCRM\deploy.bat
```

访问 http://localhost:38000 即可使用前后端。

---

## 📊 三、公网部署建议

### 方案对比

| 维度 | 云服务器（推荐） | 树莓派 |
|------|------------------|--------|
| **公网IP** | ✅ 自带稳定公网IP | ❌ 需内网穿透/DDNS |
| **带宽** | ✅ 1-5Mbps 起步 | ❌ 受家庭宽带上行限制（通常30-100kbps） |
| **稳定性** | ✅ 7×24运行，IDC机房 | ⚠️ 断电/断网即中断，需UPS |
| **备案** | ⚠️ 国内服务器需域名备案 | ✅ 无需备案（用IP访问） |
| **费用** | 💰 99-300元/年（入门级） | 💰 一次性投入300-800元 |
| **维护** | ✅ 云平台提供监控/备份 | ❌ 全靠自己维护 |
| **扩展性** | ✅ 随时升级配置 | ❌ 固定性能 |

### 结论：强烈推荐云服务器

**原因：**
1. **5人团队使用**：树莓派的家庭宽带上行带宽根本撑不住多人同时访问
2. **公网访问**：云服务器自带公网IP，无需折腾内网穿透
3. **稳定性**：云服务器在IDC机房，有UPS、多线BGP，远比家用环境稳定
4. **维护简单**：云平台一键备份、监控告警、安全组防火墙

---

## 🌐 四、云服务器部署详细方案

### 推荐配置

| 配置项 | 建议 |
|--------|------|
| **CPU/内存** | 1核2GB（足够5人使用） |
| **带宽** | 3Mbps（日常够用） |
| **系统** | Ubuntu 22.04 LTS 或 CentOS 8 |
| **费用** | 阿里云/腾讯云 轻量应用服务器 约 99-200元/年 |

### 部署步骤（Linux 服务器）

#### 1. 安装依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-pip

# 安装 conda（可选，推荐）
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
source ~/.bashrc
```

#### 2. 上传项目

```bash
# 本地打包上传
scp -r D:\RVC_SRC\TechSupportCRM root@你的服务器IP:/opt/

# 或上传到 GitHub，服务器拉取
git clone https://github.com/你的仓库/TechSupportCRM.git /opt/TechSupportCRM
```

#### 3. 安装环境

```bash
cd /opt/TechSupportCRM

# 创建环境
conda create -n Tech python=3.11 -y
conda activate Tech

# 安装依赖
pip install -r requirements.txt
```

#### 4. 构建前端

```bash
cd /opt/TechSupportCRM/frontend

# 安装 Node.js（如未安装）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 安装依赖并构建
npm install
npm run build
```

#### 5. 配置系统服务（systemd）

创建服务文件：`/etc/systemd/system/techsupport.service`

```ini
[Unit]
Description=Tech Support CRM
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/TechSupportCRM/backend
ExecStart=/root/miniconda3/envs/Tech/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable techsupport
sudo systemctl start techsupport
sudo systemctl status techsupport
```

#### 6. 配置 Nginx（反向代理 + HTTPS）

```bash
sudo apt install -y nginx
```

创建配置 `/etc/nginx/sites-available/techsupport`：

```nginx
server {
    listen 80;
    server_name your-domain.com;  # 或你的服务器IP

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

启用配置：
```bash
sudo ln -s /etc/nginx/sites-available/techsupport /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 7. 配置 HTTPS（可选，推荐）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 🔒 五、安全建议

1. **防火墙**：只开放 80/443 端口，关闭其他端口
2. **数据库**：SQLite 单文件，定期备份到云存储
3. **访问控制**：如需登录验证，后续可添加简单 Basic Auth
4. **备份策略**：
   ```bash
   # 每天凌晨3点备份数据库
   0 3 * * * cp /opt/TechSupportCRM/backend/tech_support.db /backup/tech_support_$(date +\%Y\%m\%d).db
   ```

---

## 📦 六、快速检查清单

部署完成后验证：

- [ ] 访问 `http://你的IP` 能打开登录页
- [ ] 能创建客户和工单
- [ ] 数据导出功能正常
- [ ] 定时提醒任务运行（查看日志）
- [ ] 服务器重启后自动启动（systemctl status techsupport）

---

## ❓ 七、常见问题

**Q: 为什么不用树莓派？**
A: 家用宽带上行带宽通常只有 30-100 kbps，5人同时访问会卡死。且没有固定公网IP，需要额外购买内网穿透服务。

**Q: 云服务器选哪家？**
A: 推荐阿里云/腾讯云轻量应用服务器，99元/年起步，性价比高。

**Q: 需要域名吗？**
A: 不需要，直接用 IP 访问也可以。有域名更专业，但国内服务器需要备案。

**Q: 数据怎么备份？**
A: 只需备份 `backend/tech_support.db` 这一个 SQLite 文件，每天复制一份到安全位置即可。
