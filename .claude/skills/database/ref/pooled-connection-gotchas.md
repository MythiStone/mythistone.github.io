---
name: pooled-connection-gotchas
description: Two mysql.connector pooled-connection traps in MythiStone. Use when writing DB code in backend_scripts (databaseConnector.py, collectors, simcBis.py), debugging silent write loss / rolled-back upserts, or a long-running loop that dies with "MySQL Connection not available".
files:
  - backend_scripts/databaseConnector.py
  - backend_scripts/collectLeaderboardData.py
  - backend_scripts/simcBis.py
  - discord_bot/db.py
---

# Pooled connection gotchas

Two independent traps with `mysql.connector`'s `PooledMySQLConnection` in `backend_scripts/`.

## 1. `.autocommit` attribute does not reach the server

The pooled wrapper swallows the `.autocommit` setter: `conn.autocommit = True` sets a Python attribute but the server session stays `autocommit=0` (`SELECT @@autocommit` returns 0 after the attribute set). Consequence: any WRITE on such a session sits in an open transaction and is rolled back when the connection returns to the pool, with no error. A writer can log "upserted N rows" and leave the table empty. Reads are unaffected, which is why this hides.

Apply: `databaseConnector.configure_read_session` runs `cursor.execute("SET SESSION autocommit = 1")` (SQL reaches the server, the attribute set does not) alongside READ UNCOMMITTED and the lock timeouts; that is also what makes its per-statement MDL release work on pooled connections. For any writer on a pooled connection, call `commit_with_retry(conn)` explicitly rather than trusting the attribute.

## 2. Never hold a pooled connection across a long blocking op

The pool only revalidates a connection when it is checked out (a returned stale slot transparently reconnects on next use). A connection held checked out across a long blocking operation does NOT auto-recover: when the server drops it (`wait_timeout`) the next query raises `OperationalError: MySQL Connection not available`. For example, holding one pooled connection across `optimize_spec` (an hours-long simc container) lets the idle-held connection die mid-run, so the closing `persist()` write fails and surfaces as paired Discord alerts.

Apply: for any collector work spanning a slow step, use read -> release -> work -> reacquire. Read under a short-lived connection, close it, do the slow work holding NO connection, then check out a fresh one, preferring `databaseConnector.get_live_connection()` (it pings/reconnects on checkout), to write. `simcBis.run_simc_bis` does this.

Related: [[aggregation-pipeline]].
