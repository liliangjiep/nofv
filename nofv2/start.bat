@echo off
chcp 65001 >nul
title NOFv2 Trading Bot

echo ========================================
echo   NOFv2 币安交易监控系统
echo ========================================
echo.

:: 启动 Redis (如果没运行)
echo [1/3] 检查 Redis...
E:\tools\redis\redis-cli.exe ping >nul 2>&1
if errorlevel 1 (
    echo      启动 Redis...
    start /min "" E:\tools\redis\redis-server.exe
    timeout /t 2 >nul
) else (
    echo      Redis 已运行
)

:: 启动前端
echo [2/3] 启动前端服务 (端口 8600)...
start /min "NOFv2-Frontend" cmd /c "python api_history.py"
timeout /t 2 >nul

:: 启动后端
echo [3/3] 启动后端服务...
echo.
echo ========================================
echo   前端地址: http://127.0.0.1:8600
echo   按 Ctrl+C 停止后端
echo ========================================
echo.

python main.py

pause
