import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())


@bot.event
async def on_ready():
    print(f'{bot.user} is ready!', flush=True)

if __name__ == "__main__":
    bot.load_extension("commands")
    bot.load_extension("periodic_tasks")

bot.run(TOKEN)
