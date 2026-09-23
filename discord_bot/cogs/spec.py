"""/spec: per-spec preview image, popular gear, top talent build, stats and consumables."""

import commonUtils
import databaseConnector
import discord
from discord import app_commands
from discord.ext import commands

from .. import cache, config, db, embeds, emojis, lookups

# Fixed slot render order (spec_meta uses FINGER_1/2, TRINKET_1/2, MAIN_HAND, OFF_HAND).
# Two-column slot order mirroring the site's gear overview (generateSpecPages.py
# LEFT_ORDER + WEAPON_SLOTS / RIGHT_ORDER + TRINKET_SLOTS).
GEAR_LEFT = ["HEAD", "NECK", "SHOULDER", "BACK", "CHEST", "WRIST", "MAIN_HAND", "OFF_HAND"]
GEAR_RIGHT = ["HANDS", "WAIST", "LEGS", "FEET", "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2"]
_ZWSP = "​"  # zero-width space: a nameless (label-less) field header


# --- cached DB helpers -----------------------------------------------------
@cache.ttl_cache(3600)
async def _get_top_loadout(spec_id):
    return await db.run(databaseConnector.fetch_top_loadout, spec_id, config.SEASON)


@cache.ttl_cache(3600)
async def _get_stats(spec_id):
    return await db.run(commonUtils.fetch_stat_info, spec_id, config.SEASON, lookups.SPECS)


@cache.ttl_cache(3600)
async def _get_consumable_sections(spec_id, hero_id=None):
    """Same sections the spec page renders (commonUtils.build_consumable_sections),
    spec-wide or for one hero tree."""
    ctx = lookups.CONSUMABLES
    aura_rows = await db.run(databaseConnector.fetch_consumable_count, spec_id, config.SEASON, hero_id)
    oil_rows = await db.run(
        databaseConnector.fetch_weapon_temp_enchant_usage,
        spec_id, config.SEASON, ctx["temp_enchant_effect_ids"], hero_id,
    )
    return commonUtils.build_consumable_sections(
        aura_rows,
        ctx["consumable_index"],
        ctx["consumable_lookup"],
        extra_sections=[commonUtils.build_weapon_enchant_section(
            oil_rows, ctx["temp_enchant_index"], slug_map=ctx["slug_map"],
        )],
        slug_map=ctx["slug_map"],
    )


# --- embed builders --------------------------------------------------------
def build_overview_embed(spec_id) -> discord.Embed:
    """Just the spec preview image (like /dungeon overview)."""
    embed = embeds.spec_embed_header(spec_id)
    preview = lookups.spec_preview_url(spec_id)
    if preview:
        embed.set_image(url=preview)
    return embed


def build_gear_embed(spec_id, spec_meta) -> discord.Embed:
    """Most-popular item per slot as ``<item emoji> name`` in two columns (like the
    site's gear overview) — no stats, enchants/gems, highlighting or percentages."""
    embed = embeds.spec_embed_header(spec_id)
    embed.title = f"{lookups.spec_full_name(spec_id)} — Popular Gear"
    slots = (spec_meta or {}).get("slots", {})
    if not _gear_columns(embed, spec_id, slots):
        embed.description = "No gear data published for this spec yet."
    return embed


def build_talents_embed(spec_id, loadouts) -> discord.Embed:
    """The single most-used talent build (the site's default/meta hero-tree loadout)
    as a copyable string, plus a link to the site for per-dungeon differences."""
    embed = embeds.spec_embed_header(spec_id)
    embed.title = f"{lookups.spec_full_name(spec_id)} — Top Talent Build"
    valid = [r for r in (loadouts or []) if len(r) > 1 and r[1]]
    if not valid:
        embed.description = "No talent build data for this spec yet."
        return embed
    top = max(valid, key=lambda r: int(r[2]) if len(r) > 2 and r[2] is not None else 0)
    loadout = str(top[1])
    runs = int(top[2]) if len(top) > 2 and top[2] is not None else 0
    best = int(top[3]) if len(top) > 3 and top[3] is not None else 0
    embed.description = (
        f"Most-used build — {commonUtils.humanize_number(runs)} runs · best +{best}.\n"
        f"Per-dungeon talent differences & full details on the "
        f"[website]({lookups.spec_site_url(spec_id)})."
    )
    embeds.add_fields_capped(embed, [
        ("Talent string (copy)", f"```\n{embeds.clamp(loadout, 1000)}\n```", False),
    ])
    return embed


def build_stats_embed(spec_id, stat_info) -> discord.Embed:
    embed = embeds.spec_embed_header(spec_id)
    embed.title = f"{lookups.spec_full_name(spec_id)} — Stat Priority"
    stat_priority, tertiary, health = stat_info

    def fmt(items):
        out = []
        for value in items:
            name = commonUtils.stat_display_name(value.get("name"))
            pct = value.get("avg_percent")
            if isinstance(pct, (int, float)):
                out.append(f"**{name}** — {pct:.1f}%")
            else:
                out.append(f"**{name}** — {commonUtils.humanize_number(value.get('avg_raw', 0))}")
        return "\n".join(out)

    fields = [
        ("Secondary priority", fmt(stat_priority), False),
        ("Tertiaries", fmt(tertiary), True),
        ("Health", fmt(health), True),
    ]
    if not any(f[1] for f in fields):
        embed.description = "No stat data available for this spec yet."
    embeds.add_fields_capped(embed, fields)
    return embed


CONSUMABLE_ENTRIES_SHOWN = 3


def build_consumables_embed(spec_id, sections, hero_id=None, fallback=False) -> discord.Embed:
    """Top picks per consumable category with their share of the category, like the
    spec page's Consumables accordion. ``fallback`` marks a thin hero tree that
    shows the spec-wide sections instead."""
    embed = embeds.spec_embed_header(spec_id)
    hero_name = lookups.HERO_TREES_BY_SPEC.get(str(spec_id), {}).get(str(hero_id)) if hero_id else None
    embed.title = f"{lookups.spec_full_name(spec_id)} · Consumables"
    if hero_name:
        embed.title += f" ({hero_name})"
        embed.url = f"{lookups.spec_site_url(spec_id)}#&hero={hero_id}"
    notes = []
    if fallback:
        notes.append(f"Not enough {embeds.esc(hero_name)} data, showing all builds.")
    if not sections:
        notes.append("Not enough consumable data for this spec yet.")
        embed.description = "\n".join(notes)
        return embed

    fields = []
    for sec in sections:
        lines = []
        for e in sec["entries"][:CONSUMABLE_ENTRIES_SHOWN]:
            name = embeds.esc(e.get("name") or "?")
            if e.get("slug"):
                link = f"[{name}]({config.SITE_BASE}/consumables/{e['slug']})"
            elif e.get("item_id"):
                link = f"[{name}](https://www.wowhead.com/item={e['item_id']})"
            else:
                link = name
            icon = emojis.item(e.get("item_id")) if e.get("item_id") is not None else ""
            lines.append(f"{icon} {link} · **{e['pct']}%**".strip())
        label = f"{sec['label']} ({commonUtils.humanize_number(sec['total'])} runs)"
        fields.append((label, "\n".join(lines), False))
    notes.append(f"Full breakdown on the [website]({embed.url}).")
    embed.description = "\n".join(notes)
    embeds.add_fields_capped(embed, fields)
    return embed


def _gear_columns(embed, spec_id, slots):
    """Two side-by-side columns of ``<item emoji> [name](link)`` — the most-popular
    (``common``) item per slot, in the same left/right slot order the site's gear
    overview uses. Item links carry ``?spec=`` like the spec-page links."""
    def column(slot_names):
        out = []
        for slot in slot_names:
            pick = (slots.get(slot) or {}).get("common")
            if not isinstance(pick, dict):
                continue
            name = embeds.esc(pick.get("name", "?"))
            slug = pick.get("slug", "")
            icon = emojis.item(pick.get("id")) if pick.get("id") is not None else ""
            link = f"[{name}]({config.SITE_BASE}/items/{slug}?spec={spec_id})" if slug else name
            out.append(f"{icon} {link}".strip())
        return out

    left, right = column(GEAR_LEFT), column(GEAR_RIGHT)
    if not left and not right:
        return False
    embeds.add_fields_capped(embed, [
        (_ZWSP, "\n".join(left), True),
        (_ZWSP, "\n".join(right), True),
    ])
    return True


# --- cog -------------------------------------------------------------------
def _resolve(class_name, spec_name):
    class_id = lookups.resolve_class(class_name)
    return lookups.resolve_spec(class_id, spec_name)


class SpecCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    spec = app_commands.Group(name="spec", description="Per-spec builds & stats")

    @spec.command(name="overview", description="Spec preview image")
    @app_commands.rename(class_name="class", spec_name="spec")
    @app_commands.describe(class_name="Class", spec_name="Specialization")
    @app_commands.choices(class_name=lookups.CLASS_CHOICES)
    @app_commands.autocomplete(spec_name=lookups.spec_autocomplete)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def overview(self, interaction, class_name: str, spec_name: str):
        await interaction.response.defer(thinking=True)
        await embeds.respond(interaction, build_overview_embed(_resolve(class_name, spec_name)))

    @spec.command(name="gear", description="Most popular gear per slot")
    @app_commands.rename(class_name="class", spec_name="spec")
    @app_commands.describe(class_name="Class", spec_name="Specialization")
    @app_commands.choices(class_name=lookups.CLASS_CHOICES)
    @app_commands.autocomplete(spec_name=lookups.spec_autocomplete)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def gear(self, interaction, class_name: str, spec_name: str):
        await interaction.response.defer(thinking=True)
        spec_id = _resolve(class_name, spec_name)
        spec_meta = await self.bot.site_data.spec_meta(spec_id)
        await embeds.respond(interaction, build_gear_embed(spec_id, spec_meta))

    @spec.command(name="talents", description="Top talent build (copyable string)")
    @app_commands.rename(class_name="class", spec_name="spec")
    @app_commands.describe(class_name="Class", spec_name="Specialization")
    @app_commands.choices(class_name=lookups.CLASS_CHOICES)
    @app_commands.autocomplete(spec_name=lookups.spec_autocomplete)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def talents(self, interaction, class_name: str, spec_name: str):
        await interaction.response.defer(thinking=True)
        spec_id = _resolve(class_name, spec_name)
        loadouts = await _get_top_loadout(spec_id)
        await embeds.respond(interaction, build_talents_embed(spec_id, loadouts))

    @spec.command(name="stats", description="Stat priority")
    @app_commands.rename(class_name="class", spec_name="spec")
    @app_commands.describe(class_name="Class", spec_name="Specialization")
    @app_commands.choices(class_name=lookups.CLASS_CHOICES)
    @app_commands.autocomplete(spec_name=lookups.spec_autocomplete)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def stats(self, interaction, class_name: str, spec_name: str):
        await interaction.response.defer(thinking=True)
        spec_id = _resolve(class_name, spec_name)
        stat_info = await _get_stats(spec_id)
        await embeds.respond(interaction, build_stats_embed(spec_id, stat_info))

    @spec.command(name="consumables", description="Most used flasks, potions, food, oils and runes")
    @app_commands.rename(class_name="class", spec_name="spec")
    @app_commands.describe(class_name="Class", spec_name="Specialization",
                           hero_tree="Hero tree (optional, default all builds)")
    @app_commands.choices(class_name=lookups.CLASS_CHOICES)
    @app_commands.autocomplete(spec_name=lookups.spec_autocomplete,
                               hero_tree=lookups.hero_tree_autocomplete)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def consumables(self, interaction, class_name: str, spec_name: str,
                          hero_tree: str | None = None):
        await interaction.response.defer(thinking=True)
        spec_id = _resolve(class_name, spec_name)
        hero_id = lookups.resolve_hero_tree(spec_id, hero_tree) if hero_tree else None
        sections = await _get_consumable_sections(spec_id, hero_id)
        fallback = bool(hero_id) and not sections
        if fallback:
            sections = await _get_consumable_sections(spec_id)
        await embeds.respond(interaction, build_consumables_embed(spec_id, sections, hero_id, fallback))


async def setup(bot):
    await bot.add_cog(SpecCog(bot))
