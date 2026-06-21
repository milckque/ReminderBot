import asyncio
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import init_db
from cogs.reminders import RemindersCog

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    cog = bot.get_cog("RemindersCog")
    if cog:
        cog.restore_jobs()
    scheduler.start()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set in environment or .env file")

    init_db()
    async with bot:
        await bot.add_cog(RemindersCog(bot, scheduler))
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
