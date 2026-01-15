@echo off
chcp 65001 >nul
echo 正在停止 NOFv2 服务...

taskkill /f /im python.exe /fi "WINDOWTITLE eq NOFv2*" >nul 2>&1
echo 服务已停止

pause
