---
name: runs-per-dungeon-rollup
description: "Season-wide run counts come from three nightly rollups (aggregated_runs_per_dungeon_per_level, aggregated_runs_per_period_per_day, aggregated_record_runs) instead of full-season runs scans, and every reader falls back to the live scan when its rollup is missing or empty. Use when editing fetch_runs_per_dungeon*, fetch_total_season_runs, fetch_runs_per_period_per_day, the record-run fetchers, the rollup procs, or the overview-image query paths."
files:
  - backend_scripts/databaseConnector.py
  - backend_scripts/database.sql
  - backend_scripts/image_generation/*
  - backend_scripts/generateDashboardPage.py
---

# Runs rollups with live-scan fallback

Season-wide run counts are read from three nightly rollups (current season only, shadow + RENAME like [[aggregation-pipeline]]) instead of full-season `runs ⋈ dungeon_data` scans, which take ~2-3 min each at 10-20M runs and would otherwise run ~12x per build (worst case `createDungeonOverviewImg` scanning per level once per dungeon):

| Rollup | Built by | Readers |
|---|---|---|
| `aggregated_runs_per_dungeon_per_level` | `sp_agg_runs_per_dungeon_per_level` | `fetch_runs_per_dungeon`, `fetch_runs_per_dungeon_per_level[_above_level]`, `fetch_total_season_runs` |
| `aggregated_runs_per_period_per_day` | `sp_agg_runs_per_period_per_day` | `fetch_runs_per_period_per_day`, `fetch_dungeon_timed_runs_last_two_periods` |
| `aggregated_record_runs` | `sp_agg_record_runs` | the record-run fetchers via `_fetch_record_run_rows` |

Why: the DB runs at 100% load and cannot be scaled, so every redundant query removed is a direct win. Query parallelism is deliberately avoided for the same reason (keystone.guru thumbnail HTTP is threaded instead, zero DB load). Thumbnails cannot be cached across builds (they differ every time).

How to apply: every reader goes through `_fetch_runs_rollup_with_fallback` in `databaseConnector.py`, which falls back to the live scan when the rollup table is missing (`ER_NO_SUCH_TABLE`) OR holds nothing for the requested season (e.g. the season flipped before the nightly pipeline ran). A new rollup reader must use the same helper. The overview-image renderers accept pre-fetched data via keyword args (`None` = fetch, preserving standalone social-post callers), and the page generators pass everything through so image steps do zero duplicate queries.
