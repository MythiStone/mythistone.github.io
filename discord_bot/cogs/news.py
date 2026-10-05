"""/news — admin setup of the channel that receives the daily social post.

Delivery happens in CI (``backend_scripts/broadcastDiscordNews.py``), which reads
``bot_news_channels`` and posts with the bot token. This cog only manages that row.
"""

import databaseConnector
import discord
from discord import app_commands
from discord.ext import commands

from .. import config, db, embeds
from ..errors import ValidationError

# Must match what broadcastDiscordNews.py sends: an embed with an attached image.
REQUIRED_PERMS = ("view_channel", "send_messages", "embed_links", "attach_files")


def _reply(description: str) -> discord.Embed:
    return discord.Embed(description=description, colour=embeds.BRAND_COLOR)


class NewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # default_permissions hides the group from non-admins (server owners can
    # override it), so each subcommand re-checks Manage Server at runtime too.
    news = app_commands.Group(
        name="news",
        description="Daily Mythistone post in a channel of this server",
        guild_only=True,
        allowed_installs=app_commands.AppInstallationType(guild=True, user=False),
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @news.command(name="setup", description="Send the daily Mythistone post to a channel")
    @app_commands.describe(channel="Channel that should receive the daily post")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.guild_id)
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild = interaction.guild
        me = guild.me if guild is not None else None
        if me is None:
            raise ValidationError(
                "The Mythistone bot has to be added to this server before it can post here."
            )
        perms = channel.permissions_for(me)
        missing = [p for p in REQUIRED_PERMS if not getattr(perms, p)]
        if missing:
            names = ", ".join(p.replace("_", " ").title() for p in missing)
            raise ValidationError(f"I am missing these permissions in {channel.mention}: {names}.")

        await interaction.response.defer(ephemeral=True, thinking=True)
        confirmation = embeds.base_embed(
            "Daily Mythistone posts",
            url=config.SITE_BASE,
            description="This channel now receives the daily Mythistone M+ data post.",
        )
        try:
            await channel.send(embed=confirmation)
        except discord.Forbidden as exc:
            raise ValidationError(f"I could not post in {channel.mention}. Check my permissions there.") from exc
        await db.run(
            databaseConnector.upsert_bot_news_channel, guild.id, channel.id, interaction.user.id
        )
        await interaction.followup.send(
            embed=_reply(f"Daily Mythistone posts will go to {channel.mention}."), ephemeral=True
        )

    @news.command(name="remove", description="Stop the daily Mythistone post in this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        removed = await db.run(databaseConnector.delete_bot_news_channel, interaction.guild_id)
        text = "Daily Mythistone posts are turned off." if removed else "No channel was set up."
        await interaction.followup.send(embed=_reply(text), ephemeral=True)

    @news.command(name="status", description="Show which channel gets the daily Mythistone post")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel_id = await db.run(databaseConnector.fetch_bot_news_channel, interaction.guild_id)
        if channel_id is None:
            text = "No channel is set up. Use `/news setup` to pick one."
        else:
            text = f"Daily Mythistone posts go to <#{channel_id}>."
        await interaction.followup.send(embed=_reply(text), ephemeral=True)


async def setup(bot):
    await bot.add_cog(NewsCog(bot))
