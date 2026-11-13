@echo off
cd /d "%~dp0"
"D:\Program Files\Anaconda\envs\rvc\python.exe" app.py
if errorlevel 1 pause
