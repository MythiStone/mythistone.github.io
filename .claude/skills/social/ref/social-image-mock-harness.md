---
name: social-image-mock-harness
description: How to verify the social image renderers in backend_scripts/image_generation/ locally against the seeded local test DB. Use when changing anything under image_generation/ (comp_overview, dungeon_overview, item_overview, dungeon_tierlist, mplus_run, config, mpl_setup).
kind: workflow
files:
  - backend_scripts/image_generation/*
---

# Verifying the social image renderers

The renderers in `backend_scripts/image_generation/` take their DB rows from the caller. Verify
them with real rows from the seeded local DB, never with hand-built dicts, so a query or shape
drift is caught.

- `discord_bot/db_smoke_test.py` already does this for every renderer the bot shares. Seed, export
  the printed `DATABASE_*`, run it ([[local-test-render]]).
- For one renderer: fetch its rows through `databaseConnector` and call it with `out_path` in a
  scratch directory. The SimC tierlist preview takes its rows directly and needs no DB.
- Icons are optional. Without `data/icons` the tiles are skipped and a valid PNG still lands.

Related: [[bot-architecture]].
