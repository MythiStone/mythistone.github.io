"""/vods find: the best recorded POV VODs for a dungeon, POV spec and group comp,
backed by the published compVods.json the VOD page's finder reads."""

import urllib.parse
from collections import Counter

import commonUtils
import discord
from discord import app_commands
from discord.ext import commands

from .. import config, embeds, emojis, lookups

VODS_SHOWN = 5
VIDEO_PLATFORMS = {"twitch": "Twitch", "youtube": "YouTube"}


def filter_vods(comp_vods, dungeon_id=None, pov_spec=None, group=()):
    """VODs matching every filter, best first (commonUtils.rank_run_entries, the
    VOD page's order). ``group`` is a spec multiset that must fit inside the comp,
    so asking for two Frost Mages needs two in the group."""
    need = Counter(int(s) for s in group)
    out = []
    for v in (comp_vods or {}).values():
        if dungeon_id and str(v.get("dungeon")) != str(dungeon_id):
            continue
        if pov_spec and str(v.get("pov_spec")) != str(pov_spec):
            continue
        if need and need - Counter(int(s) for s in v.get("specs") or []):
            continue
        out.append(v)
    commonUtils.rank_run_entries(out)
    return out


def vods_page_url(dungeon_id=None, pov_spec=None, group=()):
    """The VOD page with the same filters applied (finder.js reads these params)."""
    params = {}
    if dungeon_id:
        params["dungeons"] = str(dungeon_id)
    if group:
        params["specs"] = ",".join(str(s) for s in group)
    if pov_spec:
        params["povSpecs"] = str(pov_spec)
    query = urllib.parse.urlencode(params, safe=",")
    return f"{config.SITE_BASE}/pages/vods" + (f"?{query}" if query else "")


def watch_url(vod):
    return commonUtils.build_vod_watch_url(vod.get("video_ref"), vod.get("video_type"), vod.get("start_seconds"))


def _vod_field(vod):
    did = vod.get("dungeon")
    key = embeds.upgrade_text(did, vod.get("duration"), vod.get("level"))
    name = f"{key} {lookups.dungeon_name(did)} · {commonUtils.format_duration(vod.get('duration'))}"

    pov_spec = vod.get("pov_spec")
    player = embeds.esc(vod.get("pov_character_name") or "Unknown")
    if vod.get("streamer_slug"):
        player = f"[{player}]({config.SITE_BASE}/streamers/{vod['streamer_slug']})"
    pov = f"{emojis.spec(pov_spec)} {player}".strip() if pov_spec else player
    when = f"<t:{int(vod['timestamp'])}:R>" if vod.get("timestamp") else ""

    links = []
    url = watch_url(vod)
    if url:
        links.append(f"[Watch on {VIDEO_PLATFORMS.get(vod.get('video_type'), 'video')}]({url})")
    if vod.get("route_key"):
        links.append(f"[Route]({embeds.keystone_guru_route_url(vod['route_key'], did)})")
    if vod.get("run_id"):
        links.append(f"[Run]({embeds.raider_io_run_url(vod['run_id'])})")

    lines = [" · ".join(p for p in (f"POV {pov}", when) if p)]
    if vod.get("specs"):
        lines.append(embeds.comp_line(vod["specs"], with_names=False))
    lines.append(" · ".join(links))
    return name, "\n".join(lines), False


def _filter_summary(dungeon_id, pov_spec, group):
    parts = []
    if dungeon_id:
        parts.append(lookups.dungeon_name(dungeon_id))
    if pov_spec:
        parts.append(f"{lookups.spec_full_name(pov_spec)} POV")
    if group:
        parts.append("with " + ", ".join(lookups.spec_full_name(s) for s in group))
    return " · ".join(parts)


def build_vods_embed(vods, dungeon_id=None, pov_spec=None, group=()) -> discord.Embed:
    """Up to VODS_SHOWN VODs, one field each, linking to the filtered VOD page."""
    page = vods_page_url(dungeon_id, pov_spec, group)
    embed = embeds.base_embed("Mythic+ VODs", url=page)
    if dungeon_id:
        embeds.set_dungeon_thumbnail(embed, dungeon_id)
    elif pov_spec:
        embed.set_thumbnail(url=lookups.spec_icon_url(pov_spec))
    summary = _filter_summary(dungeon_id, pov_spec, group)
    if not vods:
        embed.description = (
            f"No recorded VODs match {summary or 'these filters'}. Try fewer specs or "
            f"another dungeon on the [VOD page]({page})."
        )
        return embed
    shown = vods[:VODS_SHOWN]
    header = f"{summary}\n" if summary else ""
    embed.description = (
        f"{header}Top {len(shown)} of {len(vods)} matching VODs, highest key first. "
        f"[Browse all on the VOD page]({page})."
    )
    embeds.add_fields_capped(embed, [_vod_field(v) for v in shown])
    return embed


class VodsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    vods = app_commands.Group(name="vods", description="Recorded Mythic+ POV videos")

    @vods.command(name="find", description="Best VODs for a dungeon, POV spec and group comp")
    @app_commands.describe(
        dungeon="Dungeon (optional)",
        pov_spec="Spec you want to watch from (optional)",
        spec1="Spec in the group (optional)", spec2="Spec in the group (optional)",
        spec3="Spec in the group (optional)", spec4="Spec in the group (optional)",
    )
    @app_commands.choices(dungeon=lookups.DUNGEON_CHOICES)
    @app_commands.autocomplete(
        pov_spec=lookups.spec_full_autocomplete,
        spec1=lookups.spec_full_autocomplete, spec2=lookups.spec_full_autocomplete,
        spec3=lookups.spec_full_autocomplete, spec4=lookups.spec_full_autocomplete,
    )
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def find(self, interaction, dungeon: str = None, pov_spec: str = None,
                   spec1: str = None, spec2: str = None, spec3: str = None, spec4: str = None):
        await interaction.response.defer(thinking=True)
        did = lookups.resolve_dungeon(dungeon) if dungeon else None
        pov = lookups.resolve_spec_full(pov_spec) if pov_spec else None
        group = [lookups.resolve_spec_full(s) for s in (spec1, spec2, spec3, spec4) if s]
        comp_vods = await self.bot.site_data.comp_vods()
        matches = filter_vods(comp_vods, did, pov, group)
        embed = build_vods_embed(matches, did, pov, group)
        # A bare URL in the message text makes Discord show the top VOD's player preview.
        top_url = watch_url(matches[0]) if matches else ""
        await embeds.respond(interaction, embed, content=top_url or None)


async def setup(bot):
    await bot.add_cog(VodsCog(bot))
