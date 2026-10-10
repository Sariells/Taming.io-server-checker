@echo off
REM
if not exist venv (
    echo Создаем виртуальное окружение...
    python -m venv venv
)

echo Активируем виртуальное окружение...
call venv\Scripts\activate.bat

echo Обновляем pip...
python -m pip install --upgrade pip

echo Устанавливаем зависимости из requirements.txt...
pip install -r requirements.txt

echo Запускаем бота...
python dsbot.py

pause
