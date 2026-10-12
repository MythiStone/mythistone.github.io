---
name: gear-and-talent-data-retention
description: Equipped-gear rows and talent information are purged after about 2 weeks, so every aggregate over them is a full rebuild, never watermark-incremental, and test data must be recent. Use when adding or changing an aggregate that joins equipment, bonus or talent data, or when seeded pages come out empty.
kind: coupling
files:
  - backend_scripts/database.sql
  - backend_scripts/localDev/seeders.py
---

# Gear and talent data lives for two weeks

`ev_purge_old_run_details_incremental` discards equipment, bonus and talent data older than about
two weeks. Two things follow elsewhere:

- **An aggregate that joins this data is a full rebuild** through the shadow swap
  ([[aggregation-pipeline]]). The watermark pattern of `summary_meta` only ever adds, so purged runs
  would stay counted forever. A remaining watermark aggregate over per-character gear or talents
  that feeds a "current state" display is a bug to fix, not a model to copy.
- **The aggregates also ignore older rows on the read side**, so the runs written by
  `backend_scripts/localDev/seeders.py` must be timestamped inside the last 14 days.

How a purged member drops out of the talent aggregates: [[dedup-dictionary-hash-contract]].
