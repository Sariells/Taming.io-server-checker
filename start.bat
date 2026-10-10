@echo off
chcp 65001 >nul
title Taming.io Server Checker

cd /d "%~dp0"

set "PYTHON=%~dp0venv\Scripts\python.exe"
set "OPERA=%LOCALAPPDATA%\Programs\Opera GX\opera.exe"
set "PROFILE=%~dp0opera_bot_profile"

if not exist "%PYTHON%" (
    echo.
    echo [ERROR] Python из venv не найден:
    echo %PYTHON%
    echo.
    pause
    exit /b 1
)

if not exist "%OPERA%" (
    echo.
    echo [ERROR] Opera GX не найдена:
    echo %OPERA%
    echo.
    echo Измени переменную OPERA внутри start.bat.
    pause
    exit /b 1
)

:menu
cls
echo ==========================================
echo        Taming.io Server Checker
echo ==========================================
echo.
echo 1. Discord версия
echo 2. Telegram версия
echo 3. Только запустить Opera GX
echo 0. Выход
echo.

set /p "choice=Выбери пункт: "

if "%choice%"=="1" goto discord
if "%choice%"=="2" goto telegram
if "%choice%"=="3" goto browser
if "%choice%"=="0" exit /b 0

goto menu

:start_browser
echo.
echo Запускаем Opera GX...

start "" "%OPERA%" ^
    --remote-debugging-port=9222 ^
    --remote-debugging-address=127.0.0.1 ^
    --user-data-dir="%PROFILE%" ^
    "https://taming.io/"

echo Ждём запуск браузера...
timeout /t 5 /nobreak >nul
exit /b 0

:discord
call :start_browser

echo.
echo Запускаем Discord бота...
echo.

"%PYTHON%" "%~dp0dsbot.py"

echo.
echo Discord бот остановлен.
pause
goto menu

:telegram
call :start_browser

echo.
echo Запускаем Telegram бота...
echo.

"%PYTHON%" "%~dp0tgbot.py"

echo.
echo Telegram бот остановлен.
pause
goto menu

:browser
call :start_browser

echo.
echo Opera GX запущена.
pause
goto menu
