import discord
import discord.ext
import discord.ext.commands
from discord import Interaction, app_commands
import asyncio

class bell_cog(discord.ext.commands.Cog):
    def __init__(self, bot: discord.ext.commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    bell_group = discord.app_commands.Group(name='bell', description='Bells are messages that allow users to "bump" up a bar and trigger an action')

    async def progress_bar(self, percent: int) -> str:
        if percent > 100:
            done = 25
        else:
            done = int(percent/4)
        progress_bar = f'```| {'|' * done}{' ' * (25 - done)} |```'
        return progress_bar 

    @bell_group.command(name='bar')
    async def bell_bar(self, interaction: discord.Interaction, percent: int):
        await interaction.response.send_message(content=await self.progress_bar(percent))


async def setup(bot):
    await bot.add_cog(bell_cog(bot))
