---
name: bot-command-usage-tracking
description: How the Discord bot records every slash-command invocation in bot_command_usage and renders the self-updating 24h usage embed. Use when editing discord_bot/usage_stats.py, discord_bot/errors.py outcome handling, MythistoneBot.on_app_command_completion, the bot_command_usage table, or when the usage embed is missing, duplicated or failing.
---

# Bot command-usage tracking

Every slash-command invocation writes one `bot_command_usage` row (`season`, qualified `command`,
`outcome`). `MythistoneBot.on_app_command_completion` records `ok`, and
`errors.on_app_command_error` records the outcome from `errors._usage_outcome`: `blocked` (season
guard), `user_error` (validation, cooldown), `error` (`BotError` family) or `crash` (unhandled).

- Inserts are fire-and-forget tasks (`usage_stats.record`) and never delay or break a reply. The
  bot's `configure_read_session` sets autocommit=1, which is what makes these writes commit.
- `usage_stats.UsageReporter` edits one webhook message every `USAGE_EMBED_INTERVAL_MINUTES` with
  the last 24h. The webhook is `STATUS_WEBHOOK_URL`, falling back to `WEBHOOK_URL`
  (`config.load_env`), and the loop runs only when one of them is set. Its message id lives in
  `data/bot_cache/usage_status.json` (docker volume), and a deleted message is re-posted. Channel
  layout and the re-post rule are in [[ops-discord-channels]].
- The table name sits deliberately outside the `sp_season_wipe` prefixes, so usage history survives
  wipes. It is in `table_registry.IGNORE_TABLES` (correct empty in the seed, see
  [[add-database-table]]).
- `database.sql` is not auto-applied. On prod, create the table manually and grant the bot's
  `DATABASE_USER` `INSERT, SELECT` on it. Until then, every insert logs a warning and the embed
  update fails each tick (also logged).

Related: [[discord-bot]].
