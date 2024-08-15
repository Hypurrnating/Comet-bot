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
import sys
import os
import datetime
import json
import sorcery
from sorcery import dict_of

sys.path.insert(0, '..')
import main as donut
from discord.utils import MISSING

class event_cog(discord.ext.commands.Cog):
    def __init__(self, bot: donut.Donut) -> None:
        self.bot = bot
        super().__init__()
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Create from message', callback=self.create_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='End this event', callback=self.end_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Edit this event', callback=self.edit_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Lock this event', callback=self.lock_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Start this event', callback=self.start_event_ctx))
        self.bot.tree.add_command(app_commands.ContextMenu(
            name='Add as co-host to event', callback=self.add_cohost_event_ctx))
        
        for event in bot.redis.hgetall('events').values():
            event = json.loads(event)
            view = self._event_announcement_view(event_id=event['id'])
            bot.add_view(view)

    event_group = discord.app_commands.Group(name='event', description='Commands that help you manage sessions')


    class _event_announcement_view(discord.ui.View):
        def __init__(self, *, event_id: int, information_label: str = 'Information', timeout=None):
            self.event_id = event_id
            super().__init__(timeout=timeout)
            self.information.label = information_label
            self.information.custom_id = self.information.custom_id + f'_{event_id}'
            self.action.custom_id = self.action.custom_id + f'_{event_id}'
        
        @discord.ui.button(label='I\'m interested', style=discord.ButtonStyle.green, custom_id='action')
        async def action(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer()
            event = await interaction.client.get_event(self.event_id)
            event['interested'][interaction.user.id] = dict(name = interaction.user.display_name,
                                                            username = interaction.user.global_name,
                                                            avatar_url = interaction.user.display_avatar.url)
        
        @discord.ui.button(style=discord.ButtonStyle.gray, custom_id = 'information')  # Label is handled by init
        async def information(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True, thinking=True)
            event = await interaction.client.get_event(self.event_id)
            msg = f"This is an event hosted by the server (using {interaction.client.user.mention}). "\
            "If you are interested in this event, you can press the button on the left and wait for it start. "\
            "Sometimes event managers might be waiting for enough people to become interested before starting. "\
            "Pressing that button will help them choose whether they should start the event or not. " + "\n\n" + event['FAQ']['information']

            view = discord.ui.View(timeout=None)
            for butt in event['FAQ']['buttons'].keys():
                button = discord.ui.Button(label=butt,
                                           style = discord.ButtonStyle.url,
                                           url=event['FAQ']['buttons'][butt])
                view.add_item(button)
            await interaction.followup.send(content=msg,
                                            view=view,
                                            username=event['Webhook']['webhook_name'] or interaction.guild.name,
                                            avatar_url=event['Webhook']['webhook_avatar_url'] or interaction.guild.icon.url)


    class _create_event_param_view(discord.ui.View):
        def __init__(self, *, config: dict = None, timeout=None):
            self.message = None
            self.config = config
            
            self.param_resp = None
            self.url_resp = None
            super().__init__(timeout=timeout)
            if not  self.config.get('Parameters'):
                self.params.disabled = True
                self.params.style = discord.ButtonStyle.gray
                self.param_resp = True

        @discord.ui.button(label='Enter Event URL', style=discord.ButtonStyle.blurple)
        async def url(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Create modal 
            modal = discord.ui.Modal(title='Enter Event URL', timeout=None)
            modal.add_item(discord.ui.TextInput(label='URL', 
                                                style=discord.TextStyle.long, 
                                                required=True))
            async def _on_submit(interaction: discord.Interaction):
                await interaction.response.defer()
            modal.on_submit = _on_submit

            await interaction.response.send_modal(modal)
            await modal.wait()
            self.url_resp = modal.children[0].value
            if not validators.url(self.url_resp):
                button.style = discord.ButtonStyle.red
                self.url_resp = None
            else:
                button.style = discord.ButtonStyle.gray
            if self.url_resp and self.param_resp:
                self.stop()
                return
            await self.message.edit(view=self)

        @discord.ui.button(label='Fill parameters', style=discord.ButtonStyle.blurple)
        async def params(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Create modal
            modal = discord.ui.Modal(title='Fill parameters', timeout=None)
            for param in self.config['Parameters'].keys():
                modal.add_item(discord.ui.TextInput(label=param,
                                                    placeholder=self.config['Parameters'][param]['hint'],
                                                    required=self.config['Parameters'][param]['required'],
                                                    style=discord.TextStyle.long))
                async def _on_submit(interaction: discord.Interaction):
                    await interaction.response.defer()
                modal.on_submit = _on_submit

            await interaction.response.send_modal(modal)
            await modal.wait()
            self.param_resp = dict()
            for child in modal.children:
                self.param_resp[child.label] = child.value
            button.style = discord.ButtonStyle.gray
            if self.url_resp and self.param_resp:
                self.stop()
                return
            await self.message.edit(view=self)


    async def _create_event(self, interaction: discord.Interaction, config: dict):
        channel = interaction.guild.get_channel(config['Webhook']['event_channel_id']) or await interaction.guild.fetch_channel(config['Webhook']['event_channel_id'])
        webhook = await self.bot.grab_webhook(channel)
        config['interested'] = dict()

        view = self._create_event_param_view(config=config)
        msg: discord.WebhookMessage = await interaction.followup.send(f'', view=view)
        view.message = msg
        await view.wait()
        await msg.edit(content='<a:HourGlass:1273332047276150826>', view=None)
        config['params'] = view.param_resp
        config['join_url'] = view.url_resp

        embed = discord.Embed(title=config['Configuration']['title'],
                              description=config['Configuration']['description'])
        if config.get('Parameters'):
            for param in config['params'].keys():
                embed.add_field(name=param, value=config['params'][param])
        
        # We send the announcement message without the embed/view at first because we need to set the message id and event id
        announcement = await webhook.send(content=f'-# Event Announcement',
                                          wait=True,
                                          username=config['Webhook']['webhook_name'] or interaction.guild.name,
                                          avatar_url=config['Webhook']['webhook_avatar_url'] or interaction.guild.icon.url)
        config['announcement'] = announcement.id
        config['id'] = announcement.id

        view = self._event_announcement_view(event_id=config['id'], information_label=config['FAQ']['label'])

        announcement = await webhook.edit_message(announcement.id,
                                                  embed=embed,
                                                  view=view)
        try:
            await self.bot.set_event(config)
        except Exception as exception:
            await announcement.delete()
            raise exception
        await msg.edit(content=f'Announced!', view=None)


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
        return toml

    @app_commands.guild_only()
    @app_commands.checks.has_permissions(create_events = True, manage_events = True)
    async def create_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
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
        await self._create_event(interaction, config)

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
    async def start_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)
        #if (not message.author == self.bot.user.id) or (not message.embeds):
        #    await interaction.followup.send(f'This is not a {self.bot.user.mention} event.')
        #    return
        
        event = await interaction.client.get_event(message.id)
        if not type(event) == dict: # idfk what redispy returns on fail
            await interaction.followup.send(f'This is an invalid event (i.e. expired).')
            return
        
        view = self._event_announcement_view(event_id=event['id'], information_label=event['FAQ']['label'])
        action_button: discord.ui.Button = [button for button in view.children if button.custom_id == f'action_{event['id']}'][0]
        action_button.label = 'Join Event'
        action_button.style = discord.ButtonStyle.url
        action_button.custom_id = None
        action_button.url = event['join_url']
        webhook = await self.bot.grab_webhook(message.channel)
        await webhook.edit_message(message_id=message.id, view=view)
        await interaction.followup.send(f'Started')


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




async def setup(bot: donut.Donut):
    await bot.add_cog(event_cog(bot))
