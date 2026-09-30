@echo off
chcp 65001 >nul
rem ---------------------------------------------------------------
rem Shuang-ji jiu neng yong: qi fu wu + zi dong kai liu lan qi.
rem (ASCII-only above the chcp line: cmd parses the file with the OEM
rem  code page until the switch, and GBK trail bytes can turn into
rem  | or & metacharacters. Everything Chinese lives below it.)
rem Runs in THIS window so Ctrl+C stops it cleanly - no stuck window.
rem ---------------------------------------------------------------
cd /d "%~dp0.."
title 三方工作群 (人 / A / B)
echo [trio] 正在启动三方工作群（Ctrl+C 退出；地址见下一行）
echo [trio] 想零花费先看界面长什么样：把下面的命令换成 --demo --open
echo.
python ".trio\serve.py" --open
if errorlevel 1 (
  echo.
  echo [trio] 服务异常退出（端口被占用？先关掉旧的窗口再试）。
  pause
)
