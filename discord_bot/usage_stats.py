"""Command-usage tracking and the self-updating usage embed.

Every slash-command invocation is written to ``bot_command_usage`` (one row per
call, with an outcome), and a single webhook message on ``WEBHOOK_URL`` is edited
every few minutes with the last 24h of usage, mirroring the collector's status
embed (``backend_scripts/discordHandler.py``). The message id is persisted in the
``bot_cache`` volume so restarts keep editing the same message.

Outcomes: ``ok`` (completed), ``blocked`` (season guard), ``user_error`` (bad
input / cooldown), ``error`` (DB or site data unavailable), ``crash`` (unhandled).
"""

import json
import logging
import os
import time

import discord

import databaseConnector

from . import config, db
from .embeds import MAX_FIELD_VALUE

log = logging.getLogger("mythistone.bot")

ICON_URL = config.SITE_BASE + "/assets/img/favicon/favicon-96x96.png"


def record(client, interaction, outcome: str) -> None:
    """Schedule the usage row insert without delaying the user's reply. Never raises."""
    try:
        command = interaction.command
        name = command.qualified_name if command is not None else "?"
        client.loop.create_task(_insert(name[:64], outcome))
    except Exception:
        log.warning("failed to schedule command usage insert", exc_info=True)


async def _insert(name: str, outcome: str) -> None:
    try:
        await db.run(
            databaseConnector.insert_bot_command_usage, config.SEASON, name, outcome
        )
    except Exception:
        log.warning("failed to record command usage for /%s", name, exc_info=True)


def _summarise(rows):
    """[(command, outcome, count)] -> (per-command {uses, err}, outcome totals)."""
    per_command: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for command, outcome, count in rows:
        count = int(count)
        totals[outcome] = totals.get(outcome, 0) + count
        entry = per_command.setdefault(command, {"uses": 0, "err": 0})
        entry["uses"] += count
        if outcome in ("error", "crash"):
            entry["err"] += count
    return per_command, totals


def _table(header, rows, limit: int) -> str:
    """Aligned code-block table that stays within ``limit`` characters. Rows that
    do not fit are dropped and summarised in a trailing "+N more" line, so the
    code fence is never cut in half."""
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]

    def line(r):
        first = str(r[0]).ljust(widths[0])
        rest = "  ".join(str(v).rjust(w) for v, w in zip(r[1:], widths[1:]))
        return f"{first}  {rest}"

    lines = [line(header)]
    for i, r in enumerate(rows):
        candidate = line(r)
        more = f"+{len(rows) - i} more"
        # fences (8) + newlines + room for a possible "+N more" line
        if sum(len(x) + 1 for x in lines) + len(candidate) + len(more) + 10 > limit:
            lines.append(more)
            break
        lines.append(candidate)
    return "```\n" + "\n".join(lines) + "\n```"


def build_embed(rows, next_update_epoch: int) -> discord.Embed:
    per_command, totals = _summarise(rows)
    embed = discord.Embed(
        title="Bot command usage",
        description=f"Last 24 hours. Next update in: <t:{next_update_epoch}:R>",
        url=config.SITE_BASE,
        colour=discord.Colour.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=ICON_URL)
    embed.set_footer(text="Mythistone Bot", icon_url=ICON_URL)

    total_uses = sum(totals.values())
    summary = [
        ("Commands", total_uses),
        ("Completed", totals.get("ok", 0)),
        ("Errors", totals.get("error", 0) + totals.get("crash", 0)),
        ("  of which crashes", totals.get("crash", 0)),
        ("User errors", totals.get("user_error", 0)),
        ("Season blocked", totals.get("blocked", 0)),
    ]
    embed.add_field(
        name="📊 Totals",
        value=_table(("", "count"), [(k, f"{v:,}") for k, v in summary], MAX_FIELD_VALUE),
        inline=False,
    )

    if not per_command:
        embed.add_field(name="⌨️ Commands", value="No commands in the last 24h.", inline=False)
        return embed

    ordered = sorted(per_command.items(), key=lambda kv: (-kv[1]["uses"], kv[0]))
    table_rows = [(f"/{name}", f"{c['uses']:,}", f"{c['err']:,}") for name, c in ordered]
    embed.add_field(
        name="⌨️ Commands",
        value=_table(("command", "uses", "err"), table_rows, MAX_FIELD_VALUE),
        inline=False,
    )
    return embed


class UsageReporter:
    """Owns the single usage webhook message: edits it in place, recreating it
    (and persisting the new id) when it was deleted or never existed."""

    def __init__(self, webhook_url: str, session, interval_seconds: int):
        self.webhook = discord.Webhook.from_url(webhook_url, session=session)
        self.interval = interval_seconds
        self.message_id = self._load_message_id()

    @staticmethod
    def _load_message_id():
        try:
            with open(config.USAGE_STATUS_FILE, "r", encoding="utf-8") as fh:
                return int(json.load(fh)["message_id"])
        except FileNotFoundError:
            return None
        except Exception:
            log.warning("unreadable %s; posting a new usage message", config.USAGE_STATUS_FILE, exc_info=True)
            return None

    def _persist_message_id(self):
        os.makedirs(os.path.dirname(config.USAGE_STATUS_FILE), exist_ok=True)
        with open(config.USAGE_STATUS_FILE, "w", encoding="utf-8") as fh:
            json.dump({"message_id": self.message_id}, fh)

    async def update(self):
        rows = await db.run(databaseConnector.fetch_bot_command_usage_24h)
        embed = build_embed(rows, int(time.time()) + self.interval)
        if self.message_id is not None:
            try:
                await self.webhook.edit_message(self.message_id, embed=embed)
                return
            except discord.NotFound:
                log.info("usage message %s is gone; posting a new one", self.message_id)
        message = await self.webhook.send(embed=embed, wait=True)
        self.message_id = int(message.id)
        self._persist_message_id()
