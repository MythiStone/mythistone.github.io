---
name: bot-news-channel-subscriptions
description: How servers subscribe a channel to the daily social post (/news setup|remove|status) and how the post is delivered by CI through the Discord REST API rather than by the bot. Use when editing discord_bot/cogs/news.py, backend_scripts/broadcastDiscordNews.py, the discord-subscribers job in automatedSocialMediaPosts.yml, the bot_news_channels table, or guards.SEASON_EXEMPT_ROOTS.
files:
  - discord_bot/cogs/news.py
  - backend_scripts/broadcastDiscordNews.py
  - .github/workflows/automatedSocialMediaPosts.yml
  - discord_bot/guards.py
---

# News channel subscriptions

Servers pick one channel for the daily social post with `/news setup|remove|status`
(`cogs/news.py`), stored in `bot_news_channels` (PK `guild_id`, so setup again moves it). The bot
never delivers posts itself. The `discord-subscribers` job in `automatedSocialMediaPosts.yml` runs
`broadcastDiscordNews.py`, which reads the table and posts through the Discord REST API with the
`DISCORD_BOT_TOKEN` repo secret. Its embed dict mirrors `embeds.base_embed` by hand (that module
needs discord.py and the lookups), so keep the brand colour, author and footer in sync.

- **Gating.** The group sets `default_permissions(manage_guild)`, `guild_only` and guild-only
  `allowed_installs` (a user-installed bot cannot post in channels), and every subcommand also has a
  runtime `has_permissions(manage_guild=True)` check because server owners can override default
  permissions. `MissingPermissions`/`NoPrivateMessage` render as ephemeral `user_error` replies.
- `guards.SEASON_EXEMPT_ROOTS` lets `/news` past the season guard, which would otherwise block
  setup during the off-season, the period when static posts still go out.
- **Setup** checks View Channel, Send Messages, Embed Links and Attach Files, then sends a
  confirmation into the channel before saving.
- **Cleanup.** `on_guild_remove` deletes the row. The broadcaster deletes it on Discord codes
  10003/10004/50001, keeps it on 50013 (fixable by an admin), and exits non-zero after the loop on
  any other failure.
- `database.sql` is not auto-applied. On prod, create the table and grant the bot's user
  `SELECT, INSERT, UPDATE, DELETE` and the CI `DATABASE_USER` `SELECT, DELETE`. The table is in
  `table_registry.IGNORE_TABLES` and outside the `sp_season_wipe` prefixes.

Related: [[bot-architecture]], [[social-post-pipeline]].
