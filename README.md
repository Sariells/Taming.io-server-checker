# Taming.io Server Checker

Бот автоматически проверяет серверы Taming.io, делает скриншоты и отправляет их в Telegram или Discord.

## Что нужно

- Python 3.10+
- Opera GX
- VPN/доступ к Taming.io
- Playwright
- Telegram Bot Token или Discord Bot Token

## Файлы

```text
checker_core.py   # проверка серверов
tgbot.py          # Telegram версия
dsbot.py          # Discord версия
start.bat         # запуск
screens/          # скриншоты
```

## Установка

```bat
python -m venv venv
venv\Scripts\python.exe -m pip install playwright python-telegram-bot discord.py
```

Если `checker_core.py` использует дополнительные библиотеки, установи и их.

## Токены

Токены вставляются **напрямую в Python-файлы**, а не в `.bat`.

### Telegram

В `tgbot.py`:

```python
API_TOKEN = "ТВОЙ_TELEGRAM_TOKEN"
```

### Discord

В `dsbot.py`:

```python
DISCORD_TOKEN = "ТВОЙ_DISCORD_TOKEN"
```

Не публикуй реальные токены в GitHub. Перед публичным коммитом замени их на тестовые значения.

## Opera GX

`start.bat` автоматически запускает отдельный профиль Opera GX с CDP-портом `9222`.

Путь по умолчанию:

```text
C:\Users\%USERNAME%\AppData\Local\Programs\Opera GX\opera.exe
```

Профиль:

```text
opera_bot_profile
```

После первого запуска:

1. Включи VPN в этом профиле Opera GX.
2. Открой Taming.io.
3. Если появился Cloudflare — пройди проверку вручную.
4. После этого запускай Telegram или Discord бота через `start.bat`.

## Запуск

Запусти:

```text
start.bat
```

Меню:

```text
1 - Discord
2 - Telegram
3 - Только Opera GX
0 - Выход
```

Браузер запускается автоматически перед ботом.

## Использование

### Discord

```text
!servers
```

Выбери группу и регион кнопками. Можно добавить несколько регионов подряд — они попадут в очередь. Скриншоты одного региона отправляются вместе.

### Telegram

```text
/servers
```

Выбери группу и регион кнопками. Можно нажать несколько регионов подряд — бот обработает их по очереди.

## Важно

- Opera GX должна запускаться с `--remote-debugging-port=9222`.
- Бот работает с вкладкой Taming.io в этом профиле.
- При Cloudflare может потребоваться ручное подтверждение.
- Не запускай одновременно Telegram и Discord версии, если обе используют один и тот же браузер.
<img width="238" height="784" alt="image" src="https://github.com/user-attachments/assets/06ea2873-6ac4-40d0-9930-1d6b550f8059" />
