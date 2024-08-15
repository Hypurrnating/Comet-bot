import discord
import discord.ext.commands  # Doesn't generate the docs if you dont import this
import asyncpg
import redis
import logging
import os
import platform
import pathlib
import asyncio
import typing
import traceback
import json
from multiprocessing.connection import Listener
from datetime import datetime
from dotenv import load_dotenv
import quart
from quart import Quart, Response, jsonify, request, session, redirect, url_for, render_template, render_template_string, Markup, websocket
import redis.client
import redis.connection

load_dotenv()

class Donut(discord.ext.commands.Bot):
    def __init__(self, **options):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(description='Donut :3',
                         command_prefix=discord.ext.commands.when_mentioned,
                         intents=intents, **options)
        self.bot = self
        self.quart = self.QuartWeb(self)
        self.tree.on_error = self._on_tree_error
        self.errors = self.errors()
        self.redis: redis.client.Redis = None
        self.psql: asyncpg.Pool = None
        discord.utils.setup_logging(level=logging.INFO)
        logging.getLogger('discord.gateway').setLevel(30)   # Stops a flood of "gate RESUMED" messages      


    async def load_extensions(self):
        for x in pathlib.Path(f'./extensions').iterdir():
            if x.is_file():
                if not x.name in ['starboard.py']:
                    await self.load_extension(f'extensions.{x.name.split(".")[0]}')
        if platform.system == 'Windows':    # Host is usually Linux, so this would mean its being run on my local machine
            await self.load_extension('jishaku')


    async def create_tables(self):
        # CREATE TABLE IF NOT EXISTS channel_webhooks(id SERIAL PRIMARY KEY, channel_id BIGINT, url VARCHAR(1500))
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS channel_webhooks(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id BIGINT, url VARCHAR(1500))')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS guild_starboards(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, added_by BIGINT)')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS stars(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, message_id BIGINT, user_id BIGINT)')
        #await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, )')


    async def on_ready(self):
        await self.tree.sync()

    async def _on_tree_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        await interaction.followup.send(f'Ran into an error :/\n```{error}```', ephemeral=True)
        traceback.print_exception(error)
        logging.error(error)

    class errors():
        def __init__(self) -> None:
            pass
            
        class WebhookError(discord.DiscordException):
            """Exception for whenever there is an error relating managing webhooks"""
            pass

        class EventError(discord.DiscordException):
            """ """
            pass
              

    async def set_event(self, event: dict) -> None:
        events = json.dumps(event)
        self.redis.hset(name='events', key=f'event_{event['id']}', value=events)

    async def get_event(self, event_id: int) -> dict | None:
        resp = self.redis.hget(name='events', key=f'event_{event_id}')
        try:
            event = json.loads(resp)
        except:
            return None
        return event

    async def clear_event(self, event_id: int) -> None:
        event = self.get_event(event_id)
        self.redis.hdel('events', event_id)
        self.redis.delete(f'interested_{event_id}')
        self.redis.delete(f'attendees_{event_id}')

        webhook: discord.Webhook = await self.bot.grab_webhook(event['Webhook']['event_channel_id '])
        message = await webhook.fetch_message(event['announcement'])
        await message.delete()

    async def add_interested(self, event_id: int, user_id: int, user_data: dict) -> None:
        self.redis.hset(f'interested_{event_id}', user_id, json.loads(user_data))

    async def get_interested(self, event_id: id) -> dict | None:
        resp = self.redis.hgetall(f'interested_{event_id}')
        interested = dict()
        for key, value in resp.items():
            interested[key] = json.loads(value)
        return interested
    
    async def add_attendee(self, event_id: int, user_id: int, user_data: dict) -> None:
        self.redis.hset(f'attendees_{event_id}', user_id, user_data)

    async def get_attendees(self, event_id: id) -> dict | None:
        resp = self.redis.hgetall(f'attendees_{event_id}')
        attendees = dict()
        for key, value in resp.items():
            attendees[key] = json.loads(value)
        return attendees

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
            raise self.errors.WebhookError('Channel is not a text channel') 
        webhook = None

        async with self.bot.psql.acquire() as connection:
            resp = await connection.fetchrow(f'SELECT * FROM channel_webhooks WHERE channel_id = $1', int(channel.id))
        if resp:
            webhook = discord.Webhook.from_url(resp['url'], client=self.bot)
            try:
                await webhook.fetch()
            except discord.NotFound:
                webhook = None
                async with self.bot.psql.acquire() as connection:
                    await connection.execute(f'DELETE FROM channel_webhooks WHERE channel_id = $1', int(channel.id))
        if webhook:
            if not await self.is_bot_webhook(webhook):    # Kinda useless line but oh well
                async with self.bot.psql.acquire() as connection:
                    await connection.execute(f'DELETE FROM channel_webhooks WHERE channel_id = $1', int(channel.id))
        
        if not webhook:
            for webhook in await channel.webhooks():
                if await self.is_bot_webhook(webhook):
                    # TODO: Store in pg db
                    webhook = webhook
        if not webhook:
            webhook = await channel.create_webhook(name=self.user.name, avatar=await self.user.avatar.read())
            async with self.bot.psql.acquire() as connection:
                await connection.execute(f'INSERT INTO channel_webhooks(channel_id, url) VALUES ($1, $2)', int(channel.id), str(webhook.url))

        return webhook

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

            @self.app.route('/upcheck')
            async def upcheck():
                return Response(response='Hello!', status=200)
            
            @self.app.route('/event_inspect')
            async def _eventinspect():
                args = request.args
                guild_id = args.get('guild_id')
                event_id = args.get('event_id')
                title = args.get('title')

                if not self.bot.get_guild(guild_id):
                    return Response(status=404, response='{"reason": "Invalid Guild ID"}', content_type='application/json')
                guild = self.bot.get_guild(guild_id)
                
                # then find the event and handle that

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
        await bot.load_extensions() # I load extensions after connecting to dbs cause some functions depend on that
        tasks = [bot.quart.run(), bot.start(os.environ.get('TOKEN'))]
        await asyncio.gather(*tasks)
if __name__ == '__main__':
    asyncio.run(main())
