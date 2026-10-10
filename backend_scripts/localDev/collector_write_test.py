#!/usr/bin/env python3
"""Write-path test for the collector, against an ALREADY-SEEDED throwaway test DB.

Imports the real collectLeaderboardData module and drives process_batch /
databaseConnector.run_in_transaction with synthetic queued runs, then checks
what landed in MySQL. No network: the API env vars are placeholders and nothing
here fetches. It never touches the live DB (it only opens the seeder's test DB).

What it guards (each one silently loses or corrupts collected data if broken):
  * a batch commits as one unit, and a failure leaves no run without members,
  * ids derived from multi-row inserts attach children to the right parent,
  * duplicates are no-ops, and a reused member only gains a run_members link,
  * one bad run does not cost the rest of its batch,
  * a lock wait timeout re-runs the whole batch exactly once,
  * the event loop keeps running while a batch is written.

Usage, from the repo root after seed_test_db.py:

    python backend_scripts/localDev/collector_write_test.py

or inside the collector image (modules live flat in /app there):

    docker run --rm --network host --entrypoint python \\
        -v "$PWD/backend_scripts/localDev:/t:ro" <image> /t/collector_write_test.py /app

TEST_DB_HOST / TEST_DB_PORT override 127.0.0.1:3399. Exit code 0 = pass.
"""
import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(SCRIPT_DIR))
os.chdir(REPO)  # the collector reads data/static relative to the working directory
sys.path.insert(0, os.path.join(REPO, "backend_scripts"))
sys.path.insert(0, REPO)
sys.argv = [sys.argv[0]]  # the collector parses argv at import

os.environ.update({
    "DATABASE_HOST": os.environ.get("TEST_DB_HOST", "127.0.0.1"),
    "DATABASE_PORT": os.environ.get("TEST_DB_PORT", "3399"),
    "DATABASE_USER": "Test", "DATABASE_PASSWORD": "test", "DATABASE_NAME": "Mythistone",
    "REGIONS": "us", "BLIZ_CLIENT_ID_US": "placeholder", "BLIZ_CLIENT_SECRET_US": "placeholder",
    "RAIDERIO_API_KEY": "placeholder", "KEYSTONE_GURU_USER": "placeholder",
    "KEYSTONE_GURU_PW": "placeholder", "SIMC_ENABLED": "false",
})

import collectLeaderboardData as c  # noqa: E402
import databaseConnector as db  # noqa: E402

RUNS_TMP = tempfile.mkdtemp(prefix="mythi_runs_")
c.RUNS_DIR = c.Path(RUNS_TMP)
# Fresh timestamps every invocation keep the test re-runnable on the same DB.
BASE_TS = int(time.time() * 1000) - 3_600_000
SPEC = 62

FAILED = []


def check(label, cond, detail=""):
    if not cond:
        FAILED.append(label)
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""))


def query(sql, params=()):
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


DUNGEON = str(query("SELECT dungeon_id FROM dungeon_data LIMIT 1")[0][0])
COUNTED = ("runs", "members", "run_members", "equipment", "enchantments", "sockets",
           "character_stats", "member_character", "member_dungeon_score")


def counts():
    return {t: query(f"SELECT COUNT(*) FROM {t}")[0][0] for t in COUNTED}


def delta(before):
    after = counts()
    return {k: after[k] - before[k] for k in before if after[k] != before[k]}


def advanced_member(char_id, reuse=True):
    """16 items; enchant and gem ids are derived from the item id so a wrong
    parent id shows up as a mismatch."""
    member = {
        "spec_id": SPEC, "loadout": f"LOADOUT{char_id}", "hero_talent_id": 40,
        "class_talents": [(1000 + char_id % 3, 1), (1001, 2)],
        "spec_talents": [(2000, 1)], "hero_talents": [(3000, 1)],
        "equipment": [
            {"slot": f"SLOT{i}", "item_id": 200000 + i, "item_level": 700 + i,
             "enchantments": [7000 + i] if i % 2 else [],
             "sockets": [("PRISMATIC", 213000 + i)] if i % 3 == 0 else [],
             "bonuses": [10, 20, 30 + (i % 2)]}
            for i in range(16)
        ],
        "stats": {"haste": {"rating": 1000, "percent": 12.5}, "intellect": 90000},
        "region": "us", "blizzard_character_id": char_id,
        "character_name": f"Char{char_id}", "realm_slug": "writetest", "mplus_score": 3500,
        "dungeon_scores": {DUNGEON: 400},
    }
    if reuse:
        member["reuse_key"] = ("us", char_id, SPEC)
    return member


def simple_member(char_id):
    return {"spec_id": SPEC, "loadout": None, "hero_talent_id": None, "class_talents": [],
            "spec_talents": [], "hero_talents": [], "equipment": [], "region": "us",
            "blizzard_character_id": char_id}


def queued_run(i, members):
    return {"period_id": 1, "run_hash": f"writetest-{BASE_TS}-{i}", "season": 18, "region": "us",
            "realm": 1, "dungeon_id": DUNGEON, "keystone_level": 20, "duration": 1_500_000 + i,
            "timestamp": BASE_TS + i, "faction": "ALLIANCE", "members": members}


def orphaned_runs():
    return query(
        "SELECT COUNT(*) FROM runs r LEFT JOIN run_members rm ON rm.run_id = r.run_id "
        "WHERE r.timestamp BETWEEN %s AND %s AND rm.run_id IS NULL",
        (BASE_TS, BASE_TS + 100_000))[0][0]


async def batch_tests(conn):
    before = counts()
    t0 = time.perf_counter()
    await c.process_batch(
        "test", conn,
        [queued_run(i, [advanced_member(i * 10 + j) for j in range(5)]) for i in range(50)],
        c.GLOBAL_STATS)
    took = time.perf_counter() - t0
    d = delta(before)
    check("batch of 50 advanced runs is stored", d == {
        "runs": 50, "members": 250, "run_members": 250, "equipment": 4000, "enchantments": 2000,
        "sockets": 1500, "character_stats": 500, "member_character": 250,
        "member_dungeon_score": 250}, f"{took:.2f}s {d}")

    bad_enchants = query(
        "SELECT COUNT(*) FROM enchantments e JOIN equipment q ON q.equipment_id = e.equipment_id "
        "JOIN member_character mc ON mc.member = q.member "
        "WHERE mc.realm_slug = 'writetest' AND e.enchantment_id <> q.item_id - 193000")[0][0]
    bad_sockets = query(
        "SELECT COUNT(*) FROM sockets s JOIN equipment q ON q.equipment_id = s.equipment_id "
        "JOIN member_character mc ON mc.member = q.member "
        "WHERE mc.realm_slug = 'writetest' AND s.socket_item_id <> q.item_id + 13000")[0][0]
    per_member = tuple(query(
        "SELECT MIN(n), MAX(n) FROM (SELECT COUNT(*) n FROM equipment q JOIN member_character mc "
        "ON mc.member = q.member WHERE mc.realm_slug = 'writetest' GROUP BY q.member) t")[0])
    check("generated ids attach gear children to the right item",
          bad_enchants == 0 and bad_sockets == 0 and per_member == (16, 16),
          f"enchants={bad_enchants} sockets={bad_sockets} items/member={per_member}")
    wrong_member = query(
        "SELECT COUNT(*) FROM member_character mc JOIN members m ON m.member = mc.member "
        "WHERE mc.realm_slug = 'writetest' "
        "AND m.loadout <> CONCAT('LOADOUT', mc.blizzard_character_id)")[0][0]
    check("generated ids attach identity rows to the right member", wrong_member == 0)

    seen = sum(len(open(os.path.join(dp, f)).read().split())
               for dp, _, files in os.walk(RUNS_TMP) for f in files)
    check("stored runs are recorded in the seen-files", seen == 50, f"{seen} lines")
    check("reuse cache is filled after the commit", len(c.enqueued_profiles) == 250)

    before = counts()
    await c.process_batch(
        "test", conn,
        [queued_run(i, [advanced_member(i * 10 + j) for j in range(5)]) for i in range(50)],
        c.GLOBAL_STATS)
    check("re-sent batch writes nothing", delta(before) == {}, str(delta(before)))

    member_id = c.enqueued_profiles[("us", 0, SPEC)][0]
    before = counts()
    await c.process_batch(
        "test", conn,
        [queued_run(900, [{"member_id": member_id}] + [simple_member(9000 + j) for j in range(4)])],
        c.GLOBAL_STATS)
    d = delta(before)
    check("reused member gains a run link and no gear",
          d == {"runs": 1, "members": 4, "run_members": 5, "member_character": 4}, str(d))
    check("shared member is linked to both runs",
          query("SELECT COUNT(*) FROM run_members WHERE member = %s", (member_id,))[0][0] == 2)

    before = counts()
    poisoned = [queued_run(950 + i, [simple_member(9500 + i * 5 + j) for j in range(5)])
                for i in range(5)]
    poisoned[2]["members"][3]["spec_id"] = None  # members.spec_id is NOT NULL
    bad_hash = poisoned[2]["run_hash"]
    c.processed_runs.update(r["run_hash"] for r in poisoned)
    await c.process_batch("test", conn, poisoned, c.GLOBAL_STATS)
    d = delta(before)
    check("bad run is rolled back whole, the other 4 are stored",
          d.get("runs") == 4 and d.get("members") == 20 and d.get("run_members") == 20, str(d))
    check("failed run is forgotten so the next poll retries it",
          bad_hash not in c.processed_runs and c.store_failures.get(bad_hash) == 1)

    before = counts()
    real_insert = db.insert_run_batch

    def crash_before_commit(cursor, runs):
        real_insert(cursor, runs)
        raise RuntimeError("simulated crash after every insert, before the commit")

    db.insert_run_batch = crash_before_commit
    try:
        await c.process_batch(
            "test", conn,
            [queued_run(970 + i, [advanced_member(97000 + i * 5 + j, reuse=False) for j in range(5)])
             for i in range(3)],
            c.GLOBAL_STATS)
    finally:
        db.insert_run_batch = real_insert
    check("crash before the commit leaves no rows behind", delta(before) == {}, str(delta(before)))
    check("no run exists without its members", orphaned_runs() == 0, f"orphans={orphaned_runs()}")

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.5)  # idle tick rate; timer granularity differs per OS
    idle_rate = ticks / 0.5
    ticks = 0
    t0 = time.perf_counter()
    await c.process_batch(
        "test", conn,
        [queued_run(1000 + i, [advanced_member(100000 + i * 10 + j, reuse=False) for j in range(5)])
         for i in range(50)],
        c.GLOBAL_STATS)
    took = time.perf_counter() - t0
    task.cancel()
    check("event loop keeps running during a write", ticks >= idle_rate * took * 0.4,
          f"{ticks} ticks in {took:.2f}s, idle {idle_rate:.0f}/s")


def retry_test():
    """Block the writer on a row another session holds: it times out after it
    has already inserted earlier rows of the batch, and must redo all of them."""
    writer = db.get_connection()
    blocker = db.get_connection()
    try:
        cur = writer.cursor()
        cur.execute("SET SESSION innodb_lock_wait_timeout = 1")
        cur.close()
        writer.commit()

        def shaped(i):
            member = {"row": (SPEC, None, None, None), "talent_rows": [],
                      "character": ("us", 5_000_000 + i, None, None, None), "dungeon_scores": [],
                      "stats": [], "equipment": [
                          {"row": ("HEAD", 300000 + i, 700, None), "bonus_rows": [],
                           "enchantments": [1], "sockets": []}]}
            return {"run": (18, "eu", DUNGEON, 19, 1_600_000 + i, BASE_TS + 50_000 + i, "HORDE"),
                    "members": [dict(member) for _ in range(5)]}

        runs = [shaped(i) for i in range(4)]
        blocker.cursor().execute(db.INSERT_RUN_SQL, runs[3]["run"])
        threading.Timer(2.5, blocker.rollback).start()

        attempts = []

        def work(cursor):
            attempts.append(1)
            return db.insert_run_batch(cursor, runs)

        run_ids, _ = db.run_in_transaction(writer, work)
        marks = ", ".join(["%s"] * len(run_ids))
        links, members = query(
            f"SELECT COUNT(*), COUNT(DISTINCT member) FROM run_members WHERE run_id IN ({marks})",
            tuple(run_ids))[0]
        gear = query(
            "SELECT COUNT(*) FROM equipment WHERE member IN "
            f"(SELECT member FROM run_members WHERE run_id IN ({marks}))", tuple(run_ids))[0][0]
        check("lock wait timeout re-runs the whole batch exactly once",
              len(attempts) >= 2 and all(run_ids) and (links, members, gear) == (20, 20, 20),
              f"attempts={len(attempts)} run_members={links} members={members} equipment={gear}")
    finally:
        writer.close()
        blocker.close()


def cleanup():
    """Remove every row this test wrote, so a later step on the same DB (the
    collector smoke run builds simc profiles from stored gear) never sees the
    synthetic items. Deleting the members cascades to their gear and identity."""
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT run_id FROM runs WHERE timestamp BETWEEN %s AND %s AND "
            "((faction = 'ALLIANCE' AND duration BETWEEN 1500000 AND 1501999) OR "
            " (faction = 'HORDE' AND duration BETWEEN 1600000 AND 1600999))",
            (BASE_TS, BASE_TS + 100_000))
        run_ids = [row[0] for row in cur.fetchall()]
        if run_ids:
            marks = ", ".join(["%s"] * len(run_ids))
            cur.execute(f"SELECT DISTINCT member FROM run_members WHERE run_id IN ({marks})", run_ids)
            member_ids = [row[0] for row in cur.fetchall()]
            cur.execute(f"DELETE FROM runs WHERE run_id IN ({marks})", run_ids)
            for start in range(0, len(member_ids), 500):
                chunk = member_ids[start:start + 500]
                cur.execute(
                    f"DELETE FROM members WHERE member IN ({', '.join(['%s'] * len(chunk))})", chunk)
        conn.commit()
    finally:
        conn.close()


async def main():
    conn = db.get_connection()
    try:
        await batch_tests(conn)
    finally:
        conn.close()
    await asyncio.to_thread(retry_test)


BASELINE = counts()
try:
    asyncio.run(main())
finally:
    shutil.rmtree(RUNS_TMP, ignore_errors=True)
    cleanup()
check("test rows are cleaned up", counts() == BASELINE,
      str({k: counts()[k] - BASELINE[k] for k in BASELINE if counts()[k] != BASELINE[k]}))
print("ALL PASS" if not FAILED else f"FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
