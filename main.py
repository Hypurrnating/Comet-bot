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

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

discord.utils.setup_logging(level=logging.INFO)
logging.getLogger('discord.gateway').setLevel(30)   # Stops a flood of "gate RESUMED" messages

bot = discord.ext.commands.Bot(
    description='Donut :3',
    command_prefix=discord.ext.commands.when_mentioned,
    intents=discord.Intents.default())

# Now we define some functions that will be used throughout the bot

bot.webhooks = dict()

class errors():
    pass

class WebhookError(Exception):
    """Exception for whenever there is an error relating managing webhooks"""
    pass

bot.errors = errors()
bot.errors.WebhookError = WebhookError

async def is_bot_webhook(webhook: discord.Webhook) -> bool:
    """Check if the webhook is created by THIS bot

    Args:
        webhook (discord.Webhook): The webhook to check
    """
    if webhook.is_partial():
        webhook = await webhook.fetch()
    
    if not webhook.type.name == 'application':
        return False
    
    if not webhook.user == bot.user:
        return False
    
    return True

async def cache_channel_webhook(channel: discord.TextChannel, webhook: discord.Webhook = None):
    bot_webhook = webhook if webhook else (bot.webhooks[channel.id] if bot.webhooks.get(channel.id) else None)
    if not bot_webhook:
        raise Exception('No webhook passed, and none in channel attribute')

    resp = await (await bot.sqlite.cursor()).execute("SELECT * FROM channel_webhooks WHERE channel_id = ?", 
                                                          (channel.id,))

    if resp:
        await (await bot.sqlite.cursor()).execute("UPDATE channel_webhooks SET url = ? WHERE channel_id = ?",
                                             (bot_webhook.url,
                                              channel.id))
        
    if not resp:
        await (await bot.sqlite.cursor()).execute("INSERT INTO channel_webhooks(channel_id, url) VALUES (?, ?)",
                                                       (channel.id,
                                                        bot_webhook.url))
    
    await bot.sqlite.commit()

async def grab_channel_webhook(channel: discord.TextChannel) -> discord.Webhook:
    """

    Args:
        channel (discord.TextChannel): _description_

    Returns:
        discord.Webhook: _description_
    """
    bot_webhook = None

    # This checks if a webhook has been assigned to a channel already
    if bot.webhooks.get(channel.id):
        return bot.webhooks[channel.id]
    
    else:
        # get a cached webhook url from sqlite
        resp = await (await (await bot.sqlite.cursor()).execute("SELECT * FROM channel_webhooks WHERE channel_id = ?", (channel.id,))).fetchone()

        # if it does exist in sqlite cache then create the partial webhook, and then create the complete one by .fetch()
        if resp:
            bot_webhook = await (discord.Webhook.from_url(resp['url'])).fetch()

        # if it doesn't exist in sqlite cache then fetch all webhooks in channel, if found use it and cache it, if not found create one and cache it.
        if not resp: 
            for webhook in (await channel.webhooks()):
                # check if it has 'state attached' and is the bots webhook
                if await is_bot_webhook(webhook):
                    bot_webhook = webhook
            
            if not bot_webhook:
                async with bot.psql.acquire() as connection:
                    guild_settings = await connection.fetch("SELECT * FROM webhook_configs WHERE guild_id = $1", int(channel.guild.id))
                if not guild_settings: 
                    raise bot.errors.WebhookError('Guild is not registered with any configuration')
                guild_settings = dict(guild_settings[0])
                bot_webhook = await channel.create_webhook(name=guild_settings['name'], avatar=guild_settings['avatar'])
            await cache_channel_webhook(channel, bot_webhook)
        
        # assign webhook object to channel for ease and then return it 
        bot.webhooks[channel.id] = bot_webhook
    return bot.webhooks[channel.id]

async def delete_guild_webhooks(guild: discord.Guild, reason: str = None):
    for webhook in (await guild.webhooks()):
        if not await is_bot_webhook():
            continue
        else:
            await webhook.delete(reason=reason)
        

@bot.event
async def on_ready():
    await bot.tree.sync()

async def main():

    # Use this method to figure out where to store the sqlite db file. Helps run the script on my windows pc and on the linux host without issues
    def get_db_loc():
        print(f'Running on: {platform.system()}')
        if platform.system() == 'Windows':
            return '.db'
        if platform.system() == 'Ubuntu':
            return '/s/.db'

    async def create_tables():
        await (await bot.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS channel_webhooks(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id BIGINT, url VARCHAR(1500))')
        await (await bot.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS guild_starboards(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, added_by BIGINT)')
        await (await bot.sqlite.cursor()).execute('CREATE TABLE IF NOT EXISTS stars(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT, channel_id BIGINT, message_id BIGINT, user_id BIGINT)')

    for x in pathlib.Path(f'./extensions').iterdir():
        if x.is_file():
            await bot.load_extension(f'extensions.{x.name.split(".")[0]}')

        """async with asyncpg.create_pool(database=os.environ.get('PGDATABASE'),
                                   host=os.environ.get('PGHOST'),
                                   user=os.environ.get('PGUSER'),
                                   password=os.environ.get('PGPASSWORD'),
                                   port=os.environ.get('PGPORT')) as pool:

        bot.psql = pool"""
    bot.sqlite = await aiosqlite.connect(get_db_loc())
    await create_tables()

    await bot.start(os.environ.get('TOKEN'))

asyncio.run(main())
