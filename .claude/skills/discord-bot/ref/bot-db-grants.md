---
name: bot-db-grants
description: The bot and CI connect to production MySQL with their own users, and database.sql is not applied to the server automatically, so a table the bot touches is created and granted by hand. Use when the bot gains a table or a write, or when usage rows or /news subscriptions fail only in production.
kind: external
files:
  - discord_bot/usage_stats.py
  - discord_bot/cogs/news.py
  - backend_scripts/broadcastDiscordNews.py
---

# Production grants for bot tables

Create the table on the server by hand ([[add-database-table]]), then grant:

| Table | Bot `DATABASE_USER` | CI `DATABASE_USER` |
|---|---|---|
| `bot_command_usage` | `INSERT, SELECT` | none |
| `bot_news_channels` | `SELECT, INSERT, UPDATE, DELETE` | `SELECT, DELETE` |

A missing table or grant shows only in production: every command logs a failed usage insert and
the usage embed update fails on each tick.
