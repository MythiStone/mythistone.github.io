---
name: frontend-json-dungeon-keys
description: The in-memory frontend_json keys each comp's dungeons map by INT, but on-disk comps_index.json keys them by STR, so per-dungeon lookups must handle both. Use when reading comp['dungeons'] in compArchetypes.py or generateCompPage.py, or when per-dungeon archetype lists come back empty.
kind: coupling
files:
  - backend_scripts/compArchetypes.py
  - backend_scripts/generateCompPage.py
---

# Comp dungeon maps: int keys in memory, string keys on disk

`generateCompPage.calculate_comp_stats` keys each comp's `dungeons` map by integer. Written to
`comps_index.json` the keys become strings. Code that reads the in-memory list, like
`compArchetypes.build_dungeon_archetypes`, and code that reads the file therefore see different key
types. A new reader handles both, as `compArchetypes._load_records` does.

A test that loads the JSON from disk hides the bug: convert the dungeon keys back to int first, or
the lookup passes there and returns nothing in the real build.

Related: [[spec-team-comps]], [[top-trends-bar]].
