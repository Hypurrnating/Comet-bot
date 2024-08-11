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
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Start from message', callback=self.start_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='End this event', callback=self.end_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Edit this event', callback=self.edit_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Lock this event', callback=self.lock_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Co-host this event', callback=self.cohost_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Add as co-host to event', callback=self.add_cohost_event_ctx))

    event_group = discord.app_commands.Group(name='event', description='Commands that help you manage sessions')

    async def preprocess_toml(self, toml: str) -> str:
        # Process titles
        for line in toml.splitlines():
            pattern = re.compile('^\\[.+\\]')
            tables = re.findall(pattern, line)
            if not tables:
                continue 
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
        print(toml)
        return toml

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(create_events = True, manage_events = True)
    async def start_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        if not isinstance(message.author, discord.Member):
            message.author = message.guild.get_member(message.author.id) if message.guild.get_member(message.author.id) else await message.guild.fetch_member(message.author.id)
        if not message.author.guild_permissions.create_events:
            await interaction.followup.send(content=f'The author of the template must have `create_events` permission.')
            return
        
        pattern = re.compile(r'```toml.*```', re.DOTALL)
        tomls = re.findall(pattern, message.content)
        if not tomls or len(tomls) > 1:
            await interaction.followup.send(content=f'Could not detect a template in this message.'); return
        toml = await self.preprocess_toml(tomls[0].replace('```toml', '').replace('```', '').strip())
        try:
            config = tomllib.loads(toml)
        except Exception as exception:
            await interaction.followup.send(content=f'Ran into an error parsing the config:\n`{exception}`\n[Tools like this one can help fix that](https://www.toml-lint.com/)')
            return
        await interaction.followup.send(config)

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_events=True)
    async def end_event_ctx(self, interaction: discord.Interaction, message:discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_events=True)
    async def edit_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_events=True)
    async def lock_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_events=True)
    async def cohost_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_events=True)
    async def add_cohost_event_ctx(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True, thinking=True)


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
