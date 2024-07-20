import discord
import discord.ext
import discord.ext.commands
from discord import Interaction, app_commands
import asyncio

class starboard_cog(discord.ext.commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    starboard_group = discord.app_commands.Group(name='starboard', description='Starboard lets members of a server "pin" a message to a separate channel by reacting with a star')

    @starboard_group.command(name='set', description='Set a server channel to be the starboard. This where all starred messages will get sent')
    @app_commands.checks.has_permissions(manage_channels = True)
    @app_commands.describe(
        channel = 'This is where all starred messages will be sent',
        move_stars = 'If this server has starred messages in another channel, this will move them to the new one'
    )
    async def starboard_set(self, interaction: discord.Interaction, channel: discord.TextChannel, move_stars: bool = True):
        await interaction.response.defer(thinking=True)

        resp = await (await self.bot.sqlite.cursor()).execute('SELECT * FROM guild_starboards WHERE guild_id = ?', (interaction.guild.id,))

        if not resp:
            await (await self.bot.sqlite.cursor()).execute('INSERT INTO guild_starboards(guild_id, channel_id, added_by) VALUES (?, ?, ?)', (interaction.guild.id, channel.id, interaction.user.id))
        if resp:
            resp = await resp.fetchone()
            await (await self.bot.sqlite.cursor()).execute('UPDATE guild_starboards SET channel_id = ?, added_by = ? WHERE guild_id = ?', (channel.id, interaction.user.id, interaction.guild.id))
            
        await self.bot.sqlite.commit()

        await interaction.followup.send(content=f'{channel.mention} has been set as the starboard! {'All the old stars will be moved to the new starboard' if (move_stars == True and resp == True) else ''}')
        
        if move_stars == True and resp == True:
            channel: discord.TextChannel = self.bot.get_channel(resp['channel_id']) if self.bot.get_channel(resp['channel_id']) else await self.bot.fetch_channel(resp['channel_id'])
            async for message in channel.history(limit=None, oldest_first=True):
                # this mega if statement works because we check the len of the list before indexing it, otherwise no embeds would cause a error
                if message.author == self.bot.user \
                and message.embeds \
                and len(message.embeds) == 1 \
                and message.embeds[0].description.startswith('### ') \
                and message.embeds[0].color == 0xfccf03:
                    await channel.send(content=message.content, embed=message.embeds[0])
                    await asyncio.sleep(1)  # Prevent ratelimits. 

    @discord.ext.commands.Cog.listener('on_raw_reaction_add')
    async def star_listener(self, payload: discord.RawReactionActionEvent):
        if not payload.emoji.name == '⭐':
            return

        channel: discord.TextChannel = self.bot.get_channel(payload.channel_id) if self.bot.get_channel(payload.channel_id) else await self.bot.fetch_channel(payload.channel_id)
        message: discord.Message = await channel.fetch_message(payload.message_id)

        if not [reaction.emoji for reaction in message.reactions].count('⭐') >= 1:
            return
        
        resp = await (await (await self.bot.sqlite.cursor()).execute('SELECT * FROM guild_starboards WHERE guild_id = ?', (message.guild.id,))).fetchone()
        if not resp:
            return

        try:
            starboard: discord.TextChannel = self.bot.get_channel(resp['channel_id']) if self.bot.get_channel(resp['channel_id']) else await self.bot.fetch_channel(resp['channel_id'])
        except discord.NotFound:
            await (await self.bot.sqlite.cursor()).execute('DELETE FROM guild_starboards WHERE channel_id = ?', (resp['channel_id']))

        embed = discord.Embed(title='',
                                description='### ' + message.content,
                                color=0xfccf03)
        
        embed.timestamp = message.created_at
        embed.set_author(name=message.author.display_name,
                         url=f'https://discord.com/users/{
                             message.author.id}',
                         icon_url=message.author.guild_avatar.url if message.author.guild_avatar else None)

        # just a mega big if statement to make sure cause why not
        if message.reference and message.reference.cached_message and not isinstance(message.reference.resolved, discord.DeletedReferencedMessage):
            embed.add_field(name='Replying to',
                            value=f'[{message.reference.cached_message.author.display_name}]({message.reference.cached_message.jump_url}){f':\n\n{message.reference.cached_message.content if len(message.reference.cached_message.content) < 1000 else ''}'}')

        attachments = str(' ').join([f'[⬤]({attachment.url})' for attachment in message.attachments])

        await starboard.send(content=attachments, embed=embed)
        await message.reply(content=f'Starboarded')


    
async def setup(bot):
    await bot.add_cog(starboard_cog(bot))
