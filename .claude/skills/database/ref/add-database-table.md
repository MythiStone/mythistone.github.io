---
name: add-database-table
description: What else changes when backend_scripts/database.sql grows a base table (the seeder registry, seed rows, the production server), and what the table name decides. Use whenever the schema grows a base table, or when the local seeder fails with UnknownTableError.
kind: workflow
files:
  - backend_scripts/database.sql
  - backend_scripts/localDev/table_registry.py
  - backend_scripts/localDev/seed_test_db.py
---

# Adding a table to database.sql

1. **Pick the name on purpose.** `sp_season_wipe` truncates by name prefix and
   `table_registry.classify_all` places some name prefixes on its own. The name decides whether the
   table is emptied every season and whether it needs a seeder. A table that must survive a wipe stays
   outside the prefixes in the `sp_season_wipe` cursor.
2. **Register it** in `backend_scripts/localDev/table_registry.py` (the module docstring defines
   the categories). Until then the seed fails with `UnknownTableError`.
3. **Seed it** if its category needs rows: a `seed_*` function in
   `backend_scripts/localDev/seeders.py`, called from `seed_test_db.py`. Id-bearing columns come
   from the same static lookup the template subscripts ("Templates crash on unknown ids" in
   `AGENTS.md`).
4. **Write the migration script that creates it on the production server**
   ([[database-migration-script]]). Nothing applies `database.sql` there. Grant every MySQL user
   that touches it ([[bot-db-grants]]).
5. Verify with [[local-test-render]], and [[verify-database-sql]] for the DDL itself.
