---
name: lust-pull-signature
description: The "Most Lusted Pulls" pull signature (npc_id:count tokens) is one string expression repeated in three SQL constants and parsed by the dungeon generator, the dungeon template and the bot. Use when editing FETCH_DUNGEON_LUST_TIMELINE_SQL, the example lust route queries, the lust timeline code in generateDungeonPages.py or dungeon_page.html, or the bot's /dungeon lust command.
kind: coupling
files:
  - backend_scripts/databaseConnector.py
  - backend_scripts/generateDungeonPages.py
  - templates/dungeon_page.html
  - discord_bot/cogs/dungeon.py
---

# Lust pull signature

The `pull_sig` expression of `FETCH_DUNGEON_LUST_TIMELINE_SQL` is a join key. The `HAVING` clauses
of `FETCH_EXAMPLE_LUST_ROUTE_SQL` and `FETCH_EXAMPLE_LUST_ROUTE_ARM_SQL` repeat it character for
character, or the example-route links stop resolving.

Its value reaches three parsers as `top_npcs`: `backend_scripts/generateDungeonPages.py`,
`templates/dungeon_page.html` and `discord_bot/cogs/dungeon.py`. A change to the token format
changes all three.
