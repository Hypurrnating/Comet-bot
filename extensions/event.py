import discord
import discord.ext
import discord.ext.commands
from discord import Interaction, app_commands
import asyncio
import typing
import discord.ext.tasks
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
import logging
from sorcery import dict_of
from datetime import datetime, timedelta, timezone

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
        
        for event_id, event in (bot._get_all_events()).items():
            view = self._event_announcement_view(client=self.bot, event_id=event_id) # Information label is not needed here because this is just for persistance and adding callback.
            bot.add_view(view)
        
        self.event_garbcol_loop.start()

    event_group = discord.app_commands.Group(name='event', description='Commands that help you manage sessions')

    # TODO: Garbage collector for events that timeouts views/expires events if inactive and also if announcement message was deleted
    # One possibility for the garbage collector to detect "dead" events is checking the latest join. If nobody new has joined the 
    # event in, say, 6 hours. Then the event has died. Missing announcement messages mean immediate garbage. Although fetching messages
    # every 30 minutes or so can quickly spiral out of control because thats a lot of api calls. Redis calls are internal anyways.
    # Maybe I can just listen to on_message_delete
    # TODO: Garbage collection should also include VIEWS

    """ Event Garbage Collection """

    # This is the main function which garbages events
    async def garbage_event(self, event_id: int, event: dict, message: discord.Message | bool = None):
        await self.bot.clear_event(event_id)
        if message:
            if isinstance(message, bool):
                channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
                message = channel.get_partial_message(event['announcement_id'])
            try:
                await message.delete()
            except:  # Maybe I  should catch *some* exceptions and not just completely IGNORE what it raised
                pass
        # TODO: Log event

    # This is a listener which will listen for *all* message deletes and check whether they had something to do with an event
    @discord.ext.commands.Cog.listener(name='on_raw_message_delete')
    async def event_garbcol_message_delete(self, payload: discord.RawMessageDeleteEvent):
        # Not a lot of easy sanity checks are possible, so we will just try to make do
        if payload.cached_message:
            if not payload.cached_message.author.bot: 
                return
        # Finally call redis and make absolutely sure that this was an ongoing event, then garbage it.
        event = await self.bot.get_event(payload.message_id)
        if not event:
            return
        await self.garbage_event(payload.message_id, event)
    
    # This is a task which will call all ongoing events and decide if they have died or not, then decide whether to garbage them
    @discord.ext.tasks.loop(minutes=30)
    async def event_garbcol_loop(self):
        print('Ding ding! Garbage collection.')
        garbaged = list() # just a list i use to count how many were garbaged
        for event_id, event in (self.bot._get_all_events()).items():
            interested = await self.bot.get_interested(event_id)
            attendees = await self.bot.get_attendees(event_id)
            interests = [interest['utc'] for interest in interested.values()]
            attends = [attend['utc'] for attend in attendees.values()]
            last_interested = max(interests) if interests else event['utc']
            last_attendee = max(attends) if attends else event['utc']
            last_activity = max([last_interested, last_attendee])
            if (self.bot.now_utc_timestamp - last_activity) > timedelta(hours=6).seconds:
                await self.garbage_event(event_id, event, message=True)
                garbaged.append(event_id)

        logging.info(f'Garbaged {len(garbaged)} events.\n{garbaged}')

    """ Views """
    
    class _event_announcement_view(discord.ui.View):
        def __init__(self, *, client: donut.Donut, event_id: int, information_label: str = 'Information', timeout=None):
            self.event_id = event_id
            self.bot = client
            super().__init__(timeout=timeout)
            self.information.label = information_label
            self.information.custom_id = self.information.custom_id + f'_{event_id}'
            self.action.custom_id = self.action.custom_id + f'_{event_id}'
        
        @discord.ui.button(label='I\'m interested', style=discord.ButtonStyle.green, custom_id='action')
        async def action(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer()
            user_id = interaction.user.id
            user_data = dict(name=interaction.user.display_name,
                             username=interaction.user.global_name,
                             avatar_url=interaction.user.display_avatar.url)
            await interaction.client.add_interested(self.event_id, user_id, user_data)
        
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
        
        async def on_timeout(self) -> None:     # TODO: see if this is useless or not
            event = await self.bot.get_event(self.event_id)
            await self.bot.clear_event(self.event_id)
            channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            message = channel.get_partial_message(event['announcement_id'])
            await message.delete()
            # TODO: Log event on timeout


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


    """ Interactions """

    async def _create_event(self, interaction: discord.Interaction, config: dict):
        for event in (await self.bot.get_all_events()).values():
            if (event['host'] == interaction.user.id) and (event['guild_id'] == interaction.guild.id):
                await interaction.followup.send(f'You have already started an event in this guild.\n Please end it, or wait for at least 6 hours.', ephemeral=True)
                # TODO: Give a button for the user to end their on going meet
                return

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
        config['guild_id'] = interaction.guild_id
        config['channel_id'] = interaction.channel_id
        # announcement and message are interchangeable
        config['announcement_id'] = announcement.id
        config['message_id'] = announcement.id
        config['id'] = announcement.id
        config['host'] = interaction.user.id
        config['utc'] = self.bot.now_utc_timestamp
        config['locked'] = False
        config['started'] = False
        config['co_hosts'] = list()

        view = self._event_announcement_view(client=self.bot, event_id=config['id'], information_label=config['FAQ']['label'])

        announcement = await webhook.edit_message(announcement.id,
                                                  embed=embed,
                                                  view=view)
        try:
            await self.bot.set_event(config)
        except Exception as exception:
            await announcement.delete()
            raise exception
        await msg.edit(content=f'Announced! {announcement.jump_url}', view=None)


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
    async def end_event_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)
        # TODO: validate whether message is event here
        event = await interaction.client.get_event(message.id)
        if not type(event) == dict:  # idfk what redispy returns on fail
            await interaction.followup.send(f'This is an invalid event (i.e. expired).')
            return
        
        await interaction.client.clear_event(event['id'])
        await message.delete()
        await interaction.followup.send('Cleared!') # TODO: log in channel

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
        # TODO: validate whether message is event here
        event = await interaction.client.get_event(message.id)
        if not type(event) == dict: # idfk what redispy returns on fail
            await interaction.followup.send(f'This is an invalid event (i.e. expired).')
            return
        
        view = self._event_announcement_view(client=self.bot, event_id=event['id'], information_label=event['FAQ']['label'])
        action_button: discord.ui.Button = [button for button in view.children if button.custom_id == f'action_{event['id']}'][0]
        action_button.label = 'Join Event'
        action_button.style = discord.ButtonStyle.url
        action_button.custom_id = None
        action_button.url = event['join_url']
        webhook = await self.bot.grab_webhook(message.channel)
        await webhook.edit_message(message_id=message.id, view=view)
        await interaction.followup.send(f'Started')
        # TODO: register as started in redis cache too

        for user_id, user_data in (await self.bot.get_interested(event_id=event['id'])).items():
            member = message.guild.get_member(user_id) or await message.guild.fetch_member(user_id)
            try:
                await member.send(content=f'An event that you showed interest for has started. {message.jump_url}')
            except:
                pass


    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_events=True)
    async def add_cohost_event_ctx(self, interaction: discord.Interaction, member: discord.Member):
        """ Co hosts are a log thing only. They do not get special privileges. """
        await interaction.response.defer(ephemeral=True, thinking=True)

        event = None
        for _event in (await self.bot.get_all_events()).values():
            if (_event['host'] == interaction.user.id) and (_event['guild_id'] == interaction.guild.id):
                event = _event
                break
        if not event:
            await interaction.followup.send('You dont have any active meets in this guild')
            return
        event['co_hosts'].append(member.id)
        await self.bot.set_event(event)
        await interaction.followup.send(f'Added {member.mention} to the co hosts!\n'
                                        '-# Keep in mind that co hosts are purely for organization and logging, '
                                        'and the member has not been granted any special permissions.')


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
