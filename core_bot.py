# core_bot.py
import discord
import os
from discord.ext import commands
from sheets_cog import SheetsCog

def start_discord_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="opportunities", intents=intents)

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        await bot.add_cog(SheetsCog(bot))
        
    print(os.getenv("discordtok"))  # Debugging line to check if token is loaded
    bot.run(os.getenv("discordtok"))
