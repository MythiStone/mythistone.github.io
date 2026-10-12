---
name: runs-per-dungeon-rollup
description: "The production DB runs at full load and cannot be scaled, so season-wide run counts are read from nightly rollups and a build never repeats or parallelizes a heavy query. Use when adding a season-wide run count, editing fetch_runs_per_dungeon*, fetch_total_season_runs, fetch_runs_per_period_per_day, the record-run fetchers, or the overview-image query paths."
kind: coupling
files:
  - backend_scripts/databaseConnector.py
  - backend_scripts/database.sql
  - backend_scripts/image_generation/*
  - backend_scripts/generateDashboardPage.py
---

# Run counts under a DB at full load

A full-season scan of `runs` takes minutes at 10 to 20 million rows, and the production DB has no
headroom. Three rules follow:

- **A season-wide run count reads a nightly rollup through `_fetch_runs_rollup_with_fallback`.** A
  new reader uses the same helper and gets its rollup from a new `sp_agg_*` step
  ([[aggregation-pipeline]]).
- **A page generator fetches once and passes the rows on.** The overview renderers in
  `backend_scripts/image_generation/` take pre-fetched data as keyword arguments and only query
  when they get `None`, which keeps the standalone social-post callers working.
- **Queries are not run in parallel.** Threads are for the keystone.guru thumbnail HTTP calls,
  which cost the DB nothing. Those thumbnails differ on every build and cannot be cached.
