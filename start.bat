@echo off
setlocal
title Taming.io Server Checker

cd /d "%~dp0"

set "PYTHON=%~dp0venv\Scripts\python.exe"
set "OPERA=%LOCALAPPDATA%\Programs\Opera GX\opera.exe"
set "PROFILE=%~dp0opera_bot_profile"

if not exist "%PYTHON%" (
    echo.
    echo [ERROR] Python venv not found:
    echo %PYTHON%
    echo.
    pause
    exit /b 1
)

if not exist "%OPERA%" (
    echo.
    echo [ERROR] Opera GX not found:
    echo %OPERA%
    echo.
    echo Edit the OPERA path inside start.bat.
    pause
    exit /b 1
)

:menu
cls
echo ==========================================
echo        Taming.io Server Checker
echo ==========================================
echo.
echo 1. Discord bot
echo 2. Telegram bot
echo 3. Opera GX only
echo 0. Exit
echo.

set /p "choice=Select: "

if "%choice%"=="1" goto discord
if "%choice%"=="2" goto telegram
if "%choice%"=="3" goto browser
if "%choice%"=="0" goto end

goto menu

:start_browser
echo.
echo Starting Opera GX...
start "" "%OPERA%" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="%PROFILE%" "https://taming.io/"
echo Waiting for browser startup...
timeout /t 5 /nobreak >nul
exit /b 0

:discord
call :start_browser
echo.
echo Starting Discord bot...
echo.
"%PYTHON%" "%~dp0dsbot.py"
echo.
echo Discord bot stopped.
pause
goto menu

:telegram
call :start_browser
echo.
echo Starting Telegram bot...
echo.
"%PYTHON%" "%~dp0tgbot.py"
echo.
echo Telegram bot stopped.
pause
goto menu

:browser
call :start_browser
echo.
echo Opera GX started.
pause
goto menu

:end
endlocal
exit /b 0
