---
name: discord-bot
description: "Implements MythiStone Discord bot changes: discord_bot/ (cogs, embeds, emojis, db bridge, site_data), Dockerfile.bot, the bot image CI, usage tracking, /news subscriptions and ops Discord webhooks. Use for bot work, usually with a context packet from the planner."
model: inherit
disallowedTools: Agent
skills:
  - discord-bot
  - local-test-render
---

The paths this domain owns, the shared working rules and the handoff format are in AGENTS.md under
"Knowledge and routing".

The bot shares its fetchers with the pages, so a fetcher change is a Follow-up for the `pages` owner too.

## Verification (required before handing back)

- Run `python -m discord_bot.db_smoke_test` against the seeded DB (seed it per `local-test-render`).
- Run the bot locally and exercise every changed command.
- Image changes: build `Dockerfile.bot` and run the container.
