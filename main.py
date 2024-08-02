import aiosqlite.cursor
import discord
import discord.ext.commands  # Doesn't generate the docs if you dont import this
import asyncpg
import aiosqlite
import logging
import os
import platform
import pathlib
import asyncio
from multiprocessing.connection import Listener
from datetime import datetime
from dotenv import load_dotenv
import quart
from quart import Quart, Response, jsonify, request, session, redirect, url_for, render_template, render_template_string, Markup, websocket


load_dotenv()

class Donut(discord.ext.commands.Bot):
    def __init__(self, **options):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(description='Donut :3',
                         command_prefix=discord.ext.commands.when_mentioned,
                         intents=intents, **options)

        self.bot = self     # Lets me use both `self` and `self.bot` in functions
        self.quart = self.QuartWeb(self)
        discord.utils.setup_logging(level=logging.INFO)
        logging.getLogger('discord.gateway').setLevel(30)   # Stops a flood of "gate RESUMED" messages

        self.webhooks = dict()
        self.errors = self.errors()
        asyncio.create_task(self.setup_db())

        for x in pathlib.Path(f'./extensions').iterdir():
            if x.is_file():
                asyncio.create_task(self.load_extension(f'extensions.{x.name.split(".")[0]}'))

    def get_db_loc(self):
        print(f'Running on: {platform.system()}')
        if platform.system() == 'Windows':
            return '.db'
        if platform.system() == 'Linux':
            return '/s/.db'

    async def create_tables(self):
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS channel_webhooks(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id BIGINT, url VARCHAR(1500))')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS guild_starboards(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, added_by BIGINT)')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS stars(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, message_id BIGINT, user_id BIGINT)')

    async def setup_db(self):
        self.sqlite = await aiosqlite.connect(self.get_db_loc())
        await self.create_tables()

    async def on_ready(self):
        await self.tree.sync()


    # Below are just custom functions

    class errors():
        def __init__(self) -> None:
            
            class WebhookError(Exception):
                """Exception for whenever there is an error relating managing webhooks"""
                pass
            self.WebhookError = WebhookError
    

    async def is_bot_webhook(self, webhook: discord.Webhook) -> bool:
        """Check if the webhook is created by THIS bot

        Args:
            webhook (discord.Webhook): The webhook to check
        """
        if webhook.is_partial():
            webhook = await webhook.fetch()
        
        if not webhook.type.name == 'application':
            return False
        
        if not webhook.user == self.user:
            return False
        
        return True

    async def cache_channel_webhook(self, channel: discord.TextChannel, webhook: discord.Webhook = None):
        bot_webhook = webhook if webhook else (bot.webhooks[channel.id] if bot.webhooks.get(channel.id) else None)
        if not bot_webhook:
            raise Exception('No webhook passed, and none in channel attribute')

        resp = await (await self.sqlite.cursor()).execute("SELECT * FROM channel_webhooks WHERE channel_id = ?", 
                                                            (channel.id,))

        if resp:
            await (await self.sqlite.cursor()).execute("UPDATE channel_webhooks SET url = ? WHERE channel_id = ?",
                                                (bot_webhook.url,
                                                channel.id))
            
        if not resp:
            await (await self.sqlite.cursor()).execute("INSERT INTO channel_webhooks(channel_id, url) VALUES (?, ?)",
                                                        (channel.id,
                                                            bot_webhook.url))
        
        await self.sqlite.commit()

    async def grab_channel_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """

        Args:
            channel (discord.TextChannel): _description_

        Returns:
            discord.Webhook: _description_
        """
        bot_webhook = None

        # This checks if a webhook has been assigned to a channel already
        if self.webhooks.get(channel.id):
            return self.webhooks[channel.id]
        
        else:
            # get a cached webhook url from sqlite
            resp = await (await (await self.sqlite.cursor()).execute("SELECT * FROM channel_webhooks WHERE channel_id = ?", (channel.id,))).fetchone()

            # if it does exist in sqlite cache then create the partial webhook, and then create the complete one by .fetch()
            if resp:
                bot_webhook = await (discord.Webhook.from_url(resp['url'])).fetch()

            # if it doesn't exist in sqlite cache then fetch all webhooks in channel, if found use it and cache it, if not found create one and cache it.
            if not resp: 
                for webhook in (await channel.webhooks()):
                    # check if it has 'state attached' and is the bots webhook
                    if await self.is_bot_webhook(webhook):
                        bot_webhook = webhook
                
                if not bot_webhook:
                    async with self.psql.acquire() as connection:
                        guild_settings = await connection.fetch("SELECT * FROM webhook_configs WHERE guild_id = $1", int(channel.guild.id))
                    if not guild_settings: 
                        raise self.errors.WebhookError('Guild is not registered with any configuration')
                    guild_settings = dict(guild_settings[0])
                    bot_webhook = await channel.create_webhook(name=guild_settings['name'], avatar=guild_settings['avatar'])
                await self.cache_channel_webhook(channel, bot_webhook)
            
            # assign webhook object to channel for ease and then return it 
            self.webhooks[channel.id] = bot_webhook
        return self.webhooks[channel.id]

    async def delete_guild_webhooks(self, guild: discord.Guild, reason: str = None):
        for webhook in (await guild.webhooks()):
            if not await self.is_bot_webhook():
                continue
            else:
                await webhook.delete(reason=reason)

    async def progress_bar(self, percent: int) -> str:
        if percent > 100:
            done = 25
        else:
            done = int(percent/4)
        progress_bar = f'```| {"|" * done}{" " * (25 - done)} |```'
        return progress_bar


    class QuartWeb():
        def __init__(self, bot):
            self.bot: discord.ext.commands.bot = bot
            self.host = '0.0.0.0'
            self.port = int(os.environ.get('PORT', default=8080))
            self.app = Quart(__name__)
            self.app.config['SESSION_TYPE'] = 'sederunt'
            self.app.config['SECRET_KEY'] = 'sdrnt00123'

            self.setup_routes()

        async def run(self):
            await self.app.run_task(host=self.host,
                                    port=self.port,
                                    debug=True)
        
        def setup_routes(self):
            
            @self.app.route('/event/<int:guild_id>/<int:event_id>')
            async def _event(guild_id, event_id):
                guild = self.bot.get_guild(guild_id)
                if not guild: return Response(response='Invalid Guild')
                event = guild.get_scheduled_event(event_id)
                if not event: return Response(response='Invalid Event ID')
            


async def main():
    bot = Donut()
    tasks = [bot.quart.run(), bot.start(os.environ.get('TOKEN'))]
    await asyncio.gather(*tasks)
asyncio.run(main())
