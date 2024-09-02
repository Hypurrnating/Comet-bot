import discord
import discord.ext.commands  # Doesn't generate the docs if you dont import this
import discord.ext.tasks
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
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import quart
from quart import Quart, Response, jsonify, request, session, redirect, url_for, render_template, render_template_string, Markup, websocket
import redis.client
import redis.connection

load_dotenv()

class Donut(discord.ext.commands.Bot):
    def __init__(self, **options):
        intents = discord.Intents.default()
        intents.messages = True
        super().__init__(description='Donut :3',
                         command_prefix=discord.ext.commands.when_mentioned,
                         intents=intents,
                         owner_id=1226476776683868241
                         , **options)
        self.bot = self
        self.setup_ctx_commands()
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
                await self.load_extension(f'extensions.{x.name.split(".")[0]}')
        if platform.system() == 'Windows':    # Host is usually Linux, so this would mean its being run on my local machine
            await self.load_extension('jishaku')
            logging.info('Loaded jishaku')


    async def create_tables(self):
        # CREATE TABLE IF NOT EXISTS channel_webhooks(id SERIAL PRIMARY KEY, channel_id BIGINT, url VARCHAR(1500))
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS channel_webhooks(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id BIGINT, url VARCHAR(1500))')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS guild_starboards(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, added_by BIGINT)')
        await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS stars(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, message_id BIGINT, user_id BIGINT)')
        #await (await self.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, )')


    def setup_ctx_commands(self):
        @discord.ext.tasks.loop(hours=12)
        async def update_subscriptions():
            donut_guild = await self.fetch_guild('1275039951439794221')
            subscription_role = await donut_guild.fetch_role('1276860234773692437')
            # Fetch the guilds fresh maybe?
            active_subscribers: typing.List[discord.Member] = list()

            # Get everyone with the subscriber role
            async for member in donut_guild.fetch_members():
                if subscription_role in member.roles:
                    active_subscribers.append(member)

            # Get needed data from db
            async with self.psql.acquire() as connection:
                _recorded_subscribers = await connection.fetch('SELECT * FROM subscribed_members')
                _recorded_oauths = await connection.fetch('SELECT * FROM discord_oauth WHERE user_guilds IS NOT NULL')
            
            # Sort data by ID
            recorded_subscribers = dict()
            recorded_oauths = dict()
            for record in _recorded_subscribers:
                recorded_subscribers[record['user_id']] = record
            for record in recorded_oauths:
                recorded_oauths[record['user_id']] = record
            
            # Remove all subscribers who aren't subscribed anymore
            outgoing_subscribers = list()
            for user_id in recorded_subscribers.keys():
                if not user_id in active_subscribers:
                    outgoing_subscribers.append(user_id)
            
            async with self.psql.acquire() as connection:
                # Remove outgoing subscribers
                for user_id in outgoing_subscribers:
                    await connection.execute(f'DELETE FROM subscribed_members WHERE user_id = $1', int(user_id))
                
                # Append new subscribers
                for user in active_subscribers:
                    await connection.execute(f'INSERT INTO subscribed_members(user_id, user_name, user_guilds)' 
                                             f'ON CONFLICT(user_id) DO UPDATE SET user_name = $2, user_guilds = $3',
                                             int(user.id),
                                             str(user.username),
                                             json.dumps(user.mutual_guilds))
                
            
            
            

        @self.command(name='sync')
        async def sync_command(ctx: discord.ext.commands.Context):
            if not ctx.author.id == self.bot.owner_id:
                return
            logging.info(f'Syncing tree on command')
            await self.tree.sync()
            await ctx.send('Synced ✨')
        
        @self.command(name='shutdown')
        async def shutdown_command(ctx: discord.ext.commands.Context):
            if not ctx.author.id == self.bot.owner_id:
                return
            logging.critical(f'Shutting down on command')
            await ctx.send(f'Bye bye 😵')
            await self.close()
            exit()


    async def on_ready(self):
        pass

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
              
    @property
    def now_utc_timestamp(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())
    
    # TODO: add expiry to all keys

    async def set_event(self, event: dict) -> None:
        events = json.dumps(event)
        self.redis.hset(name='events', key=f'{event['id']}', value=events)

    async def get_event(self, event_id: int) -> dict | None:
        resp = self.redis.hget(name='events', key=f'{event_id}')
        try:
            event = json.loads(resp)
        except:
            return None
        return event
    
    # I did this because the cog needs non-awaitable func
    def _get_all_events(self) -> dict:
        resp = self.redis.hgetall(name='events')
        events = dict()
        for event in resp.values():
            event = json.loads(event)
            events[event['id']] = event
        return events
    
    async def get_all_events(self) -> dict:
        return (self._get_all_events())

    async def clear_event(self, event_id: int) -> None:
        self.redis.hdel('events', f'{event_id}')
        self.redis.delete(f'interested_{event_id}')
        self.redis.delete(f'attendees_{event_id}')

    async def add_interested(self, event_id: int, user_id: int, user_data: dict) -> None:
        user_data['utc'] = self.now_utc_timestamp
        self.redis.hset(f'interested_{event_id}', user_id, json.dumps(user_data))

    async def get_interested(self, event_id: id) -> dict | None:
        resp = self.redis.hgetall(f'interested_{event_id}')
        interested = dict()
        for key, value in resp.items():
            interested[key] = json.loads(value)
        return interested
    
    async def add_attendee(self, event_id: int, user_id: int, user_data: dict) -> None:
        self.redis.hset(f'attendees_{event_id}', user_id, json.dumps(user_data))

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
        
        if not webhook:
            for webhook in await channel.webhooks():
                if await self.is_bot_webhook(webhook):
                    async with self.psql.acquire() as connection:
                        await connection.execute(f'INSERT INTO channel_webhooks(channel_id, url) VALUES ($1, $2)'
                                                 f'ON CONFLICT(channel_id) DO UPDATE channel_id=$1, url=$2', 
                                                 int(channel.id), str(webhook.url))
                    webhook = webhook
        if not webhook:
            # The try except below is important, because the limit for webhooks is 15. 
            # By deleting all the bots current webhooks in the guild, we can make sure that all useless ones are purged, as
            # new ones will be created dynamically.
            try:
                webhook = await channel.create_webhook(name=self.user.name, avatar=await self.user.avatar.read())
            except:
                for webhook in (await channel.guild.webhooks()):
                    if await self.is_bot_webhook(webhook):
                        await webhook.delete()
                webhook = await channel.create_webhook(name=self.user.name, avatar=await self.user.avatar.read())
            async with self.bot.psql.acquire() as connection:
                await connection.execute(f'INSERT INTO channel_webhooks(channel_id, url) VALUES ($1, $2)'
                                         f'ON CONFLICT(channel_id) DO UPDATE channel_id=$1, url=$2',
                                         int(channel.id), str(webhook.url))

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
    logging.info('Initialized bot')
    _redis = redis.Redis(host=os.environ.get('REDISHOST'),
                         port=os.environ.get('REDISPORT'),
                         password=os.environ.get('REDISPASSWORD'),
                         username=os.environ.get('REDISUSER'),
                         decode_responses=True)
    logging.info('Create redis')
    async with asyncpg.create_pool(database=os.environ.get('PGDATABASE'),
                                   host=os.environ.get('PGHOST'),
                                   user=os.environ.get('PGUSER'),
                                   password=os.environ.get('PGPASSWORD'),
                                   port=os.environ.get('PGPORT')) as psql:
        logging.info('Create psql')
        bot.psql = psql
        bot.redis = _redis
        await bot.load_extensions() # I load extensions after connecting to dbs cause some functions depend on that
        logging.info('Loaded extensions')
        tasks = [bot.quart.run(), bot.start(os.environ.get('TOKEN'))]
        await asyncio.gather(*tasks)
if __name__ == '__main__':
    asyncio.run(main())
