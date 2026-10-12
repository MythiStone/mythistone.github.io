---
name: pooled-connection-gotchas
description: Two rules every user of the mysql.connector pool follows, a write commits only on a configured session or with an explicit commit, and no pooled connection is held across a slow step. Use when adding a DB write, a long-running collector or simc step, or when a writer logs success and the table stays empty.
kind: coupling
files:
  - backend_scripts/databaseConnector.py
  - backend_scripts/collectLeaderboardData.py
  - backend_scripts/simcBis.py
  - discord_bot/db.py
---

# Pooled connection rules

- **A write commits only on a session set up by `databaseConnector.configure_read_session`, or
  after an explicit `commit_with_retry`.** On any other pooled connection the write is rolled back
  without an error when the connection returns to the pool: the writer logs success and the table
  stays empty, and reads never show the problem. The bot's inserts rely on the first form through
  `discord_bot/db.py`, so the session setup in `configure_read_session` is load-bearing for them.
- **No pooled connection is held across a slow step.** Read, release, do the slow work, then check
  out a fresh connection with `get_live_connection` to write, as `simcBis.run_simc_bis` does. A
  connection held idle past the server's `wait_timeout` fails on its next statement.

Related: [[aggregation-pipeline]].
