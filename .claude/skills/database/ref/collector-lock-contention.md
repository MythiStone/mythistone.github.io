---
name: collector-lock-contention
description: Every scheduled job in database.sql runs next to the collector's open write transaction, so it reads collector tables without row locks, takes shared rows in primary-key order and survives losing a deadlock. Use when adding or changing an event or proc that reads or deletes rows of runs, run_members, members, equipment, talent_sets or bonus_sets, when changing the insert order in insert_run_batch, or when a 1213 or 1205 shows up in agg_pipeline_log or the collector log.
kind: coupling
files:
  - backend_scripts/database.sql
  - backend_scripts/databaseConnector.py
---

# Scheduled jobs and the collector's write transaction

The collector is never paused for the nightly pipeline or the purge events. `insert_run_batch`
keeps a row lock on everything it wrote, dictionary rows included, until `run_in_transaction`
commits. A job that touches the same rows follows three rules:

- **Read collector tables below REPEATABLE READ.** At the server default the `SELECT` half of an
  `INSERT ... SELECT`, and a subquery inside an `UPDATE` or `DELETE`, takes a shared lock on every
  row it reads. For a season-wide scan of `runs` that is the whole season, and every collector
  insert in that window blocks or deadlocks. An event starts on a fresh session at the server
  default, so each one sets its own level, as `sp_agg_session_setup` and
  `ev_purge_old_run_details_incremental` do.
- **Take dictionary rows in primary-key order.** `sp_agg_talent_sets_gc` and
  `sp_agg_bonus_sets_gc` scan in that order and `insert_run_batch` sorts its rows to match. Two
  sessions taking the same rows in different orders deadlock.
- **Expect to lose a deadlock.** InnoDB picks the victim. `run_in_transaction` and
  `sp_run_agg_step` re-run their unit, so anything behind either must be safe to run again from
  the start. A step that fails for good fails the site build through
  `backend_scripts/aggPipelineHealth.py`.

To see what a job collided with, read the `LATEST DETECTED DEADLOCK` section of
`SHOW ENGINE INNODB STATUS` on the server. It keeps only the most recent deadlock, and a deadlock
the collector lost appears nowhere else.

Related: [[aggregation-pipeline]], [[dedup-dictionary-hash-contract]], [[pooled-connection-gotchas]].
