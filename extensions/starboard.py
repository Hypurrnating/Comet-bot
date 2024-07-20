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

        resp = await (await self.bot.sqlite.execute('SELECT * FROM guild_starboards WHERE guild_id = ?', (interaction.guild.id,))).fetchone()

        if not resp:
            await self.bot.sqlite.execute('INSERT INTO guild_starboards(guild_id, channel_id, added_by) VALUES (?, ?, ?)', (interaction.guild.id, channel.id, interaction.user.id))
        if resp:
            await self.bot.sqlite.execute('UPDATE guild_starboards SET channel_id = ?, added_by = ? WHERE guild_id = ?', (channel.id, interaction.user.id, interaction.guild.id))
            
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
        author = message.guild.get_member(payload.message_author_id) if message.guild.get_member(payload.message_author_id) else await message.guild.fetch_member(payload.message_author_id)

        msg_stars = await (await (await self.bot.sqlite.execute('SELECT * FROM stars WHERE message_id = ?', (message.id,)))).fetchall()
        if not len(msg_stars) >= 1:
            return

        
        resp = await (await (await self.bot.sqlite.cursor()).execute('SELECT * FROM guild_starboards WHERE guild_id = ?', (message.guild.id,))).fetchone()
        if resp: id, guild_id, channel_id, added_by = resp
        if not resp:
            return

        try:
            starboard: discord.TextChannel = self.bot.get_channel(channel_id) if self.bot.get_channel(channel_id) else await self.bot.fetch_channel(channel_id)
        except discord.NotFound:
            await (await self.bot.sqlite.cursor()).execute('DELETE FROM guild_starboards WHERE channel_id = ?', (channel_id))

        if not message.content and not message.attachments:
            await starboard.send(content=message.jump_url)

        if message.content or message.attachments:
            embed = discord.Embed(title='',
                                    description=(message.content) if message.content else '',
                                    color=0xfccf03)
            
            embed.timestamp = message.created_at
            embed.set_author(name=author.display_name,
                            url=f'https://discord.com/users/{
                                author.id}',
                            icon_url=author.guild_avatar.url if author.guild_avatar else (author.avatar.url if author.avatar else None))
            
            embed.add_field(name=' ', value=f'[Jump to message]({message.jump_url})')

            if message.reference and not isinstance(message.reference.resolved, discord.DeletedReferencedMessage):
                if not message.reference.cached_message:
                    ref = await message.channel.fetch_message(message.reference.message_id)
                else: ref = message.reference.cached_message
                embed.add_field(name='',
                                value=f'***Replying to [{ref.author.display_name}]({ref.jump_url})***' + f'\n{ref.content if len(ref.content) < 950 else ""}',
                                inline=False)

            msg = await starboard.send(embed=embed, files=[await attachment.to_file() for attachment in message.attachments])

        await message.reply(content=f'Starboarded')


    
async def setup(bot):
    await bot.add_cog(starboard_cog(bot))
