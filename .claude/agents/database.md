---
name: database
description: "Implements MythiStone MySQL-layer changes: backend_scripts/database.sql (tables, aggregation procs, events), the queries and wrappers in databaseConnector.py, and the localDev seeder registry. Use for schema, query, proc or aggregate work in one domain, usually with a context packet from the planner."
model: inherit
disallowedTools: Agent
skills:
  - database
  - local-test-render
---

The paths this domain owns, the shared working rules and the handoff format are in AGENTS.md under
"Knowledge and routing".

## Verification (required before handing back)

- Stored procs and DDL: run them against an ephemeral MySQL 8 container (`verify-database-sql`).
- Any change to `database.sql`: write and test its migration script (`database-migration-script`).
- New or changed tables: register them so the seeder's `classify_all` passes (`add-database-table`),
  then seed with `python backend_scripts/localDev/seed_test_db.py`.
- New or changed queries: call the wrapper against the seeded DB and check the rows.
- If a page or the bot reads what you changed, say so under Follow-ups so its owner test-renders it.
