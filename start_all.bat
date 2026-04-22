@echo off
chcp 65001 >nul
echo ========================================
echo  Tech Support CRM - 一键启动工具
echo ========================================
echo.

:: 检查 Conda 环境
conda info --envs | findstr "Tech" >nul
if errorlevel 1 (
    echo [错误] 未找到 Tech 环境，请先创建环境
    pause
    exit /b 1
)

:: 启动后端（新窗口）
echo [1/2] 正在启动后端服务...
start "TechSupportCRM-Backend" cmd /k "cd /d D:\RVC_SRC\TechSupportCRM\backend && conda activate Tech && uvicorn main:app --host 0.0.0.0 --port 38000 --reload"

:: 等待后端启动
timeout /t 3 /nobreak >nul

:: 检查后端是否启动
curl -s http://localhost:38000/api/dashboard/stats >nul
if %errorlevel% == 0 (
    echo [✓] 后端启动成功 (http://localhost:38000)
) else (
    echo [!] 后端可能还在启动中...
)

:: 启动前端（新窗口）
echo [2/2] 正在启动前端服务...
start "TechSupportCRM-Frontend" cmd /k "cd /d D:\RVC_SRC\TechSupportCRM\frontend && npm run dev"

:: 等待前端启动
timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo  启动完成！
echo ========================================
echo  前端访问: http://localhost:5173
echo  后端API:  http://localhost:38000
echo.
echo  请保持两个窗口运行，关闭窗口即停止服务
echo ========================================
pause