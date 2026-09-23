"""/consumable — per-consumable usage and the most used consumables, backed by the
published consumables index."""

import commonUtils
import discord
from discord import app_commands
from discord.ext import commands

from .. import config, embeds, emojis, lookups
from ..errors import ValidationError
from .items import DEFAULT_QUALITY_COLOUR, QUALITY_COLOURS

TOP_PER_CATEGORY = 3
TOP_SINGLE_CATEGORY = 10
CATEGORY_CHOICES = [
    app_commands.Choice(name=label, value=key)
    for key, label in commonUtils.CONSUMABLE_CATEGORY_LABELS
]


def resolve_consumable(name, index):
    """Accept the autocomplete value (numeric id) or an exact/unique name."""
    key = str(name).strip()
    if key.isdigit():
        for c in index:
            if int(c["id"]) == int(key):
                return c
    lowered = key.casefold()
    matches = [c for c in index if c["name"].casefold() == lowered]
    if len(matches) == 1:
        return matches[0]
    raise ValidationError("Pick a consumable from the suggestions.")


def resolve_category(category):
    if category not in lookups.CONSUMABLE_CATEGORY_LABEL:
        raise ValidationError("Pick a category from the list.")
    return category


def _consumable_url(entry):
    return f"{config.SITE_BASE}/consumables/{entry.get('slug')}"


def _consumable_line(entry):
    icon = emojis.item(entry.get("id"))
    link = f"[{embeds.esc(entry['name'])}]({_consumable_url(entry)})"
    return f"{icon} {link} · {commonUtils.humanize_number(entry.get('runs', 0))} runs".strip()


def build_consumable_embed(entry) -> discord.Embed:
    colour = QUALITY_COLOURS.get(entry.get("quality"), DEFAULT_QUALITY_COLOUR)
    embed = embeds.base_embed(embeds.esc(entry["name"]), url=_consumable_url(entry), colour=colour)
    if entry.get("icon"):
        embed.set_thumbnail(url=lookups.asset_icon_url(entry["icon"]))

    label = entry.get("category_label") or lookups.CONSUMABLE_CATEGORY_LABEL.get(entry.get("category"), "?")
    fields = [
        ("Category", label, True),
        ("Seen in", f"{commonUtils.humanize_number(entry.get('runs', 0))} runs", True),
    ]
    if entry.get("category_share") is not None:
        fields.append(("Share", f"{entry['category_share']}% of {label} users", True))
    top_spec = entry.get("top_spec")
    if top_spec is not None:
        fields.append((
            "Most used by",
            f"{emojis.spec(top_spec)} [{lookups.spec_full_name(top_spec)}]({lookups.spec_site_url(top_spec)})".strip(),
            True,
        ))
    specs = entry.get("specs") or []
    if specs:
        fields.append(("Used by", f"{len(specs)} specs", True))
    fields.append(("Links", f"[Mythistone consumable page]({_consumable_url(entry)})", False))
    embeds.add_fields_capped(embed, fields)
    return embed


def build_consumable_top_embed(index, category=None) -> discord.Embed:
    """Without a category: the top few per category. With one: its top list."""
    embed = embeds.base_embed(
        "Most Used Consumables",
        url=f"{config.SITE_BASE}/pages/consumables",
    )
    by_cat = {}
    for entry in sorted(index or [], key=lambda c: c.get("runs", 0), reverse=True):
        by_cat.setdefault(entry.get("category"), []).append(entry)

    if category:
        label = lookups.CONSUMABLE_CATEGORY_LABEL[category]
        embed.title = f"Most Used {label}s"
        entries = by_cat.get(category, [])[:TOP_SINGLE_CATEGORY]
        if not entries:
            embed.description = f"No {label} data published yet."
            return embed
        embed.description = "\n".join(
            f"**{i}.** {_consumable_line(e)}" for i, e in enumerate(entries, 1)
        )
        return embed

    fields = []
    for key, label in commonUtils.CONSUMABLE_CATEGORY_LABELS:
        entries = by_cat.get(key, [])[:TOP_PER_CATEGORY]
        if entries:
            fields.append((label, "\n".join(_consumable_line(e) for e in entries), False))
    if not fields:
        embed.description = "No consumable data published yet."
    embeds.add_fields_capped(embed, fields)
    return embed


class ConsumablesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    consumable = app_commands.Group(name="consumable", description="Consumable usage stats")

    @consumable.command(name="info", description="Usage stats for a consumable")
    @app_commands.describe(name="Consumable name")
    @app_commands.autocomplete(name=lookups.consumable_autocomplete)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def info(self, interaction, name: str):
        await interaction.response.defer(thinking=True)
        index = await self.bot.site_data.consumables_index()
        await embeds.respond(interaction, build_consumable_embed(resolve_consumable(name, index)))

    @consumable.command(name="top", description="Most used consumables, overall or per category")
    @app_commands.describe(category="Category (optional)")
    @app_commands.choices(category=CATEGORY_CHOICES)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: i.user.id)
    async def top(self, interaction, category: str | None = None):
        await interaction.response.defer(thinking=True)
        category = resolve_category(category) if category else None
        index = await self.bot.site_data.consumables_index()
        await embeds.respond(interaction, build_consumable_top_embed(index, category))


async def setup(bot):
    await bot.add_cog(ConsumablesCog(bot))
