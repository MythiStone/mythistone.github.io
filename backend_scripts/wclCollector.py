"""Warcraft Logs pull intelligence: the collector task and its debug CLI.

Production: collectLeaderboardData.main runs run_wcl. Its sweeper queues the ranked runs of every
(dungeon, spec) in the last SWEEP_DAYS, least recently swept pair first, and its worker turns each
queued run into wcl_* aggregate deltas and example-log rows, written in one transaction.

Debug:
  python backend_scripts/wclCollector.py --dry-run CODE FIGHT [--route KSG_KEY] [--friendly-sightings]
        [--cache | --from-cache] [--pack-truth PATH] [--write-local]
      Rebuilds one run's pulls and prints them next to the keystone.guru route, plus the deltas the
      collector would write. --write-local (needs --from-cache) then also processes the run into the
      DB at DATABASE_* exactly like the worker. Only ever point it at a throwaway local DB.
  python backend_scripts/wclCollector.py --sweep-once --dungeon CM --spec SPEC_ID
      Prints the fights one sweep of that pair would queue. Writes nothing. With DATABASE_* set it
      also leaves out the fights that DB already processed.

Needs WCL_CLIENT_ID / WCL_CLIENT_SECRET (not with --from-cache), and KEYSTONE_GURU_USER /
KEYSTONE_GURU_PW for --route.
"""
import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

import databaseConnector as db
import wclPullBuilder as pb
from wclClient import NoMplusZone, WclClient

STATIC_DIR = Path("data") / "static"
KSG_ROUTE_URL = "https://keystone.guru/api/v1/route/{key}"
# Local, temporary raw-event cache of the acceptance runs only (--cache): gitignored tmp/, never
# committed or stored in the DB, deleted once the gate passes.
EVENT_CACHE_DIR = os.path.join("tmp", "wcl_event_cache")
# The lust spells are the spells.json entries whose tooltip is the party haste buff.
LUST_TOOLTIP = "haste by 30%"
SWEEP_DAYS = 14
SWEEP_PAGES = 1
WORKER_BATCH = 20
WORKER_IDLE_S = 300
# Matches the queue pop, which skips fights with 3 attempts.
MAX_ATTEMPTS = 3
NO_ZONE_RECHECK_S = 3600
ERROR_BACKOFF_S = (60, 3600)

SIGHTING_QUERIES = {
    "enemyCasts": "dataType: Casts, hostilityType: Enemies, includeResources: true",
    "enemyDamage": "dataType: DamageDone, hostilityType: Enemies, includeResources: true",
    "enemyDeaths": "dataType: Deaths, hostilityType: Enemies, includeResources: true",
    "enemySummons": "dataType: Summons, hostilityType: Enemies",
}
FRIENDLY_DAMAGE = {"friendlyDamage": "dataType: DamageDone, hostilityType: Friendlies, includeResources: true"}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def lust_ids():
    spells = load_json(STATIC_DIR / "spells.json")
    ids = {int(k) for k, v in spells.items() if LUST_TOOLTIP in (v.get("description") or {}).get("en_US", "")}
    if len(ids) < 3:
        raise RuntimeError(f"spells.json holds only {sorted(ids)} as lust spells")
    return ids


def wcl_specs():
    """[(WCL class name, WCL spec name, spec id)] and {(norm class, norm spec): spec id}."""
    classes = load_json(STATIC_DIR / "classes.json")
    specs = load_json(STATIC_DIR / "specs.json")
    rows = [(classes[s["classID"]]["name"].replace(" ", ""), s["name"].replace(" ", ""), int(sid))
            for sid, s in specs.items() if s["classID"] in classes]
    return rows, {(norm(c), norm(s)): sid for c, s, sid in rows}


def player_specs(actors, fight, by_name):
    """{player actor id: spec id} from the actor icon, which WCL sets to "<Class>-<Spec>". Some reports'
    icons hold only the class; then the spec comes from fight.friendlySpecs, aligned with friendlyPlayers."""
    out = {}
    fight_specs = fight.get("friendlySpecs") or []
    for i, pid in enumerate(fight["friendlyPlayers"]):
        icon = (actors.get(pid) or {}).get("icon") or ""
        cls, _, spec = icon.partition("-")
        if not spec and i < len(fight_specs):
            spec = fight_specs[i] or ""
        if (norm(cls), norm(spec)) not in by_name:
            raise RuntimeError(f"Player actor {pid} has an unknown spec icon '{icon}'")
        out[pid] = by_name[(norm(cls), norm(spec))]
    return out


def dungeon_id(fight, dungeons, enc_ids=None):
    """The fight's cm id. enc_ids ({cm: WCL encounter id}) is authoritative: WCL can title a complete
    run after its bosses. Without it (debug CLI) the fight name decides."""
    hits = ([cm for cm, enc in enc_ids.items() if enc == fight["encounterID"]] if enc_ids else
            [cm for cm, d in dungeons.items() if norm(d["name"]["en_US"]) == norm(fight["name"])])
    if len(hits) != 1:
        raise RuntimeError(f"Fight '{fight['name']}' (encounter {fight['encounterID']}) matches "
                           f"{len(hits)} current dungeons")
    return hits[0]


def boss_windows(fight):
    return [(p["encounterID"], p["startTime"], p["endTime"]) for p in fight.get("dungeonPulls") or []
            if p.get("encounterID")]


def sighting_events(events):
    return events["enemyCasts"] + events["enemyDamage"] + events.get("friendlyDamage", [])


async def fetch_route(session, key):
    auth = aiohttp.encode_basic_auth(os.environ["KEYSTONE_GURU_USER"], os.environ["KEYSTONE_GURU_PW"])
    async with session.get(KSG_ROUTE_URL.format(key=key), headers={"Authorization": auth}) as resp:
        resp.raise_for_status()
        route = (await resp.json()).get("data") or {}
    pulls = route.get("pulls") or []
    if not pulls:
        raise RuntimeError(f"keystone.guru route {key} has no pulls")
    return [sorted(Counter(int(e["npcId"]) for e in p.get("enemies", []) if e.get("npcId")).items())
            for p in pulls]


def clock(ms, start):
    tenths = round((ms - start) / 100)
    return f"{tenths // 600:02d}:{tenths % 600 / 10:04.1f}"


def align_pulls(ours, theirs):
    """Walks both pull lists ([[(npc, n)]]) in order and pairs them by content: equal pulls, a run of
    our pulls that sums to one of theirs (we split it), one of ours that sums a run of theirs (we
    merged), or a mismatch. Returns [(kind, our indexes, their indexes)], 1-based."""
    def total(pulls):
        return sum((Counter(dict(p)) for p in pulls), Counter())

    out, i, j = [], 0, 0
    while i < len(ours) or j < len(theirs):
        if i < len(ours) and j < len(theirs) and ours[i] == theirs[j]:
            out.append(("same", [i + 1], [j + 1]))
            i, j = i + 1, j + 1
            continue
        step = None
        for k in range(i + 2, len(ours) + 1):
            if j < len(theirs) and total(ours[i:k]) == total([theirs[j]]):
                step = ("we split", list(range(i + 1, k + 1)), [j + 1], k, j + 1)
                break
        for k in range(j + 2, len(theirs) + 1):
            if step is None and i < len(ours) and total(theirs[j:k]) == total([ours[i]]):
                step = ("we merged", [i + 1], list(range(j + 1, k + 1)), i + 1, k)
                break
        if step is None:
            step = ("differs", [i + 1] if i < len(ours) else [], [j + 1] if j < len(theirs) else [],
                    min(i + 1, len(ours)), min(j + 1, len(theirs)))
        out.append(step[:3])
        i, j = step[3], step[4]
    return out


def print_run(run, fight, route):
    start = fight["startTime"]
    print(f"\n{len(run['pulls'])} pulls rebuilt" + (f", keystone.guru route has {len(route)}" if route else ""))
    for p in run["pulls"]:
        print(f"\n#{p.index} {clock(p.start, start)} - {clock(p.end or run['fight_end'], start)} key {p.key()}" + (f" b:{p.encounter_id}" if p.encounter_id else "") + f" packs {','.join(p.pack_ids()) or '-'}")
        print(f"   ours  {p.npc_counts()}")
        for m in sorted(p.mobs, key=lambda m: m.engage):
            k = m.pack
            where = (f"pack {k['id']}" + (f" at {m.distance:.1f} yd from its fitted centre" if m.distance is not None else "") if k
                     else "UNRESOLVED" + (f" at ({m.first[0]:.1f}, {m.first[1]:.1f}) floor {m.first[2]}" if m.first else ""))
            print(f"     {m.npc} inst {m.key[1]:>3} engage {clock(m.engage, start)} dies {clock(m.death, start)} "
                  f"{m.killed_by:<13} {where}")
    if route:
        ours = [p.npc_counts() for p in run["pulls"]]
        steps = align_pulls(ours, route)
        print("\nkeystone.guru alignment:")
        for kind, a, b in steps:
            print(f"   {kind:<9} ours {a} ksg {b}" + ("" if kind == "same" else f"   ksg {[route[x - 1] for x in b]}"))
        same = sum(1 for kind, _, _ in steps if kind == "same")
        print(f"\nACCEPTANCE: {same} of {len(route)} keystone.guru pulls reproduced exactly"
              f"{' - MATCH' if same == len(route) == len(ours) else ''}")


def print_wcl_pull_links(run, fight, actors):
    """Each rebuilt pull next to the WCL dungeon pull wcl_pull_id picks for it."""
    start = fight["startTime"]
    dungeon_pulls = fight.get("dungeonPulls") or []
    by_id = {p["id"]: p for p in dungeon_pulls}
    print("\nWCL dungeon pulls:")
    for w in dungeon_pulls:
        print(f"  WCL {w['id']:>3} {clock(w['startTime'], start)} - {clock(w['endTime'], start)}"
              f" encounter {w.get('encounterID') or 0}")
    print("\nOur pulls and the WCL pull each one links to:")
    for p in run["pulls"]:
        linked = by_id.get(pb.wcl_pull_id(p, dungeon_pulls, run["fight_end"]))
        target = (f"WCL {linked['id']} {clock(linked['startTime'], start)} - {clock(linked['endTime'], start)}"
                  if linked else "no WCL pull")
        names = sorted({(actors.get(m.key[0]) or {}).get("name", str(m.npc)) for m in p.mobs})
        print(f"  #{p.index:>2} {clock(p.start, start)} - {clock(p.end or run['fight_end'], start)} -> {target}: "
              f"{', '.join(names)}")


def print_pack_accuracy(run, truth):
    """Compares our pack per mob with a reference route's resolved MDT clones: {"pulls": [[[npc,
    clone index, g, ...], ...], ...]}. Pulls are paired by equal npc counts."""
    ref = [Counter(str(r[2]) if r[2] != -1 else f"c{r[0]}.{r[1]}" for r in p) for p in truth["pulls"]]
    ref_counts = [sorted(Counter(r[0] for r in p).items()) for p in truth["pulls"]]
    exact = right = compared = 0
    for p in run["pulls"]:
        if p.npc_counts() not in ref_counts:
            continue
        want = ref[ref_counts.index(p.npc_counts())]
        ours = Counter(m.pack["id"] for m in p.mobs if m.pack)
        exact += set(ours) == set(want)
        right += sum((ours & want).values())
        compared += sum(want.values())
    print(f"\npacks vs reference: pull pack sets exact {exact}/{len(ref)}; mobs in the reference pack "
          f"{right}/{compared} of the pulls with equal npc counts ({sum(sum(w.values()) for w in ref)} mobs in all)")


def print_deltas(deltas):
    print("\nDeltas this run would add:")
    for name, rows in sorted(deltas.items()):
        print(f"  {name}: {len(rows)} keys, total {sum(rows.values())}")
        for key, n in list(rows.items())[:3]:
            print(f"      {key}: {n}")




# Static data and one run's build, shared by the debug CLI and the collector.

def load_static():
    dungeons = load_json(STATIC_DIR / "dungeons.json")
    mapping = load_json(STATIC_DIR / "dungeon_mapping.json")
    if set(dungeons) - set(mapping):
        raise RuntimeError(f"dungeon_mapping.json lacks dungeons {sorted(set(dungeons) - set(mapping))}")
    spec_rows, specs_by_name = wcl_specs()
    return {"dungeons": dungeons, "mapping": mapping, "lust": lust_ids(),
            "cooldowns": load_json(STATIC_DIR / "player_cooldowns.json"),
            "cooldown_categories": load_json(STATIC_DIR / "player_cooldown_categories.json"),
            "aoe_spells": {int(k) for k, v in load_json(STATIC_DIR / "dungeon_spells.json").items() if v.get("aoe")},
            "spec_rows": spec_rows, "specs_by_name": specs_by_name}


async def zone_dungeons(client, dungeons):
    """{cm id: WCL encounter id} of the active M+ zone, matched by English name."""
    zone = await client.mplus_zone()
    by_name = {norm(d["name"]["en_US"]): cm for cm, d in dungeons.items()}
    out = {by_name.get(norm(e["name"])): e["id"] for e in zone["encounters"]}
    if None in out or set(out) != set(dungeons):
        raise RuntimeError(f"WCL zone '{zone['name']}' dungeons {sorted(e['name'] for e in zone['encounters'])} "
                           f"do not match dungeons.json")
    return out


async def fetch_events(client, code, fight, actors, static, friendly_sightings=True):
    """One aliased events request (paged): enemy sightings and deaths, player deaths, and the
    casts of the present specs' cooldowns, every racial and lust."""
    return await client.events(code, fight, run_queries(actors, fight, static, friendly_sightings))


def run_queries(actors, fight, static, friendly_sightings=True):
    specs = set(player_specs(actors, fight, static["specs_by_name"]).values())
    ids = sorted({int(sid) for sid, c in static["cooldowns"].items() if c.get("racial") or set(c["specs"]) & specs}
                 | static["lust"])
    return {**SIGHTING_QUERIES, **(FRIENDLY_DAMAGE if friendly_sightings else {}),
            "friendlyDeaths": "dataType: Deaths, hostilityType: Friendlies",
            "friendlyInterrupts": "dataType: Interrupts, hostilityType: Friendlies",
            "friendlyCasts": f'dataType: Casts, hostilityType: Friendlies, '
                             f'filterExpression: "ability.id IN ({",".join(map(str, ids))})"'}


def build(fight, actors, events, static, enc_ids=None):
    """(cm id, {player: spec id}, run) of one fetched run. CPU heavy: the collector runs it in a thread."""
    cm = dungeon_id(fight, static["dungeons"], enc_ids)
    clones = static["mapping"][cm]["clones"]
    specs = player_specs(actors, fight, static["specs_by_name"])
    run = pb.build_run(
        pb.mdt_packs(clones), actors, sighting_events(events), events["enemyDeaths"],
        events["enemySummons"], boss_windows(fight), fight["startTime"], fight["endTime"],
        friendly_casts=[e for e in events["friendlyCasts"] if e.get("type") == "cast"],
        friendly_deaths=events["friendlyDeaths"], lust_ids=static["lust"],
        boss_npc_ids=set(static["dungeons"][cm]["boss_npc_ids"]), npc_slots=Counter(c["npc_id"] for c in clones),
        main_boss_npcs=set(static["mapping"][cm]["boss_npcs"]), clones=clones,
        interrupts=[e for e in events["friendlyInterrupts"] if e.get("type") == "interrupt"],
        aoe_spells=static["aoe_spells"])
    return cm, specs, run


def run_fingerprint(cm, fight, actors):
    """sha1(cm, key level, keystone time, sorted player name-server): one run logged in several reports."""
    players = sorted(f"{actors[p]['name']}-{actors[p].get('server') or ''}" for p in fight["friendlyPlayers"])
    parts = [cm, str(fight.get("keystoneLevel")), str(fight.get("keystoneTime")), *players]
    return hashlib.sha1("|".join(parts).encode("utf-8")).digest()


def marker_fingerprint(status, code, fight_id):
    """wcl_processed_runs.run_fingerprint is unique and NOT NULL, so a skipped or failed run, which
    must not claim the real run's fingerprint, stores a digest of its own key instead."""
    return hashlib.sha1(f"{status}:{code}:{fight_id}".encode("utf-8")).digest()


def delta_rows(d, day, cm):
    """[(upsert function, rows)] of run_deltas output for one run, prefixed with bucket day and dungeon.
    Family-keyed deltas become family_id here, next to the dictionary rows sp_agg_wcl_cooldowns joins."""
    def fam(k):
        return (k[0], db.wcl_family_id(k[1]), *k[2:])

    pulls = defaultdict(lambda: [0, 0])
    for (key, enc), n in d["pull"].items():
        pulls[key][0] = max(pulls[key][0], enc or 0)
        pulls[key][1] += n
    spell_keys = set(d["enemy_spell_casts"]) | set(d["enemy_spell_mobs"])
    cd_keys = set(d["player_cd_casts"]) | set(d["player_cd_players"])
    return [
        (db.upsert_wcl_pull_families, [(db.wcl_family_id(k), k) for k in d["family"]]),
        (db.upsert_wcl_pull_daily, [(day, cm, key, enc, n, d["pull_duration_ms"][key], d["pulls_with_death"][key])
                                    for key, (enc, n) in pulls.items()]),
        (db.upsert_wcl_spec_pull_daily, [(day, cm, *fam(k), n) for k, n in d["spec_pull"].items()]),
        (db.upsert_wcl_npc_daily, [(day, cm, npc, n, d["npc_alive_ms"][npc]) for npc, n in d["npc_engaged"].items()]),
        (db.upsert_wcl_enemy_spell_daily, [(day, cm, enc or 0, npc, spell, d["enemy_spell_casts"][(enc, npc, spell)],
                                            d["enemy_spell_mobs"][(enc, npc, spell)]) for enc, npc, spell in spell_keys]),
        (db.upsert_wcl_enemy_spell_timing_daily, [(day, cm, k[0] or 0, *k[1:], n)
                                                  for k, n in d["enemy_spell_timing"].items()]),
        (db.upsert_wcl_player_cd_daily, [(day, cm, *fam(k), d["player_cd_casts"][k], d["player_cd_players"][k])
                                         for k in cd_keys]),
        (db.upsert_wcl_player_cd_relation_daily, [(day, cm, *fam(k), n, d["player_cd_relation_offset_s"][k],
                                                   d["player_cd_relation_abs_offset_s"][k])
                                                  for k, n in d["player_cd_relation"].items()]),
        (db.upsert_wcl_player_cd_usage_daily, [(day, cm, *fam(k), n, d["player_cd_usage_casts"][k],
                                                d["player_cd_usage_possible"][k], d["player_cd_usage_first_s"][k])
                                               for k, n in d["player_cd_usage_players"].items()]),
        (db.upsert_wcl_player_cd_target_daily, [(day, cm, *fam(k), n) for k, n in d["player_cd_target"].items()]),
        (db.upsert_wcl_enemy_spell_interrupt_daily, [(day, cm, k[0] or 0, *k[1:], n)
                                                     for k, n in d["enemy_spell_interrupts"].items()]),
        (db.upsert_wcl_lust_daily, [(day, cm, *k, n) for k, n in d["lust"].items()]),
        (db.upsert_wcl_player_death_daily, [(day, cm, *k, n) for k, n in d["player_death"].items()]),
    ]


def example_rows(run, specs, cm, code, fight_id, keystone_level, run_start_ms, dungeon_pulls):
    """One wcl_example_logs row per (pull key, spec, spell) of this run: the pull itself (spec 0,
    spell 0) at its first pull no other pull overlaps, else its first pull, lust (spec 0, the lust
    spell) and each spec's cooldown casts. A trash example opens as a time window on WCL, so only an
    isolated pull shows nothing but its own enemies."""
    pulls = {p.index: p for p in run["pulls"]}

    def end(p):
        return p.end or run["fight_end"]

    isolated = {p.index: not any(o is not p and o.start < end(p) and end(o) > p.start for o in run["pulls"])
                for p in run["pulls"]}
    first = {}
    for p in run["pulls"]:
        k = (p.key(), 0, 0)
        if k not in first or (isolated[p.index] and not isolated[first[k].index]):
            first[k] = p
    for lust in run["lusts"]:
        if lust["pull"] is not None:
            first.setdefault((pulls[lust["pull"]].key(), 0, lust["spell"]), pulls[lust["pull"]])
    for c in run["player_cds"]:
        if specs.get(c["player"]) is not None:
            first.setdefault((pulls[c["pull"]].key(), specs[c["player"]], c["spell"]), pulls[c["pull"]])
    return [(cm, key, spec, spell, code, fight_id, p.start, end(p), keystone_level, run_start_ms,
             pb.wcl_pull_id(p, dungeon_pulls, run["fight_end"]), int(isolated[p.index]))
            for (key, spec, spell), p in first.items()]


# Database units. Each checks a pooled connection out for one short unit and returns it, so no
# connection is ever held across an API call. Callers run them in a thread.

def _db(work):
    conn = db.get_live_connection()
    try:
        result = work(conn, conn.cursor())
        conn.commit()
        return result
    finally:
        conn.close()


def _write_run(code, fight_id, fingerprint, cm, run_start_ms, status, writes=(), examples=()):
    """The run's deltas, example logs, processed mark and queue delete, as one transaction."""
    def work(cursor):
        for upsert, rows in writes:
            upsert(cursor, rows)
        db.upsert_wcl_example_logs(cursor, list(examples))
        db.insert_wcl_processed_run(cursor, code, fight_id, fingerprint, cm, run_start_ms, status)
        db.delete_wcl_fight_queue(cursor, code, fight_id)
    return _db(lambda conn, _: db.run_in_transaction(conn, work))


def _queue_fresh(conn, cursor, fights, cm, spec_id):
    """Queues the fights neither processed nor already queued, and returns them."""
    keys = [f[:2] for f in fights]
    known = db.fetch_wcl_processed_runs(conn, cursor, keys) | db.fetch_wcl_queued_runs(conn, cursor, keys)
    fresh = [f for f in fights if f[:2] not in known]
    db.upsert_wcl_fight_queue(conn, cursor, fresh)
    db.update_wcl_crawl_state(conn, cursor, cm, spec_id, len(fresh))
    return fresh


def _record_failure(code, fight_id, error, final, cm, run_start_ms):
    _db(lambda conn, cursor: db.record_wcl_fight_attempt(conn, cursor, code, fight_id, error))
    if final:
        _write_run(code, fight_id, marker_fingerprint("failed", code, fight_id), cm, run_start_ms, "failed")


# Sweeper.

async def ranked_fights(client, encounter_id, spec_row, cm, now_ms):
    """[(code, fight, cm, run start ms, key level)] of the spec's top ranked runs in the window."""
    cls, spec, _ = spec_row
    out = {}
    for page in range(1, SWEEP_PAGES + 1):
        ranked = await client.character_rankings(encounter_id, cls, spec, page,
                                                 now_ms - SWEEP_DAYS * 86_400_000, now_ms)
        rows = ranked.get("rankings") or []
        for r in rows:
            report = r.get("report") or {}
            # "a:" codes are anonymized reports: no player names for the run fingerprint.
            if report.get("code") and report.get("fightID") and not report["code"].startswith("a:"):
                key = (report["code"], int(report["fightID"]))
                out[key] = (*key, cm, int(r["startTime"]), int(r["hardModeLevel"]))
        if not rows:
            break
    return list(out.values())


def next_pair(static, enc_ids, crawl_state):
    """The (cm, spec row) swept least recently, never swept first."""
    swept = {(str(d), int(s)): t for d, s, t, _ in crawl_state}
    return min(((cm, row) for cm in sorted(enc_ids) for row in static["spec_rows"]),
               key=lambda p: swept.get((p[0], p[1][2])) or datetime.min)


def _publish_rate(client, stats):
    """The API budget as the status embed shows it. client.rate is None right after an hourly reset."""
    if client.rate:
        r = client.rate
        stats.set_status("wcl_points", f"{r['pointsSpentThisHour']:.0f}/{r['limitPerHour']}")
        stats.set_status("wcl_db_points", f"{r['databasePointsSpentThisHour']:.0f}/{r['databaseLimitPerHour']}")


async def run_sweeper(client, static, enc_ids, write_gate, log, stats):
    pairs = {(str(cm), row[2]) for cm in enc_ids for row in static["spec_rows"]}
    while True:
        await write_gate.pause_point()
        state = await asyncio.to_thread(_db, db.fetch_wcl_crawl_state)
        cm, spec_row = next_pair(static, enc_ids, state)
        fights = await ranked_fights(client, enc_ids[cm], spec_row, cm, int(time.time() * 1000))
        async with write_gate:
            fresh = await asyncio.to_thread(_db, lambda c, cur: _queue_fresh(c, cur, fights, cm, spec_row[2]))
        log(f"[wcl] swept {static['dungeons'][cm]['name']['en_US']} {spec_row[1]} {spec_row[0]}: "
            f"{len(fights)} ranked runs, {len(fresh)} queued")
        await stats.increment("wcl_pairs_swept")
        await stats.increment("wcl_runs_ranked", len(fights))
        await stats.increment("wcl_runs_queued", len(fresh))
        swept = {(str(d), int(s)) for d, s, _, _ in state} | {(str(cm), spec_row[2])}
        stats.set_status("wcl_coverage", f"{len(swept & pairs)}/{len(pairs)}")
        _publish_rate(client, stats)


# Worker.

async def process_run(client, static, queued, write_gate, enc_ids=None):
    """Turns one queued run into its wcl_* rows. Returns (status, rows written)."""
    code, fight_id, cm, run_start_ms, keystone_level, _ = queued
    if await asyncio.to_thread(_db, lambda c, cur: db.fetch_wcl_processed_runs(c, cur, [(code, fight_id)])):
        async with write_gate:
            await asyncio.to_thread(_db, lambda c, cur: db.delete_wcl_fight_queue(cur, code, fight_id))
        return "already processed", 0
    fight, actor_list = await client.fight(code, fight_id)
    actors = {a["id"]: a for a in actor_list}
    if dungeon_id(fight, static["dungeons"], enc_ids) != str(cm):
        raise RuntimeError(f"Fight '{fight['name']}' is not queued dungeon {cm}")
    fingerprint = run_fingerprint(str(cm), fight, actors)
    if await asyncio.to_thread(_db, lambda c, cur: db.fetch_wcl_processed_fingerprints(c, cur, [fingerprint])):
        async with write_gate:
            await asyncio.to_thread(_write_run, code, fight_id, marker_fingerprint("skipped", code, fight_id),
                                    cm, run_start_ms, "skipped")
        return "skipped", 0
    events = await fetch_events(client, code, fight, actors, static)
    cm, specs, run = await asyncio.to_thread(build, fight, actors, events, static, enc_ids)
    day = datetime.fromtimestamp(run_start_ms / 1000, timezone.utc).date()
    writes = delta_rows(pb.run_deltas(run, specs, static["cooldowns"], static["cooldown_categories"]), day, cm)
    examples = example_rows(run, specs, cm, code, fight_id, keystone_level, run_start_ms, fight.get("dungeonPulls") or [])
    async with write_gate:
        await asyncio.to_thread(_write_run, code, fight_id, fingerprint, cm, run_start_ms, "done", writes, examples)
    return "done", sum(len(rows) for _, rows in writes) + len(examples)


async def run_worker(client, static, enc_ids, write_gate, log, stats):
    while True:
        await write_gate.pause_point()
        batch, pending = await asyncio.to_thread(_db, lambda c, cur: (db.pop_wcl_fight_queue(c, cur, WORKER_BATCH),
                                                                      db.count_wcl_fight_queue(c, cur)))
        stats.set_status("wcl_pending", f"{pending:,}")
        if not batch:
            await asyncio.sleep(WORKER_IDLE_S)
            continue
        for queued in batch:
            await write_gate.pause_point()
            code, fight_id, cm, run_start_ms, _, attempts = queued
            try:
                status, n = await process_run(client, static, queued, write_gate, enc_ids)
                log(f"[wcl] {code}#{fight_id} {status}, {n} rows")
                await stats.increment("wcl_runs_done" if status == "done" else "wcl_runs_skipped")
                _publish_rate(client, stats)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                final = attempts + 1 >= MAX_ATTEMPTS
                log(f"[wcl] {code}#{fight_id} attempt {attempts + 1}/{MAX_ATTEMPTS} failed"
                    f"{', marked failed' if final else ''}: {error}")
                await stats.increment("wcl_runs_failed" if final else "wcl_runs_retried")
                async with write_gate:
                    await asyncio.to_thread(_record_failure, code, fight_id, error, final, cm, run_start_ms)


# Collector task.

async def _supervised(name, start, reporter, log):
    """Awaits start() and returns its result. On an error it logs, alerts (at most hourly) and
    retries with a doubling backoff, so WCL trouble never takes the collector down."""
    delay = ERROR_BACKOFF_S[0]
    while True:
        began = time.monotonic()
        try:
            return await start()
        except asyncio.CancelledError:
            raise
        except Exception:
            detail = traceback.format_exc()
        if time.monotonic() - began > ERROR_BACKOFF_S[1]:
            delay = ERROR_BACKOFF_S[0]
        log(f"[wcl] {name} failed, retrying in {delay}s:\n{detail}")
        await reporter.stats.increment("wcl_task_errors")
        await reporter.send_alert(f"WCL {name} failed", f"Retrying in {delay}s.\n```{detail[-1500:]}```",
                                  throttle_key=f"wcl-{name}", throttle_seconds=3600)
        await asyncio.sleep(delay)
        delay = min(delay * 2, ERROR_BACKOFF_S[1])


async def wait_for_zone(client, dungeons, reporter, log):
    """zone_dungeons, waiting hourly while WCL has no active M+ zone (one alert per wait)."""
    alerted = False
    while True:
        try:
            return await zone_dungeons(client, dungeons)
        except NoMplusZone as e:
            log(f"[wcl] {e}, checking again in {NO_ZONE_RECHECK_S}s")
            reporter.stats.set_status("wcl_state", "no active M+ zone")
            if not alerted:
                await reporter.send_alert("WCL: no active Mythic+ zone",
                                          f"{e}. The WCL collector checks again every hour.", level="warning")
                alerted = True
        await asyncio.sleep(NO_ZONE_RECHECK_S)


async def run_wcl(reporter, write_gate, log=print):
    """The collector's WCL task: sweeper and worker on one client, so they share its pacing."""
    static = load_static()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        client = WclClient(session)
        enc_ids = await _supervised("zone lookup", lambda: wait_for_zone(client, static["dungeons"], reporter, log),
                                    reporter, log)
        log(f"[wcl] M+ zone resolved, {len(enc_ids)} dungeons, sweeper and worker starting")
        stats = reporter.stats
        stats.set_status("wcl_state", "running")
        await asyncio.gather(
            _supervised("sweeper", lambda: run_sweeper(client, static, enc_ids, write_gate, log, stats), reporter, log),
            _supervised("worker", lambda: run_worker(client, static, enc_ids, write_gate, log, stats), reporter, log))


# Debug CLI.

class CachedRun:
    """Stands in for WclClient on one run of the local event cache (--write-local)."""

    def __init__(self, cached):
        self.cached = cached

    async def fight(self, code, fight_id):
        return self.cached["fight"], self.cached["actors"]

    async def events(self, code, fight, queries):
        missing = set(queries) - set(self.cached["events"])
        if missing:
            raise RuntimeError(f"cached run lacks {sorted(missing)}: re-cache it with --friendly-sightings")
        return {alias: self.cached["events"][alias] for alias in queries}


def init_local_pool():
    db.init_connection_pool(os.environ["DATABASE_HOST"], os.environ["DATABASE_USER"],
                            os.environ["DATABASE_PASSWORD"], os.environ["DATABASE_NAME"],
                            os.environ["DATABASE_PORT"], pool_size=2)


async def dry_run(args):
    static = load_static()
    cache_path = os.path.join(EVENT_CACHE_DIR, f"{args.code}_{args.fight}.json")
    if args.from_cache:
        cached = load_json(cache_path)
        fight, actor_list, events, route = cached["fight"], cached["actors"], cached["events"], cached["route"]
        route = [[tuple(npc_count) for npc_count in pull] for pull in route] if route else None
    else:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            client = WclClient(session)
            fight, actor_list = await client.fight(args.code, args.fight)
            events = await fetch_events(client, args.code, fight, {a["id"]: a for a in actor_list}, static,
                                        args.friendly_sightings)
            route = await fetch_route(session, args.route) if args.route else None
            print(f"{sum(map(len, events.values()))} events, points this hour "
                  f"{client.rate['pointsSpentThisHour']:.0f}/{client.rate['limitPerHour']}")
        if args.cache:
            os.makedirs(EVENT_CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"fight": fight, "actors": actor_list, "events": events, "route": route}, f)
            print(f"cached to {cache_path}")
    actors = {a["id"]: a for a in actor_list}
    cm, specs, run = build(fight, actors, events, static)
    print(f"{static['dungeons'][cm]['name']['en_US']} +{fight.get('keystoneLevel')}")
    print_run(run, fight, route)
    print_wcl_pull_links(run, fight, actors)
    if args.pack_truth:
        print_pack_accuracy(run, load_json(args.pack_truth))
    ignored = Counter(m.npc for m in run["mobs"].values() if m.ignored)
    never = Counter(m.npc for m in run["mobs"].values() if m.engage is None and not m.ignored)
    uncredited = Counter(m.npc for m in run["mobs"].values() if m.engage is not None and not m.credited)
    print(f"\nignored (killed, but no MDT clone left or in range): {sorted(ignored.items())}")
    print(f"seen but never engaged (never lost HP, never died): {sorted(never.items())}")
    print(f"engaged, not credited (no death, or no free slot at death): {sorted(uncredited.items())}")
    for lust_row in run["lusts"]:
        print(f"\nlust {lust_row}")
    print_deltas(pb.run_deltas(run, specs, static["cooldowns"], static["cooldown_categories"]))
    if args.write_local:
        init_local_pool()
        queued = (args.code, args.fight, cm, int(time.time() * 1000), fight["keystoneLevel"], 0)
        status, n = await process_run(CachedRun(cached), static, queued, contextlib.nullcontext())
        print(f"\nwrite-local into {os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}: {status}, {n} rows")


async def sweep_once(args):
    static = load_static()
    spec_row = next((r for r in static["spec_rows"] if r[2] == args.spec), None)
    if spec_row is None or args.dungeon not in static["dungeons"]:
        raise SystemExit(f"unknown dungeon {args.dungeon} or spec {args.spec}")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        client = WclClient(session)
        enc_ids = await zone_dungeons(client, static["dungeons"])
        fights = await ranked_fights(client, enc_ids[args.dungeon], spec_row, args.dungeon, int(time.time() * 1000))
        rate = client.rate
    done = set()
    if os.environ.get("DATABASE_HOST"):
        init_local_pool()
        done = _db(lambda c, cur: db.fetch_wcl_processed_runs(c, cur, [f[:2] for f in fights]))
    fresh = [f for f in fights if f[:2] not in done]
    for code, fight_id, _, start_ms, level in sorted(fresh, key=lambda f: -f[3]):
        print(f"{code} {fight_id:>4} +{level:<3} {datetime.fromtimestamp(start_ms / 1000, timezone.utc):%Y-%m-%d %H:%M}")
    print(f"\n{static['dungeons'][args.dungeon]['name']['en_US']} {spec_row[1]} {spec_row[0]}: {len(fights)} ranked "
          f"runs in {SWEEP_DAYS} days, {len(done)} already processed, {len(fresh)} would be queued. Database points "
          f"this hour {rate['databasePointsSpentThisHour']:.0f}/{rate['databaseLimitPerHour']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", nargs=2, metavar=("CODE", "FIGHT"))
    mode.add_argument("--sweep-once", action="store_true", help="print what one sweep of --dungeon/--spec would queue")
    ap.add_argument("--dungeon", help="sweep-once: dungeons.json id (cm id)")
    ap.add_argument("--spec", type=int, help="sweep-once: specs.json id")
    ap.add_argument("--route", help="keystone.guru route key to compare with")
    ap.add_argument("--cache", action="store_true",
                    help="dry run: save this run's raw events and route to the local event cache")
    ap.add_argument("--from-cache", action="store_true", help="dry run offline from the local event cache")
    ap.add_argument("--pack-truth", metavar="PATH", help="dry run: score pack assignment against a reference file")
    ap.add_argument("--friendly-sightings", action="store_true",
                    help="also use player damage on enemies as sightings (more points)")
    ap.add_argument("--write-local", action="store_true",
                    help="dry run from cache: also process the run into the throwaway DB at DATABASE_*")
    args = ap.parse_args()
    if args.sweep_once:
        if not args.dungeon or args.spec is None:
            ap.error("--sweep-once needs --dungeon and --spec")
        asyncio.run(sweep_once(args))
        return
    if args.write_local and not args.from_cache:
        ap.error("--write-local needs --from-cache")
    args.code, args.fight = args.dry_run[0], int(args.dry_run[1])
    asyncio.run(dry_run(args))


if __name__ == "__main__":
    main()
