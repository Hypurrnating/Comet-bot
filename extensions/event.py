import discord
import discord.ext
import discord.ext.commands
from discord import Interaction, app_commands
import asyncio

class event_cog(discord.ext.commands.Cog):
    def __init__(self, bot: discord.ext.commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    event_group = discord.app_commands.Group(name='event', description='Commands that help you manage sessions')

    async def progress_bar(self, percent: int) -> str:
        if percent > 100:
            done = 25
        else:
            done = int(percent/4)
        progress_bar = f'```| {'|' * done}{' ' * (25 - done)} |```'
        return progress_bar 


async def setup(bot):
    await bot.add_cog(event_cog(bot))
