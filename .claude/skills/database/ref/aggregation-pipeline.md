---
name: aggregation-pipeline
description: How to add or change a nightly aggregate without wedging the server, and what every reader of the aggregate tables owes the pipeline. Use when editing aggregation stored procs (sp_agg_*, sp_run_agg_pipeline, sp_swap_public_table) in backend_scripts/database.sql, adding an aggregate table, opening a new read-only DB connection, or debugging morning lock-ups / RENAME contention.
kind: workflow
files:
  - backend_scripts/database.sql
  - backend_scripts/aggPipelineHealth.py
---

# Adding or changing an aggregate

1. Write `sp_agg_<step>`. Build into the `<table>_new` shadow and swap it in with
   `sp_swap_public_table`.
2. Add one `CALL sp_run_agg_step('<step>')` line to `sp_run_agg_pipeline`.
3. Verify with [[verify-database-sql]].

Rules the procs cannot enforce:

- **Never rebuild with `TRUNCATE`, and never add a standalone rebuild event.** The comment in
  `sp_truncate_with_retry` explains what a queued exclusive metadata lock does to the server.
- **Keep lock waits short and retry.** A long `lock_wait_timeout` parks the exclusive `RENAME` in
  the fair metadata-lock queue and every reader stacks up behind it.
- **An aggregate table has no foreign key.** The `CREATE TABLE ... LIKE` shadow swap depends on it.
- **Every connection that reads these tables calls `databaseConnector.configure_read_session`
  first**: generators, the bot, one-off scripts. An idle open transaction holds the lock the swap
  needs ([[pooled-connection-gotchas]]).
- An aggregate over gear or talents is a full rebuild ([[gear-and-talent-data-retention]]).

The server can hold events and tables that are not in `database.sql`. When auditing, compare
`information_schema.events` and `SHOW TABLES` with the file.
