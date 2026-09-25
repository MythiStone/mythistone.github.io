"""Season-wide comparison context for social posts: every spec's runs, timed
rate, tier and role rank, and every dungeon's tier and highest timed key.

Hooks, the weekly snapshot, the weekly-mover and the underdog generators all
read this, so it is loaded once per process (load_season_context caches)."""

import os
from contextlib import closing

import databaseConnector
from commonUtils import (
    LOOKUP_DIR,
    get_class_lookup,
    get_dungeon_lookup,
    get_spec_lookup,
    load_json,
)
from pageGeneration import ROLE_FOLDERS
from tierMath import build_ckmeans_tiers, build_spec_tiers

ROLE_NAMES = {"0": "tank", "1": "healer", "2": "DPS"}

_cache = {}


def _timed(row):
    return row["upgrade_1"] + row["upgrade_2"] + row["upgrade_3"]


def _tier_by_id(tiers, id_key):
    return {str(it[id_key]): letter for letter, items in tiers.items() for it in items}


def _hero_trees(hero_rows, spec_id):
    """Per hero tree share and timed rate for one spec, largest first."""
    sub_trees = load_json(os.path.join(LOOKUP_DIR, "talents", f"{spec_id}.json")).get("subTrees", {})
    agg = {}
    for r in hero_rows:
        if str(r["spec_id"]) != str(spec_id) or str(r["hero_talent_id"]) not in sub_trees:
            continue
        a = agg.setdefault(r["hero_talent_id"], {"runs": 0, "timed": 0})
        a["runs"] += r["total_runs"]
        a["timed"] += _timed(r)
    total = sum(a["runs"] for a in agg.values())
    out = [
        {
            "name": sub_trees[str(hid)]["name"],
            "runs": a["runs"],
            "share": a["runs"] / total * 100,
            "timed_pct": a["timed"] / a["runs"] * 100,
        }
        for hid, a in agg.items()
        if a["runs"]
    ]
    return sorted(out, key=lambda t: t["runs"], reverse=True)


def build_spec_context(spec_rows, hero_rows=()):
    """{str(spec_id): stats} from fetch_spec_upgrades (+ fetch_spec_hero_upgrades) rows.

    ``share`` is the percentage of groups featuring the spec, approximated as
    spec runs over total tank runs (every group has exactly one tank)."""
    spec_lookup = get_spec_lookup()
    class_lookup = get_class_lookup()
    per_spec = {}
    for r in spec_rows:
        sid = str(r["spec_id"])
        if sid not in spec_lookup:
            continue
        a = per_spec.setdefault(sid, {"runs": 0, "timed": 0, "three": 0})
        a["runs"] += r["total_runs"]
        a["timed"] += _timed(r)
        a["three"] += r["upgrade_3"]

    tier_of = _tier_by_id(build_spec_tiers(spec_lookup, class_lookup, list(spec_rows)), "spec_id")
    groups = sum(a["runs"] for sid, a in per_spec.items() if str(spec_lookup[sid].get("role")) == "0") or 1

    ctx = {}
    for sid, a in per_spec.items():
        if not a["runs"]:
            continue
        meta = spec_lookup[sid]
        class_meta = class_lookup.get(str(meta.get("classID", "")), {})
        role = str(meta.get("role", "2"))
        ctx[sid] = {
            "spec_id": sid,
            "name": f"{meta.get('name', '')} {class_meta.get('name', '')}".strip(),
            "role": role,
            "role_name": ROLE_NAMES.get(role, "DPS"),
            "role_folder": ROLE_FOLDERS.get(role, "Dps"),
            "runs": a["runs"],
            "share": a["runs"] / groups * 100,
            "timed_pct": a["timed"] / a["runs"] * 100,
            "three_pct": a["three"] / a["runs"] * 100,
            "tier": tier_of.get(sid, ""),
            "hero_trees": _hero_trees(hero_rows, sid) if hero_rows else [],
        }

    for role in {s["role"] for s in ctx.values()}:
        members = sorted((s for s in ctx.values() if s["role"] == role), key=lambda s: s["runs"], reverse=True)
        avg_timed = sum(s["timed_pct"] for s in members) / len(members)
        for rank, s in enumerate(members, start=1):
            s["role_rank"] = rank
            s["role_count"] = len(members)
            s["role_avg_timed_pct"] = avg_timed
    return ctx


def build_dungeon_context(dungeon_rows, max_timed_levels=None):
    """{str(dungeon_id): stats} from fetch_runs_per_dungeon_per_level rows."""
    dungeon_lookup = get_dungeon_lookup()
    tiers = build_ckmeans_tiers(dungeon_lookup, list(dungeon_rows), max_timed_levels=max_timed_levels)
    ctx = {}
    for letter, items in tiers.items():
        for it in items:
            did = str(it["dungeon_id"])
            meta = dungeon_lookup.get(did, {})
            name = meta.get("name", {})
            runs = int(it.get("total_runs", 0))
            if not runs:
                continue
            ctx[did] = {
                "dungeon_id": did,
                "name": name.get("en_US", f"Dungeon {did}") if isinstance(name, dict) else str(name),
                "tier": letter,
                "runs": runs,
                "timed_pct": sum(int(it.get(k, 0)) for k in ("upgrade_1", "upgrade_2", "upgrade_3")) / runs * 100,
                "max_timed": int(it.get("max_timed_level", 0)),
            }
    ranked = sorted(ctx.values(), key=lambda d: d["runs"], reverse=True)
    avg_timed = sum(d["timed_pct"] for d in ranked) / len(ranked) if ranked else 0
    for rank, d in enumerate(ranked, start=1):
        d["runs_rank"] = rank
        d["count"] = len(ranked)
        d["avg_timed_pct"] = avg_timed
    return ctx


def load_season_context(season):
    """{"specs": ..., "dungeons": ...} for the season, fetched once per process."""
    if season in _cache:
        return _cache[season]
    with closing(databaseConnector.get_connection()) as conn:
        cursor = conn.cursor()
        try:
            spec_rows = databaseConnector.fetch_spec_upgrades(conn, cursor)
            hero_rows = databaseConnector.fetch_spec_hero_upgrades(conn, cursor)
            dungeon_rows = databaseConnector.fetch_runs_per_dungeon_per_level(conn, cursor, season)
            max_timed = databaseConnector.fetch_max_timed_level_per_dungeon(conn, cursor, season)
        finally:
            cursor.close()
    _cache[season] = {
        "specs": build_spec_context(spec_rows, hero_rows),
        "dungeons": build_dungeon_context(dungeon_rows, max_timed),
    }
    return _cache[season]


def find_spec_by_name(ctx, name):
    """Match a display name ("Arms Warrior" or "Arms - Warrior") to its context entry."""
    wanted = " ".join((name or "").replace(" - ", " ").split()).lower()
    for s in (ctx or {}).get("specs", {}).values():
        if s["name"].lower() == wanted:
            return s
    return None


def find_dungeon_by_name(ctx, name):
    wanted = (name or "").strip().lower()
    for d in (ctx or {}).get("dungeons", {}).values():
        if d["name"].lower() == wanted:
            return d
    return None


def underdog_candidates(ctx):
    """Specs in S or A tier that sit in the less-played half of their role,
    best story first (higher tier, then rarer)."""
    picks = [
        s for s in ctx["specs"].values()
        if s["tier"] in ("S", "A") and s["role_rank"] > s["role_count"] / 2
    ]
    return sorted(picks, key=lambda s: (s["tier"] != "S", -s["role_rank"] / s["role_count"]))
