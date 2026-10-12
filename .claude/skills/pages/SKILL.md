---
name: pages
description: "MythiStone page generation: generate*.py, Jinja templates and macros, shared generator modules (pageGeneration, commonUtils, aggregateData, compArchetypes) and page-specific data rules for spec, item, dungeon, comps, analyzer, tierlist, routes, trends. Use when changing what a page renders."
---

# Pages domain

Owner agent `pages`. Owns `backend_scripts/generate*.py` (except social/simc profile generators), `templates/`, the shared generator modules. Client-side conventions live in the `frontend` skill.

**Verify:** Always test-render the affected page: the `local-test-render` skill.

**Look things up, do not read whole files.** The `mythi-kb` MCP tools (or `python .claude/kb/kb.py <tool> <arg>`)
return the slice you need: `kb_table`, `kb_symbol`, `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`.
Open a source file only at the range a tool pointed to.

## Gotchas

Before changing a file listed below, read its gotcha: `ref/<id>.md` in this skill (or `kb_gotcha <id>`).
`kb_file <path>` lists every gotcha for a path across all domains.

| id | rule | files |
|---|---|---|
| `analyzer-page` | Covers the "Am I Meta?" analyzer page: client-side talent decode/compare and the Gear/Talents card sync | `assets/js/analyzer.js`, `assets/js/loadout-view.js`, `backend_scripts/generateAnalyzerPage.py`, `assets/css/analyzer.css`, `templates/analyzer.html` |
| `build-new-page` | How to scaffold a NEW static page so its markup, includes, and asset wiring match existing pages | `backend_scripts/pageGeneration.py`, `templates/base_template.html`, `templates/header_imports.html`, `templates/javascript_imports.html` |
| `dungeon-best-loot-card` | Covers the dungeon page "Best Loot From This Dungeon" card and item→dungeon source resolution | `backend_scripts/generateDungeonPages.py`, `templates/dungeon_page.html` |
| `dungeon-npc-portrait-icons` | How the dungeon page's per-NPC portrait icons are sourced — MDT static Lua for npc_id→displayId, then Wowhead zamimg webthumbs for the image (100% coverage) | `backend_scripts/fetchNpcIcons.py`, `backend_scripts/generateDungeonPages.py`, `templates/dungeon_page.html` |
| `enchant-link-icon-rune-fallback` | Every enchant link/icon render surface must fall back to spellId/spellIcon because DK weapon runes have no scroll itemId | `templates/spec_page.html`, `templates/item.html` |
| `enchant-lookup-filter` | How enchants are filtered for display (catalog membership + current expansion + equipRequirements slot fit) through one shared commonUtils util used by both the spec and item pages | `backend_scripts/generateSpecPages.py`, `backend_scripts/generateItemPages.py`, `backend_scripts/commonUtils.py` |
| `frontend-json-dungeon-keys` | The in-memory frontend_json keys each comp's dungeons map by INT, but on-disk comps_index.json keys them by STR, so per-dungeon lookups must handle both | `backend_scripts/compArchetypes.py`, `backend_scripts/generateCompPage.py` |
| `item-quality-from-bonus` | Item quality/color (rarity) is resolved from the item's bonus ids, not the base item quality, on both the spec page and the items page, through one shared commonUtils helper | `backend_scripts/generateSpecPages.py`, `backend_scripts/generateItemPages.py`, `backend_scripts/commonUtils.py`, `templates/item.html`, `assets/js/items.js` |
| `item-source-filters` | Covers the items page "Drops from" source filter, its flat source-token spine, and raid metadata discovery | `backend_scripts/generateItemPages.py`, `backend_scripts/pageGeneration.py`, `assets/js/items.js`, `backend_scripts/fetchRaidData.py` |
| `page-data-and-scripts` | Page JS and CSS live in assets/js/<page>.js and assets/css/<page>.css, never inline in templates, and server data reaches the script either as a fetched JSON file or an inline application/json block depending on how the page consumes it | `assets/js/dashboard.js`, `assets/js/comps.js`, `backend_scripts/generateDashboardPage.py`, `backend_scripts/generateCompPage.py` |
| `route-accordion-macro` | The keystone.guru route accordion item is one shared Jinja macro used by the spec, routes and dungeon pages, and assets/js/routes-finder.js must mirror its full markup | `templates/_route_macros.html`, `templates/spec_page.html`, `templates/find_routes.html`, `templates/dungeon_page.html`, `assets/js/routes-finder.js` |
| `spec-team-comps` | Covers the spec page "Popular Team Comps" card and its archetype ranking | `backend_scripts/compArchetypes.py`, `backend_scripts/generateSpecPages.py`, `templates/_team_comp_macros.html`, `templates/comps.html` |
| `tierlist-gear-modal` | The sim tierlist's per-bar gear/talents modal is client-rendered from a tierlist_gear.json emitted by the profile builder and reuses the analyzer's shipped catalogs | `assets/js/tierlist-modal.js`, `assets/js/loadout-view.js`, `assets/css/loadout-view.css`, `backend_scripts/generateSimcProfiles.py`, `backend_scripts/generateTierlistPage.py`, `templates/simc_tierlist.html` |
| `top-trends-bar` | Covers the site-wide "Top Trends" bar: weekly trend_snapshot baseline, the Python snapshotTrends writer, per-page contextual feeds, and the marquee JS | `backend_scripts/snapshotTrends.py`, `backend_scripts/pageGeneration.py`, `templates/trends_bar.html`, `templates/top_chrome.html`, `assets/js/trends-bar.js` |
