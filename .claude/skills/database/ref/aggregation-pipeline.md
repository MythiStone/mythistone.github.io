---
name: aggregation-pipeline
description: How the nightly aggregation runs and how to add a new aggregate. Use when editing aggregation stored procs (sp_agg_*, sp_run_agg_pipeline, sp_swap_public_table) in backend_scripts/database.sql, adding an aggregate table, or debugging morning lock-ups / RENAME contention.
files:
  - backend_scripts/database.sql
  - backend_scripts/aggPipelineHealth.py
---

# Aggregation pipeline (shadow swap)

Aggregation runs as stored procedures (`sp_agg_*`) called sequentially by `ev_nightly_agg_pipeline` -> `sp_run_agg_pipeline`, each step through `sp_run_agg_step('<step>')`. Everything lives in `backend_scripts/database.sql`; there is no migrations directory. Per-step timing/errors go to `agg_pipeline_log`.

Rebuilds use shadow tables (`<t>_new`) plus atomic `RENAME`, never `TRUNCATE`. Reason: a `TRUNCATE`'s exclusive metadata-lock request queued behind a long reader wedges the whole server (MDL waits use `lock_wait_timeout`, which defaults to one year); that is what morning lock-ups look like. `aggregated_*` tables carry no FKs, so `CREATE TABLE ... LIKE` shadows work.

How to add a new aggregate: write a new `sp_agg_<step>` proc plus one `CALL sp_run_agg_step('<step>')` line in the pipeline. Never add a new standalone `TRUNCATE` event. Route table swaps through `sp_swap_public_table(p_base)`, which does the `RENAME`+`DROP` with escalating `lock_wait_timeout` (60->300s), logs the blocking session into `agg_lock_diag` via `sp_capture_lock_holders`, and after 3 failed attempts calls `sp_kill_lock_holders`, which KILLs only idle (`PROCESSLIST_COMMAND='Sleep'`) MDL holders so it can never hit the always-active collector. Use a short `lock_wait_timeout` plus retry (`sp_run_agg_step` retries on 1205 with 30s backoff, 5 attempts), NOT a long timeout, since a long timeout parks the exclusive RENAME in the fair MDL queue and stacks readers behind it (the freeze).

Read-only Python scripts must call `databaseConnector.configure_read_session(conn, cursor)` right after opening the connection, see [[pooled-connection-gotchas]]. Gear-joined aggregates must be full rebuilds, see [[gear-and-talent-data-retention]].

The live server can hold events/tables that are not in `database.sql`. When auditing, compare `information_schema.events` / `SHOW TABLES` against the repo file. Verify proc changes with [[verify-database-sql]].
