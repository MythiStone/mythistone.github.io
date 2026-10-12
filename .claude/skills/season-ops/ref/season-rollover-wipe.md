---
name: season-rollover-wipe
description: The per-season DB wipe is a handshake between a CI workflow, the collector and a MySQL event, and its invariants are documented at each of those sites. Use when touching seasonRolloverWipe.yml, requestSeasonWipe.py, wipe_control, ev_season_wipe / sp_season_wipe / sp_truncate_with_retry in database.sql, wipe_watch or SEASON_FLOOR in the collector, or the collector's restart policy.
kind: coupling
files:
  - .github/workflows/seasonRolloverWipe.yml
  - backend_scripts/requestSeasonWipe.py
  - backend_scripts/database.sql
  - backend_scripts/collectLeaderboardData.py
  - data/static/seasonInfo.json
  - docker-compose.yml
---

# Season rollover wipe

Three actors, and each documents its own part:

| Actor | Where | Read |
|---|---|---|
| CI raises the request | `.github/workflows/seasonRolloverWipe.yml`, `backend_scripts/requestSeasonWipe.py` | the workflow comments and the script header |
| The collector pauses and acks | `wipe_watch` in `backend_scripts/collectLeaderboardData.py` | its docstring and the `SEASON_FLOOR` comment |
| MySQL clears | `ev_season_wipe`, `sp_season_wipe`, `sp_truncate_with_retry` | their comments |

What spans them:

- **`request_season` is the season rolled into**, a boundary marker, not the season to delete.
- **The collector does not resume after a wipe, it exits.** It resolves season and period once per
  process, so it depends on the `restart: always` policy in `docker-compose.yml` to come back.
- **Order:** the built site of the outgoing season is archived first
  ([[season-snapshot-archive]]). The workflow blocks when that archive branch is missing.

Verify SQL changes with [[verify-database-sql]].
