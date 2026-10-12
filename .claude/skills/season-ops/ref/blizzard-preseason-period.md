---
name: blizzard-preseason-period
description: Two Blizzard period quirks shift the dashboard week axes or drop a region from the throughput charts, a phantom period that ends at season start and the KR/TW Thursday reset against the Wednesday-only static fetch. Use when week numbers look off by one, a region is missing from the Keys per Week / Key Throughput charts, or when touching fetchSeasonAndPeriodInfo.py, periods.json, season_periods, or the dashboard throughput code.
kind: external
files:
  - backend_scripts/fetchSeasonAndPeriodInfo.py
  - backend_scripts/generateDashboardPage.py
  - data/static/periods.json
  - .github/workflows/buildPages.yml
---

# Blizzard period quirks

## The phantom pre-season period

Blizzard's season details API lists the period that ends exactly at the season start. It has no
runs. `backend_scripts/fetchSeasonAndPeriodInfo.py` filters it out of `periods.json` and out of the
`season_periods` insert.

The insert ignores existing rows, so a phantom row that is already in `season_periods` stays there
and a re-fetch never removes it. When "Keys per Week" starts at week 2 although `periods.json` is
clean, delete the row by hand:
`DELETE FROM season_periods WHERE season = <id> AND end_timestamp <= <season start in ms>;`

## The KR/TW Thursday reset

`getStaticData.yml` fetches periods on Wednesday only, and KR and TW reset on Thursday. From
Thursday to the next Wednesday their current period is unknown, their runs fail the period join,
and both regions vanish from the throughput charts.

`heal_missing_periods` in `backend_scripts/generateDashboardPage.py` repairs this during the build.
Decisions that are easy to undo by accident:

- **It is fail-soft on purpose.** Without Blizzard credentials or network the region is simply
  absent. There is deliberately no fail-loud guard and no extra Thursday cron. The dashboard step
  of `.github/workflows/buildPages.yml` carries the Blizzard credentials for it.
- **It never reruns an aggregation step from the generator.** That would swap an aggregate table
  outside the nightly pipeline ([[aggregation-pipeline]]). Healed periods are injected in memory.
- **`aggregated_key_throughput` stays at one row per region and period.** The week-one daily view
  is drawn from the per-day rollup instead.

Related: [[runs-per-dungeon-rollup]].
