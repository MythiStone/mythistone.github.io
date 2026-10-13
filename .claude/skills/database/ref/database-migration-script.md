---
name: database-migration-script
description: Nothing applies backend_scripts/database.sql to the production server, so every change to it ships with a migration script under backend_scripts/migrations/ that the user runs there. Use when changing a table, routine or event in database.sql, or when production lacks something database.sql defines.
kind: workflow
files:
  - backend_scripts/database.sql
  - backend_scripts/migrations/*
---

# A database change ships with a migration script

`backend_scripts/database.sql` describes the schema, and nothing applies it to the production
server. Every change to a table, routine or event there comes with one script in
`backend_scripts/migrations/` that takes a server from the previous `database.sql` to the new one.
The user runs it. A change without its script is not done.

1. Name it `<yyyy-mm-dd>_<what>.sql`. The header lists what it adds, changes and drops, and the
   command that runs it.
2. Copy table and routine definitions from `database.sql` unchanged, so the server and the file
   cannot drift. The script runs in the mysql client, so routines need `DELIMITER` blocks, which
   `database.sql` does not have.
3. Make it safe to run twice: `CREATE TABLE IF NOT EXISTS`, `DROP ... IF EXISTS` before a `CREATE`,
   an `ALTER` only when the column or index is missing.
4. Order it so the server works after every statement: a table before the routine that fills it,
   a routine before the `sp_run_agg_pipeline` that calls it.
5. When it touches anything the nightly pipeline or the season wipe uses, it takes the
   `agg_pipeline` lock first and stops when it cannot, the way `ev_nightly_agg_pipeline` skips a
   run. Replacing a proc under a running pipeline mixes old and new steps
   ([[aggregation-pipeline]]).
6. Grants are per server and not in `database.sql`. End the script with the grants the new objects
   need as a commented template ([[bot-db-grants]]).
7. Keep a backfill that scans a large table out of the main path: a commented, optional last
   step, with its cost in the comment.

Test it the way production will run it: bring an ephemeral MySQL 8 to the previous `database.sql`
([[verify-database-sql]]), feed the script to the mysql client, run it a second time, then run the
routines it touched. The mysql client drops comments from routine bodies, so compare them with
`database.sql` ignoring comments and whitespace.

Related: [[add-database-table]].
