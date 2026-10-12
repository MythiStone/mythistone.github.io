---
name: season-ops
description: "MythiStone season lifecycle and deployment: rollover wipe handshake, season snapshot archive, launch-day gating, Blizzard period quirks, build cadence, artifact-only Pages deploy. Use when touching .github/workflows, season_gate.py, seasonInfo.json/periods.json or the wipe procs."
---

# Season Ops domain

Owner agent `collector-infra` (wipe procs in `database.sql` are reviewed with the `database` skill). Owns `.github/workflows/` (except bot CI), `season_gate.py`, `requestSeasonWipe.py`, `computeBuildPhase.py`.

**Verify:** Workflows cannot run locally: trace each changed step against the scripts it calls and state what was not exercised.

**Look things up, do not read whole files.** The `mythi-kb` MCP tools (or `python .claude/kb/kb.py <tool> <arg>`)
return the slice you need: `kb_table`, `kb_symbol`, `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`.
Open a source file only at the range a tool pointed to.

## Gotchas

Before changing a file listed below, read its gotcha: `ref/<id>.md` in this skill (or `kb_gotcha <id>`).
`kb_file <path>` lists every gotcha for a path across all domains.

| id | rule | files |
|---|---|---|
| `artifact-only-deploy` | Built pages are never committed; the site deploys straight from the Pages artifact and generated paths are gitignored | `.github/workflows/buildPages.yml`, `.gitignore` |
| `blizzard-preseason-period` | How season_periods completeness drives the dashboard week axes and throughput charts - the filtered phantom pre-season period, the week-1 per-day grain, the weekly keys/min headline, the aggregated-sourced region set, and the build-time self-heal for a region's missing current period (KR/TW Thursday reset vs the Wednesday-only fetch) | `backend_scripts/fetchSeasonAndPeriodInfo.py`, `backend_scripts/generateDashboardPage.py`, `data/static/periods.json` |
| `build-cadence-phases` | buildPages schedules daily/every-3-days/weekly by phase, gated on days since the most recent content update (season start or a .5/.7 patch) | `.github/workflows/buildPages.yml`, `backend_scripts/computeBuildPhase.py` |
| `season-launch-day-presentation` | How the social auto-poster and the Discord bot present the pre-season gap vs the season's first 24h, and why launch day needs its own time-based gate | `backend_scripts/season_gate.py`, `backend_scripts/social_posts/pipeline.py`, `backend_scripts/image_generation/season_countdown.py`, `discord_bot/guards.py`, `discord_bot/errors.py`, `discord_bot/embeds.py` |
| `season-rollover-wipe` | How the automated per-season DB wipe works as a CI-intent + collector-pause + MySQL-event handshake keyed off seasonInfo.json | `.github/workflows/seasonRolloverWipe.yml`, `backend_scripts/requestSeasonWipe.py`, `backend_scripts/database.sql`, `backend_scripts/collectLeaderboardData.py`, `data/static/seasonInfo.json` |
| `season-snapshot-archive` | Each season's built _site is force-pushed to a season-<id> branch in a separate archive repo as cold storage before the DB wipe | `.github/workflows/buildPages.yml` |
| `season-wipe-invariants` | Four hard-won invariants of the season-rollover wipe handshake | `backend_scripts/collectLeaderboardData.py`, `backend_scripts/database.sql` |
