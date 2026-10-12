---
name: bot-architecture
description: The Discord bot is a third consumer of backend modules, static lookups and page logic that the collector and the page generators own, so a change made for them must keep the bot importing, querying and rendering. Use when changing a backend module that Dockerfile.bot copies (databaseConnector.py, commonUtils.py, image_generation/ and the others in its COPY list) for any caller, when the bot reads a new data/static lookup, or when changing the analyzer scoring or the house embed style.
kind: coupling
files:
  - discord_bot/*
  - Dockerfile.bot
  - backend_scripts/databaseConnector.py
  - backend_scripts/commonUtils.py
  - backend_scripts/chartData.py
  - backend_scripts/tierMath.py
  - backend_scripts/season_gate.py
  - backend_scripts/computeBuildPhase.py
  - backend_scripts/image_generation/*
  - assets/js/analyzer.js
---

# What the bot shares with the collector and the pages

- **Shared backend modules.** `Dockerfile.bot` copies backend modules and `image_generation/` into
  the bot image, and the cogs call their fetchers and renderers directly. Changing one of them for
  the collector or a page changes the bot too: a new third-party import needs the `pip install` in
  `Dockerfile.bot`, a new first-party import needs its `COPY` list, and a renamed fetcher or a
  changed return shape breaks the cogs that read it. The symbol lookup of a fetcher lists those
  cogs. Run `discord_bot/db_smoke_test.py` after such a change.
- **Static lookups.** A `data/static` file read by `discord_bot/lookups.py` or by a shared module
  must be in the `COPY` list of `Dockerfile.bot`. Without it the bot passes locally, where the whole
  repo is present, and fails in the container.
- **Hand-kept mirrors.** `discord_bot/cogs/analyze.py` reimplements the scoring of
  `assets/js/analyzer.js`, and `backend_scripts/broadcastDiscordNews.py` rebuilds the embed of
  `embeds.base_embed` as a plain dict. A change to the pass rules or to the brand color, author or
  footer belongs in both ends.

The season gate the bot shares with the social poster: [[season-launch-day-presentation]].
