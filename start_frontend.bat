@echo off
chcp 65001 >nul
echo 正在启动 Tech Support CRM 前端...
cd /d D:\RVC_SRC\TechSupportCRM\frontend
npm run dev
echo 前端已停止
pause