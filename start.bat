@echo off
cd /d "%~dp0"
title General Search Agent

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8001"
set "BASE=http://127.0.0.1:%PORT%"

echo ============================================
echo  General Search Agent - 通用网页搜索助手
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 goto NOPYTHON

if not exist ".env" goto NOENV

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if not errorlevel 1 goto START

curl.exe -s -o NUL --max-time 3 "%BASE%/health"
if not errorlevel 1 goto ALREADY

echo [错误] 端口 %PORT% 被其他程序占用。
echo        请换端口启动：start.bat 8002
pause
exit /b 1

:ALREADY
echo 服务已在运行，正在打开 %BASE%
start "" "%BASE%"
ping -n 2 127.0.0.1 >nul
exit /b 0

:START
echo 正在启动：%BASE%
echo 关闭弹出的服务窗口即可停止服务。
echo.
start "General Search Agent" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%"

set "TRIES=0"
:WAIT
if %TRIES% GEQ 60 goto TIMEOUT
set /a TRIES+=1
ping -n 2 127.0.0.1 >nul
curl.exe -s -o NUL --max-time 2 "%BASE%/health"
if not errorlevel 1 goto OPEN
goto WAIT

:TIMEOUT
echo.
echo [警告] 服务 60 秒内没有就绪，请看服务窗口中的报错。
pause
exit /b 1

:OPEN
echo 服务已就绪，正在打开浏览器...
start "" "%BASE%"
exit /b 0

:NOPYTHON
echo [错误] 没有找到 python，请安装 Python 3.11+ 并加入 PATH。
pause
exit /b 1

:NOENV
echo [错误] 缺少 .env，请复制 .env.example 为 .env 并填写配置。
pause
exit /b 1