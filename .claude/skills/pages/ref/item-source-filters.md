---
name: item-source-filters
description: Where an item drops is joined through Blizzard journal ids and travels to the items page as source tokens that Python writes and JS parses. Use when editing pageGeneration.build_source_lookups, generateItemPages.py, the loot code in generateDungeonPages.py, assets/js/items.js or backend_scripts/fetchRaidData.py.
kind: coupling
files:
  - backend_scripts/generateItemPages.py
  - backend_scripts/generateDungeonPages.py
  - backend_scripts/pageGeneration.py
  - assets/js/items.js
  - backend_scripts/fetchRaidData.py
  - backend_scripts/fetchDungeonData.py
---

# Item sources: the join keys

- **Blizzard journal ids are the join key.** The `sources` of `data/static/equippable-items.json`
  carry journal instance and encounter ids. `backend_scripts/fetchDungeonData.py` stores the
  matching `journal_instance_id` per dungeon, and `backend_scripts/fetchRaidData.py` keys raids and
  bosses the same way. Raider.IO raid ids do not join (header comment of `fetchRaidData.py`).
- **Item ids change type between sources.** The usage tables return `item_id` as a string, the
  static JSON holds ints. Normalise before a lookup, or every lookup misses without an error.
- **Source tokens are a format shared by Python and JS.** `pageGeneration.build_source_lookups`
  writes them into `items_index.json`, and `buildSourceOptions` and `parseSourceParam` in
  `assets/js/items.js` read them. A new token kind changes both.
- `raids.json` is absent before a raid releases. The items page degrades with a notice instead of
  raising, which is intended.
