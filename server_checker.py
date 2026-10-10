import os
import logging
import asyncio

from telegram import (
    Update,
    InputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from telegram.error import TimedOut, TelegramError

from checker_core import ServerChecker


# ============================================================
# НАСТРОЙКИ
# ============================================================


# set TELEGRAM_BOT_TOKEN=твой_токен
API_TOKEN = ""

ADMIN_CHAT_ID = 


region_servers = {
    "Chicago": 5,
    "Atlanta": 6,
    "Dallas": 5,
    "Frankfurt": 5,
    "Los Angeles": 3,
    "Miami": 4,
    "Mumbai": 2,
    "New York": 4,
    "Paris": 4,
    "Sao Paulo": 5,
    "Seattle": 3,
    "Silicon Valley": 4,
    "Singapore": 9,
    "Sydney": 3,
    "Tokyo": 3,
    "Toronto": 6,
    "St Petersburg": 2,
    "Manchester": 2,
    "Warsaw": 2,
    "Jerusalem": 2,
    "Bangalore": 2,
    "Madrid": 2,
    "Delhi NCR": 2,
    "Seoul": 3,
    "Johannesburg": 2,
    "Mexico City": 2,
    "Santiago": 2,
    "Melbourne": 2,
}


REGION_GROUPS = {
    "🇪🇺 EU": [
        "Frankfurt",
        "Paris",
        "Madrid",
        "Warsaw",
        "Manchester",
        "St Petersburg",
    ],

    "🌏 Asia": [
        "Singapore",
        "Tokyo",
        "Seoul",
        "Mumbai",
        "Bangalore",
        "Delhi NCR",
        "Jerusalem",
    ],

    "🇺🇸 North America": [
        "Chicago",
        "Atlanta",
        "Dallas",
        "Los Angeles",
        "Miami",
        "New York",
        "Seattle",
        "Silicon Valley",
        "Toronto",
        "Mexico City",
    ],

    "🇧🇷 South America": [
        "Sao Paulo",
        "Santiago",
    ],

    "🇦🇺 Oceania": [
        "Sydney",
        "Melbourne",
    ],

    "🌍 Africa": [
        "Johannesburg",
    ],
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# ОЧЕРЕДЬ ПРОВЕРОК
# ============================================================

# В очереди лежат кортежи:
# (chat_id, region)
check_queue = asyncio.Queue()

# Регион, который сейчас проверяется.
current_region = None


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def build_main_groups_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                "🇪🇺 EU",
                callback_data="group:🇪🇺 EU",
            ),
            InlineKeyboardButton(
                "🌏 Asia",
                callback_data="group:🌏 Asia",
            ),
        ],

        [
            InlineKeyboardButton(
                "🇺🇸 North America",
                callback_data="group:🇺🇸 North America",
            ),
        ],

        [
            InlineKeyboardButton(
                "🇧🇷 South America",
                callback_data="group:🇧🇷 South America",
            ),
            InlineKeyboardButton(
                "🇦🇺 Oceania",
                callback_data="group:🇦🇺 Oceania",
            ),
        ],

        [
            InlineKeyboardButton(
                "🌍 Africa",
                callback_data="group:🌍 Africa",
            ),
        ],
    ]

    return InlineKeyboardMarkup(rows)


def build_regions_keyboard_for_group(
    group_name: str,
    cols: int = 2,
) -> InlineKeyboardMarkup:

    regions = REGION_GROUPS.get(
        group_name,
        [],
    )

    rows = []
    row = []

    for i, region in enumerate(
        regions,
        start=1,
    ):
        row.append(
            InlineKeyboardButton(
                region,
                callback_data=f"check:{region}",
            )
        )

        if i % cols == 0:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Назад к группам",
                callback_data="menu:groups",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# ============================================================
# РАБОТА СО СКРИНШОТАМИ
# ============================================================

def collect_region_files(
    folder: str,
    region: str,
):
    if not os.path.isdir(folder):
        return []

    all_png = sorted(
        [
            f
            for f in os.listdir(folder)
            if f.lower().endswith(".png")
        ]
    )

    prefix_space = region + "_"
    prefix_underscore = (
        region.replace(" ", "_") + "_"
    )

    return [
        f
        for f in all_png
        if (
            f.startswith(prefix_space)
            or f.startswith(prefix_underscore)
        )
    ]


def clear_region_screenshots(
    folder: str,
    region: str,
):
    """
    Удаляет старые PNG-скриншоты
    только для указанного региона.
    """

    if not os.path.isdir(folder):
        return

    prefix_space = region + "_"
    prefix_underscore = (
        region.replace(" ", "_") + "_"
    )

    for fname in os.listdir(folder):

        if not fname.lower().endswith(".png"):
            continue

        if (
            fname.startswith(prefix_space)
            or fname.startswith(prefix_underscore)
        ):
            try:
                os.remove(
                    os.path.join(
                        folder,
                        fname,
                    )
                )

            except Exception as e:
                logger.warning(
                    "Не удалось удалить %s: %s",
                    fname,
                    e,
                )


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Привет!\n"
        "Нажми /servers и выбери группу региона."
    )


async def servers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Выбери группу серверов:",
        reply_markup=build_main_groups_keyboard(),
    )


# ============================================================
# ДОБАВЛЕНИЕ В ОЧЕРЕДЬ
# ============================================================

async def add_to_queue(
    chat_id: int,
    region: str,
    bot,
):
    global current_region

    waiting = check_queue.qsize()

    # Если что-то уже проверяется, новая задача
    # будет стоять после текущей.
    if current_region is not None:
        position = waiting + 2
    else:
        position = waiting + 1

    await check_queue.put(
        (
            chat_id,
            region,
        )
    )

    if position == 1:
        message = (
            f"✅ {region} добавлен в очередь.\n"
            "Запустится сейчас."
        )
    else:
        message = (
            f"✅ {region} добавлен в очередь.\n"
            f"Позиция в очереди: {position}"
        )

    await bot.send_message(
        chat_id=chat_id,
        text=message,
    )


# ============================================================
# ПРОВЕРКА РЕГИОНА И ОТПРАВКА СКРИНОВ
# ============================================================

async def run_check_and_send(
    bot,
    chat_id: int,
    region: str,
):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🔍 Проверяю сервера региона "
            f"{region}..."
        ),
    )

    checker = ServerChecker(
        region_name=region,
        server_count=region_servers[region],
        headless=False,
    )

    # Удаляем старые скриншоты
    # только выбранного региона.
    clear_region_screenshots(
        checker.screenshot_dir,
        region,
    )

    loop = asyncio.get_running_loop()

    try:
        # ServerChecker синхронный, поэтому
        # выполняем его в отдельном потоке.
        # Telegram-бот при этом продолжает
        # принимать новые кнопки и складывать
        # регионы в очередь.
        await loop.run_in_executor(
            None,
            checker.check_servers,
        )

    except Exception as e:
        logger.exception(
            "Ошибка ServerChecker для региона %s",
            region,
        )

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"❌ Ошибка при проверке "
                f"{region}:\n{e}"
            ),
        )

        return

    folder = checker.screenshot_dir

    if not os.path.isdir(folder):
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Папка скриншотов "
                f"не найдена: {folder}"
            ),
        )
        return

    region_files = collect_region_files(
        folder,
        region,
    )

    if not region_files:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ Для региона {region} "
                "скриншоты не найдены."
            ),
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Проверка завершена. "
            "Отправляю скриншоты..."
        ),
    )

    for filename in region_files:
        filepath = os.path.join(
            folder,
            filename,
        )

        try:
            with open(filepath, "rb") as file:
                await bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(file),
                    filename=filename,
                )

            await asyncio.sleep(1)

        except (TimedOut, TelegramError) as e:
            logger.exception(
                "Ошибка отправки %s",
                filename,
            )

            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "❌ Ошибка при отправке "
                        f"{filename}: {e}"
                    ),
                )

            except TelegramError:
                pass

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ Регион {region} "
            "полностью обработан."
        ),
    )


# ============================================================
# WORKER ОЧЕРЕДИ
# ============================================================

async def queue_worker(
    app: Application,
):
    global current_region

    logger.info(
        "Обработчик очереди запущен."
    )

    while True:

        chat_id, region = await check_queue.get()

        current_region = region

        logger.info(
            "Начинаем обработку региона %s",
            region,
        )

        try:
            await run_check_and_send(
                bot=app.bot,
                chat_id=chat_id,
                region=region,
            )

        except Exception as e:
            logger.exception(
                "Необработанная ошибка "
                "при проверке региона %s",
                region,
            )

            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"❌ Ошибка при обработке "
                        f"{region}: {e}"
                    ),
                )
            except TelegramError:
                pass

        finally:
            current_region = None
            check_queue.task_done()

            logger.info(
                "Регион %s удалён из очереди.",
                region,
            )


# ============================================================
# /check
# ============================================================

async def check(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        await update.message.reply_text(
            "Выбери группу, потом регион:",
            reply_markup=build_main_groups_keyboard(),
        )
        return

    region = " ".join(
        context.args
    ).title()

    if region not in region_servers:
        await update.message.reply_text(
            f"Регион '{region}' не найден. "
            "Выбери через /servers."
        )
        return

    await add_to_queue(
        chat_id=update.effective_chat.id,
        region=region,
        bot=context.bot,
    )


# ============================================================
# INLINE BUTTON ROUTER
# ============================================================

async def button_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    data = query.data or ""

    # --------------------------------------------------------
    # Назад к группам
    # --------------------------------------------------------

    if data == "menu:groups":
        await query.message.reply_text(
            "Выбери группу серверов:",
            reply_markup=build_main_groups_keyboard(),
        )
        return

    # --------------------------------------------------------
    # Выбор группы
    # --------------------------------------------------------

    if data.startswith("group:"):
        group_name = data.split(
            "group:",
            1,
        )[1]

        if group_name not in REGION_GROUPS:
            await query.message.reply_text(
                "Неизвестная группа."
            )
            return

        await query.message.reply_text(
            f"Группа {group_name}. "
            "Выбери регион:",
            reply_markup=(
                build_regions_keyboard_for_group(
                    group_name,
                    cols=2,
                )
            ),
        )

        return

    # --------------------------------------------------------
    # Выбор региона
    # --------------------------------------------------------

    if data.startswith("check:"):
        region = data.split(
            "check:",
            1,
        )[1]

        if region not in region_servers:
            await query.message.reply_text(
                f"Регион '{region}' не найден."
            )
            return

        # ВАЖНО:
        # здесь мы НЕ запускаем проверку напрямую.
        # Мы только кладём её в очередь.
        await add_to_queue(
            chat_id=query.message.chat_id,
            region=region,
            bot=context.bot,
        )

        return


# ============================================================
# POST INIT
# ============================================================

async def post_init(
    app: Application,
):
    # Запускаем одного worker-а.
    # Поэтому одновременно работает
    # только ОДНА проверка ServerChecker.
    asyncio.create_task(
        queue_worker(app)
    )

    logger.info(
        "Очередь проверок запущена."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not API_TOKEN:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN.\n"
            "В CMD перед запуском выполни:\n"
            "set TELEGRAM_BOT_TOKEN=ТВОЙ_ТОКЕН"
        )

    print("Запускаем бота...")

    app = (
        Application.builder()
        .token(API_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "servers",
            servers,
        )
    )

    app.add_handler(
        CommandHandler(
            "check",
            check,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_router
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
