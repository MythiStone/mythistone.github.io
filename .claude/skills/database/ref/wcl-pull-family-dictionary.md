---
name: wcl-pull-family-dictionary
description: The Warcraft Logs pull family text, its hash and its dictionary row tie the collector and the nightly aggregates together. Use when changing how pulls are grouped into families or writing a family-keyed wcl table.
kind: coupling
files:
  - backend_scripts/wclPullBuilder.py
  - backend_scripts/wclCollector.py
  - backend_scripts/databaseConnector.py
  - backend_scripts/database.sql
---

# Pull family keys must agree everywhere

- **Same text.** `Pull.family_key` and `sp_wcl_family_map` build the family key independently, and
  spec tables and dungeon tables only line up on the page when both produce identical text.
- **Same hash.** `wcl_family_id` must stay byte-identical to the SQL form in the migration that
  backfills `wcl_pull_families`, or one family splits into two entries.
- **Same transaction.** `sp_agg_wcl_cooldowns` inner-joins `wcl_pull_families`, so `delta_rows` has
  to send the `upsert_wcl_pull_families` rows with the family-keyed daily rows. A daily row without
  its dictionary row vanishes from the aggregates without an error.

Related: [[dedup-dictionary-hash-contract]].
