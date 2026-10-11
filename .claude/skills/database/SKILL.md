---
name: database
description: "MythiStone MySQL layer: schema in backend_scripts/database.sql, every query in databaseConnector.py, aggregation stored procs, the localDev seeder table registry. Use when adding or changing a table, query, proc or aggregate."
---

# Database domain

Owner agent `database`. Owns `backend_scripts/database.sql`, `backend_scripts/databaseConnector.py`, `backend_scripts/localDev/`, `aggPipelineHealth.py`.

**Verify:** Procs: the `verify-database-sql` gotcha (ephemeral MySQL 8). Schema growth: the seeder's `classify_all` must pass. Pages that read the change: the `local-test-render` skill.

**Look things up, do not read whole files.** The `mythi-kb` MCP tools (or `python .claude/kb/kb.py <tool> <arg>`)
return the slice you need: `kb_table`, `kb_symbol`, `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`.
Open a source file only at the range a tool pointed to.

## Gotchas

Before changing a file listed below, read its gotcha: `ref/<id>.md` in this skill (or `kb_gotcha <id>`).
`kb_file <path>` lists every gotcha for a path across all domains.

| id | rule | files |
|---|---|---|
| `add-database-table` | What else to update when you add a new table to backend_scripts/database.sql | `backend_scripts/database.sql`, `backend_scripts/localDev/table_registry.py`, `backend_scripts/localDev/seed_test_db.py` |
| `aggregation-pipeline` | How the nightly aggregation runs and how to add a new aggregate | `backend_scripts/database.sql`, `backend_scripts/aggPipelineHealth.py` |
| `comp-routes-specs-fallback` | fetch_comp_routes collapses runs by physical route_signature and the surfaced winner borrows a signature-sibling's comp when its own run logged no route_specs | `backend_scripts/databaseConnector.py` |
| `dedup-dictionary-hash-contract` | Talents and bonus ids are stored deduplicated in content-hash dictionaries (talent_sets / bonus_sets) whose set_id must be produced identically by the Python collector and by any SQL that writes them, plus the purge-NULL parity rule that keeps talent aggregations correct | `backend_scripts/commonUtils.py`, `backend_scripts/collectLeaderboardData.py`, `backend_scripts/database.sql`, `backend_scripts/databaseConnector.py` |
| `gear-and-talent-data-retention` | Equipped-gear rows and talent information are purged after ~2 weeks, so aggregations must be full rebuild, never watermark-incremental | `backend_scripts/database.sql` |
| `keystone-guru-mapping-data` | What route_data.mapping_version means and how the "Most Skipped NPCs" card is computed today | `backend_scripts/generateDungeonPages.py`, `templates/dungeon_page.html`, `backend_scripts/database.sql` |
| `pooled-connection-gotchas` | Two mysql.connector pooled-connection traps in MythiStone | `backend_scripts/databaseConnector.py`, `backend_scripts/collectLeaderboardData.py`, `backend_scripts/simcBis.py`, `discord_bot/db.py` |
| `runs-per-dungeon-rollup` | Season-wide run counts come from three nightly rollups (aggregated_runs_per_dungeon_per_level, aggregated_runs_per_period_per_day, aggregated_record_runs) instead of full-season runs scans, and every reader falls back to the live scan when its rollup is missing or empty | `backend_scripts/databaseConnector.py`, `backend_scripts/database.sql`, `backend_scripts/image_generation/*`, `backend_scripts/generateDashboardPage.py` |
| `table-storage-placement` | Where the large MySQL tables physically live (general tablespaces vs. per-table DATA DIRECTORY on specific host drives) and the only working way to move a table to another drive | `backend_scripts/database.sql` |
| `verify-database-sql` | How to syntax and runtime verify backend_scripts/database.sql stored procedures against an ephemeral MySQL 8 Docker container | `backend_scripts/database.sql` |
