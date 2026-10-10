import os
import asyncio
import logging

import discord
from discord.ext import commands

from checker_core import ServerChecker

DISCORD_TOKEN = ""

region_servers = {
    "Chicago": 5, "Atlanta": 6, "Dallas": 5, "Frankfurt": 5,
    "Los Angeles": 3, "Miami": 4, "Mumbai": 2, "New York": 4,
    "Paris": 4, "Sao Paulo": 5, "Seattle": 3, "Silicon Valley": 4,
    "Singapore": 9, "Sydney": 3, "Tokyo": 3, "Toronto": 6,
    "St Petersburg": 2, "Manchester": 2, "Warsaw": 2, "Jerusalem": 2,
    "Bangalore": 2, "Madrid": 2, "Delhi NCR": 2, "Seoul": 3,
    "Johannesburg": 2, "Mexico City": 2, "Santiago": 2, "Melbourne": 2,
}

REGION_GROUPS = {
    "🇪🇺 EU": ["Frankfurt", "Paris", "Madrid", "Warsaw", "Manchester", "St Petersburg"],
    "🌏 Asia": ["Singapore", "Tokyo", "Seoul", "Mumbai", "Bangalore", "Delhi NCR", "Jerusalem"],
    "🇺🇸 North America": ["Chicago", "Atlanta", "Dallas", "Los Angeles", "Miami", "New York", "Seattle", "Silicon Valley", "Toronto", "Mexico City"],
    "🇧🇷 South America": ["Sao Paulo", "Santiago"],
    "🇦🇺 Oceania": ["Sydney", "Melbourne"],
    "🌍 Africa": ["Johannesburg"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

check_queue = asyncio.Queue()
current_region = None


def collect_region_files(folder: str, region: str) -> list[str]:
    if not os.path.isdir(folder):
        return []

    prefix_space = region + "_"
    prefix_underscore = region.replace(" ", "_") + "_"

    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(".png")
        and (f.startswith(prefix_space) or f.startswith(prefix_underscore))
    ]

    def server_number(filename: str) -> int:
        try:
            return int(os.path.splitext(filename)[0].rsplit("_", 1)[1])
        except (ValueError, IndexError):
            return 999999

    return sorted(files, key=server_number)


def clear_region_screenshots(folder: str, region: str):
    for filename in collect_region_files(folder, region):
        try:
            os.remove(os.path.join(folder, filename))
        except Exception as e:
            logger.warning("Не удалось удалить %s: %s", filename, e)


async def send_region_screenshots(channel, folder: str, region: str):
    filenames = collect_region_files(folder, region)

    if not filenames:
        await channel.send(f"⚠️ Скриншоты для **{region}** не найдены.")
        return

    attachments = [
        discord.File(os.path.join(folder, filename), filename=filename)
        for filename in filenames
    ]

    try:
        await channel.send(
            content=f"📸 **{region}** — все серверы ({len(attachments)} шт.)",
            files=attachments,
        )
    finally:
        for attachment in attachments:
            try:
                attachment.close()
            except Exception:
                pass


async def add_to_queue(channel, region: str):
    global current_region

    waiting = check_queue.qsize()
    position = waiting + (2 if current_region is not None else 1)

    await check_queue.put((channel, region))

    if position == 1:
        await channel.send(
            f"✅ **{region}** добавлен в очередь. Запустится сейчас."
        )
    else:
        await channel.send(
            f"✅ **{region}** добавлен в очередь. Позиция: **{position}**"
        )


async def run_check_and_send(channel, region: str):
    await channel.send(f"🔍 Проверяю сервера региона **{region}**...")

    checker = ServerChecker(
        region_name=region,
        server_count=region_servers[region],
        headless=False,
    )

    clear_region_screenshots(checker.screenshot_dir, region)

    loop = asyncio.get_running_loop()

    try:
        await loop.run_in_executor(None, checker.check_servers)
    except Exception as e:
        logger.exception("Ошибка проверки региона %s", region)
        await channel.send(
            f"❌ Ошибка при проверке **{region}**:\n```{e}```"
        )
        return

    if not os.path.isdir(checker.screenshot_dir):
        await channel.send(
            f"❌ Папка `{checker.screenshot_dir}` не найдена."
        )
        return

    await channel.send(
        "✅ Проверка завершена. Отправляю все скриншоты одним сообщением..."
    )

    try:
        await send_region_screenshots(
            channel,
            checker.screenshot_dir,
            region,
        )
    except Exception as e:
        logger.exception("Ошибка отправки скриншотов региона %s", region)
        await channel.send(
            f"❌ Не удалось отправить скриншоты **{region}**:\n```{e}```"
        )
        return

    await channel.send(
        f"✅ Регион **{region}** полностью обработан."
    )


async def queue_worker():
    global current_region

    await bot.wait_until_ready()
    logger.info("Discord queue worker запущен.")

    while not bot.is_closed():
        channel, region = await check_queue.get()
        current_region = region

        try:
            await run_check_and_send(channel, region)
        except Exception:
            logger.exception("Ошибка queue worker")
        finally:
            current_region = None
            check_queue.task_done()


class RegionButton(discord.ui.Button):
    def __init__(self, region: str):
        super().__init__(
            label=region,
            style=discord.ButtonStyle.primary,
        )
        self.region = region

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"➕ **{self.region}** добавлен в очередь.",
            ephemeral=True,
        )
        await add_to_queue(interaction.channel, self.region)


class RegionView(discord.ui.View):
    def __init__(self, group_name: str):
        super().__init__(timeout=300)

        for region in REGION_GROUPS.get(group_name, []):
            self.add_item(RegionButton(region))


class GroupButton(discord.ui.Button):
    def __init__(self, group_name: str):
        super().__init__(
            label=group_name,
            style=discord.ButtonStyle.secondary,
        )
        self.group_name = group_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Выбери регион из **{self.group_name}**:",
            view=RegionView(self.group_name),
            ephemeral=True,
        )


class GroupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

        for group_name in REGION_GROUPS:
            self.add_item(GroupButton(group_name))


@bot.command()
async def servers(ctx):
    await ctx.send(
        "🌍 Выбери группу серверов:",
        view=GroupView(),
    )


@bot.command()
async def check(ctx, *, region: str):
    region = region.title()

    if region not in region_servers:
        await ctx.send(f"❌ Регион `{region}` не найден.")
        return

    await add_to_queue(ctx.channel, region)


@bot.command()
async def queue(ctx):
    await ctx.send(
        f"🔄 Сейчас: **{current_region or 'ничего'}**\n"
        f"⏳ В очереди: **{check_queue.qsize()}**"
    )


@bot.event
async def on_ready():
    logger.info("Discord bot logged in as %s", bot.user)


async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("Не задан DISCORD_BOT_TOKEN")

    async with bot:
        asyncio.create_task(queue_worker())
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
