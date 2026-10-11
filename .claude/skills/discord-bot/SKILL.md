---
name: discord-bot
description: "The dockerized MythiStone Discord slash-command bot (discord_bot/): cogs, embeds, emojis, site JSON and DB access, usage tracking, /news subscriptions, ops webhooks. Use when editing discord_bot/, Dockerfile.bot, buildBotImage.yml or Discord webhook handling."
---

# Discord Bot domain

Owner agent `discord-bot`. Owns `discord_bot/`, `Dockerfile.bot`, `entrypoint_bot.sh`, `.github/workflows/buildBotImage.yml`, `discordHandler.py`, `broadcastDiscordNews.py`.

**Verify:** `python -m discord_bot.db_smoke_test` against the seeded DB (the `local-test-render` skill seeds it), then run the bot and exercise the changed commands.

**Look things up, do not read whole files.** The `mythi-kb` MCP tools (or `python .claude/kb/kb.py <tool> <arg>`)
return the slice you need: `kb_table`, `kb_symbol`, `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`.
Open a source file only at the range a tool pointed to.

## Gotchas

Before changing a file listed below, read its gotcha: `ref/<id>.md` in this skill (or `kb_gotcha <id>`).
`kb_file <path>` lists every gotcha for a path across all domains.

| id | rule | files |
|---|---|---|
| `bot-architecture` | The standalone dockerized Discord slash-command bot in discord_bot/ that serves MythiStone stats, plus its application-owned custom-emoji layer | `discord_bot/*`, `Dockerfile.bot`, `.github/workflows/buildBotImage.yml` |
| `bot-command-usage-tracking` | How the Discord bot records every slash-command invocation in bot_command_usage and renders the self-updating 24h usage embed | `discord_bot/usage_stats.py`, `discord_bot/errors.py`, `discord_bot/bot.py` |
| `bot-news-channel-subscriptions` | How servers subscribe a channel to the daily social post (/news setup|remove|status) and how the post is delivered by CI through the Discord REST API rather than by the bot | `discord_bot/cogs/news.py`, `backend_scripts/broadcastDiscordNews.py`, `.github/workflows/automatedSocialMediaPosts.yml`, `discord_bot/guards.py` |
| `ops-discord-channels` | Which Discord webhook carries which ops output (the self-editing collector status and bot usage embeds vs. alerts, entrypoint pings and watchtower), and the rules that keep the embeds from being orphaned or buried | `backend_scripts/discordHandler.py`, `discord_bot/usage_stats.py`, `entrypoint.sh`, `entrypoint_bot.sh`, `docker-compose.yml` |
