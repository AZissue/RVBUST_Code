@echo off
chcp 65001 >nul
echo 正在启动 Tech Support CRM 后端...
cd /d D:\RVC_SRC\TechSupportCRM\backend
conda activate Tech && uvicorn main:app --host 0.0.0.0 --port 38000 --reload
echo 后端已停止
pause