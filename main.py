import aiosqlite.cursor
import discord
import discord.ext.commands  # Doesn't generate the docs if you dont import this
import asyncpg
import redis
import aiosqlite
import logging
import os
import platform
import pathlib
import asyncio
import typing
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
        self.webhooks = dict()
        self.errors = self.errors()
        discord.utils.setup_logging(level=logging.INFO)
        logging.getLogger('discord.gateway').setLevel(30)   # Stops a flood of "gate RESUMED" messages      

        for x in pathlib.Path(f'./extensions').iterdir():
            if x.is_file():
                asyncio.create_task(self.load_extension(f'extensions.{x.name.split(".")[0]}'))


    async def create_tables(self):
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS channel_webhooks(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id BIGINT, url VARCHAR(1500))')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS guild_starboards(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, added_by BIGINT)')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS stars(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, message_id BIGINT, user_id BIGINT)')
        #await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, )')


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

    async def grab_webhook(self, channel: discord.TextChannel) -> discord.Webhook | None:
        if not isinstance(channel, discord.TextChannel):
            return

        channel_webhooks = await channel.webhooks()
        for webhook in channel_webhooks:
            if await self.is_bot_webhook(webhook):
                return webhook

        return await channel.create_webhook(name=self.user.name, avatar=await self.user.avatar.read())

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

            @self.app.route('/')
            async def _():
                with open('./main.html', 'r') as file:
                    return Response(file.read(), content_type='text/html')
                
            async def _event(self, **kwargs):
                guild = self.bot.get_guild(kwargs['guild_id'])
                if not guild:
                    return Response(status=400, response='Invalid Guild', mimetype='application/json')
                event = await (await self.bot.sqlite.execute('SELECT * FROM events WHERE guild_id = ? AND event_id = ?')).fetchone()
                guild_event = guild.get_scheduled_event(kwargs['event_id'])
                if not event or guild_event:
                    return Response(status=400, response='Invalid Event', mimetype='application/json')

                if request.args.get('data_only').lower() == 'true':
                    pass
                
                if kwargs['title']:
                    if not kwargs['title'] == event[1]: # the title
                        return redirect(location=request.url.replace(kwargs['title'], event[1]))
            
            @self.app.route('/event/<int:guild_id>/<int:event_id>')
            async def _event1(guild_id, event_id):
                await _event(guild_id=guild_id, event_id=event_id)
            @self.app.route('/event/<string:title>/<int:guild_id>/<int:event_id>')
            async def _event2(title, guild_id, event_id):
                await _event(title=title, guild_id=guild_id, event_id=event_id)
            

async def main():
    bot = Donut()
    _redis = redis.Redis(host=os.environ.get('REDISHOST'),
                         port=os.environ.get('REDISPORT'),
                         password=os.environ.get('REDISPASSWORD'),
                         username=os.environ.get('REDISUSER'),
                         decode_responses=True)
    async with asyncpg.create_pool(database=os.environ.get('PGDATABASE'),
                                   host=os.environ.get('PGHOST'),
                                   user=os.environ.get('PGUSER'),
                                   password=os.environ.get('PGPASSWORD'),
                                   port=os.environ.get('PGPORT')) as psql:
        bot.psql = psql
        bot.redis = _redis
        tasks = [bot.quart.run(), bot.start(os.environ.get('TOKEN'))]
        await asyncio.gather(*tasks)
asyncio.run(main())
