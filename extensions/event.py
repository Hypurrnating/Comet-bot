import discord
import discord.ext
import discord.ext.commands
from discord import Interaction, app_commands
import asyncio
import typing
import validators
import urllib
import urllib.parse
import re
import tomllib

from discord.utils import MISSING

class event_cog(discord.ext.commands.Cog):
    def __init__(self, bot: discord.ext.commands.Bot) -> None:
        self.bot = bot
        super().__init__()
        self.bot.tree.add_command(app_commands.ContextMenu(name='Start from message', callback=self.start_event_ctx))

    event_group = discord.app_commands.Group(name='event', description='Commands that help you manage sessions')

    async def preprocess_toml(toml: str) -> str:
        # Process titles
        pattern = re.compile('\\[.+\\]')
        tables = re.findall(pattern, toml)
        if not tables:
            return # Because there needs to be at least one table
        for table in tables:
            # Check if the title isn't already wrapped in quotes
            pattern = re.compile('\\[".+"\\]')
            check = re.search(pattern, table)
            if check: 
                continue
            # Wrap it in quotes
            pattern = re.compile('[a-zA-Z0-9_\\s\\.-]+')
            _title = re.search(pattern, table).group()
            title_ = f'"{_title}"'
            toml = toml.replace(_title, title_)

        # Process bools
        pattern = re.compile(r'.+\s*=\s*true|.+\s*=\s*false', re.IGNORECASE)
        bools = re.findall(pattern, toml)
        for bool in bools:
            pattern = re.compile('true|false', re.IGNORECASE)
            _bool = re.search(pattern, bool).group()
            bool_ = pattern.sub(_bool.lower(), bool)
            toml = toml.replace(bool, bool_)
        return toml

    @app_commands.guild_only()
    async def start_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)
        pattern = re.compile(r'```toml.*```', re.DOTALL)
        tomls = re.findall(pattern, message.content)
        if not tomls:
            await interaction.followup.send(content=f'This message either doesnt contain any templates, or isnt formatted properly.'); return
        toml = await self.preprocess_toml(tomls[0].replace('```toml', '').replace('```', ''))
        try:
            config = tomllib.loads(toml)
        except Exception as exception:
            await interaction.followup.send(content=f'Ran into an error parsing the config:\n{exception}')
        await interaction.followup.send(config)
        

    @event_group.command(name='new',
                                  description='Start a new event')
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
