import discord
import discord.ext
import discord.ext.commands
from discord import Interaction, app_commands
import asyncio
import typing
import validators
import urllib
import urllib.parse

from discord.utils import MISSING

class event_cog(discord.ext.commands.Cog):
    def __init__(self, bot: discord.ext.commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    def build_internal_join_url(self, guild_id: int, event_id: int, event_title: str = None):
        return f'https://donut.imady.pro/event/{event_title}/{guild_id}/{event_id}'

    event_group = discord.app_commands.Group(name='event', description='Commands that help you manage sessions')

    @discord.app_commands.command(name='new',
                                  description='Start a new event', 
                                  extras=dict())
    @discord.app_commands.describe(title='Title of the event.',
                                   description='What is this event about?',
                                   post_to='Where should the event be announced?',
                                   use_discord_event='Whether or not a discord event should be started alongside')
    async def event_new(self, interaction: discord.Interaction,
                        title: str,
                        description: str,
                        type: typing.Literal['URL Join', 'Instructions'],
                        post_to: discord.TextChannel,
                        thumbnail: discord.Attachment = None,
                        use_discord_event: bool = True,
                        ):
        modal = self.event_instructions_modal(title='Now tell users how to join', type=type)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if not modal._join.value: return
        if modal._join.value == 'URL Join':
            if not validators.url(modal._join.value):
                await interaction.followup.send(f'The URL you provided is invalid: {modal._join.value}')
        
        url_safe_title = urllib.parse.quote(title.replace(' ', '_'))
        internal_join_url = self.build_internal_join_url(guild_id=interaction.guild.id, event_id=interaction.id, event_title=url_safe_title)
        

    class event_instructions_modal(discord.ui.Modal):
        def __init__(self, title: str, type: typing.Literal['URL Join', 'Instructions'], timeout: float | None = None, custom_id: str = None) -> None:
            if type == 'URL Join':
                _join = discord.ui.TextInput(label='Enter URL', style=discord.TextStyle.short)
            elif type == 'Instructions':
                _join = discord.ui.TextInput(label='Enter join instructions', style=discord.TextStyle.long)

            super().__init__(title=title, timeout=timeout, custom_id=custom_id)
        
        async def on_submit(self, interaction: Interaction) -> None:
            await interaction.response.defer()




async def setup(bot):
    await bot.add_cog(event_cog(bot))
