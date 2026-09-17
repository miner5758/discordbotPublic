import logging
import os

import discord
from discord.ext import commands

from sheets_cog import SheetsCog

log = logging.getLogger(__name__)


class OpportunitiesBot(commands.Bot):

    async def setup_hook(self):
        # Not on_ready: that fires again after every gateway reconnect, and add_cog
        # raises on the second call.
        await self.add_cog(SheetsCog(self))


def start_discord_bot():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    for name in ("discordtok", "gemkey"):
        if not os.getenv(name):
            raise RuntimeError(f"{name} is not set - check src/resources/file.env")

    intents = discord.Intents.default()
    intents.message_content = True

    bot = OpportunitiesBot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)

    bot.run(os.getenv("discordtok"), log_handler=None)
