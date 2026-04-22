@echo off
chcp 65001 >nul
echo ========================================
echo  Tech Support CRM - 生产环境部署
echo ========================================
echo.

:: 1. 进入前端目录并打包
echo [1/3] 正在构建前端...
cd /d D:\RVC_SRC\TechSupportCRM\frontend
if not exist node_modules (
    echo [错误] 未找到 node_modules，请先运行 npm install
    pause
    exit /b 1
)

:: 使用生产配置打包
npm run build -- --config vite.config.prod.js
if errorlevel 1 (
    echo [错误] 前端构建失败
    pause
    exit /b 1
)
echo [✓] 前端构建完成

:: 2. 启动后端（托管前端静态文件）
echo.
echo [2/3] 正在启动生产服务器...
echo.
echo ========================================
echo  部署完成！
echo ========================================
echo  访问地址: http://localhost:38000
echo  局域网 :  http://[本机IP]:38000
echo.
echo  按 Ctrl+C 停止服务
echo ========================================
cd /d D:\RVC_SRC\TechSupportCRM\backend
conda activate Tech && uvicorn main:app --host 0.0.0.0 --port 38000

pause