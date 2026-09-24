"""Talent build paths: hero tree -> core build -> class variant.

Pure (no DB, no Jinja). Input is ``databaseConnector.fetch_loadout_key_levels``
rows plus the top-50 players' export strings; output feeds the spec page's
Talent Builds modal. See AGENTS.md "Talent build paths" for why each rule exists.
"""
import math
from collections import Counter, defaultdict

from commonUtils import decode_loadout, loadout_spec_id

BUILD_MERGE_MAX_POINTS = 1       # a neighbour this many points away folds in as "flex"
BUILD_MERGE_MAX_RATIO = 0.25     # ...unless it has at least this share of the leader's runs
BUILD_MIN_RUNS = 30
BUILD_MIN_VARIANT_RUNS = 15
BUILD_MIN_SHARE = 0.03
BUILD_TOP_N = 5
BUILD_LOW_COVERAGE = 0.30        # shown builds cover less than this -> "no dominant build"
BUILD_FLEX_MIN_PCT = 5.0         # a pick counts as flex when at least this % of the build's runs differ on it
BUILD_MAX_DROP_SHARE = 0.5       # more dropped runs than this means a broken tree file
BUILD_TOP50_BADGE_SHARE = 0.25   # TOP when at least this share of the parent's top-50 loadouts match
BUILD_TOP50_MIN_LOADOUTS = 5     # ...and at least this many (also the floor for the extra top-50 row)

SECTIONS = ("class", "spec", "hero")


def canonical_build(code, spec_id, hero_tree_id, full_node_order, nodes):
    """(core, cls, totals, active_tree) for one loadout string, or
    (reason, None, None, None).

    core/cls are frozensets of (node_id, (entry_index, rank)). Strings also keep
    the INACTIVE hero tree's picks, so hero nodes count only for the tree the
    string's hero-selection ("sub") node points at. ``hero_tree_id`` None accepts
    whichever tree that is (top-50 strings carry no separate hero id).
    """
    if loadout_spec_id(code) != int(spec_id):
        return "spec_mismatch", None, None, None
    decoded = decode_loadout(code, full_node_order, nodes)
    if decoded is None:
        return "decode_fail", None, None, None
    active = None
    picks = []
    for nid, sel in decoded.items():
        node = nodes.get(str(nid))
        if node is None:
            # Exports also flag granted, unpurchased nodes of hero trees the spec
            # cannot pick (Windwalker strings carry Master of Harmony's free entry
            # node). They spend no points, so only a purchased unknown node is stale data.
            if not sel["purchased"]:
                continue
            return "unknown_node", None, None, None
        if node.get("g") == "sub":
            entries = node.get("entries") or []
            if sel["entry_index"] < len(entries):
                active = entries[sel["entry_index"]].get("subTreeId")
            continue
        if node.get("free") or not sel["purchased"]:
            continue
        rank = sel["rank"] if sel["rank"] is not None else int(node.get("maxRanks") or 1)
        picks.append((nid, node, sel["entry_index"], rank))
    if active is None:
        return "no_sub", None, None, None
    if hero_tree_id is not None and int(active) != int(hero_tree_id):
        return "tree_mismatch", None, None, None
    core, cls, totals = [], [], Counter()
    for nid, node, entry, rank in picks:
        g = node.get("g")
        if g == "hero" and node.get("subTreeId") != active:
            continue
        if g not in SECTIONS:
            continue
        (cls if g == "class" else core).append((nid, (entry, rank)))
        totals[g] += rank
    return frozenset(core), frozenset(cls), totals, int(active)


def points_distance(a, b):
    """Talent points moved between two builds: a changed choice entry counts as
    its whole rank removed plus the other entry's rank added."""
    da, db = dict(a), dict(b)
    moved = 0
    for nid in da.keys() | db.keys():
        x, y = da.get(nid), db.get(nid)
        if x == y:
            continue
        if x and y and x[0] == y[0]:
            moved += abs(x[1] - y[1])
        else:
            moved += (x[1] if x else 0) + (y[1] if y else 0)
    return math.ceil(moved / 2)


def is_choice_flip(a, b):
    """True when two builds pick the same nodes and differ only in which option a
    choice node takes."""
    da, db = dict(a), dict(b)
    return da.keys() == db.keys() and all(da[n][0] != db[n][0] for n in da if da[n] != db[n])


def cluster_builds(entries):
    """Leader clustering without chaining. ``entries`` are dicts with ``key`` and
    ``runs``. A key joins its nearest leader within BUILD_MERGE_MAX_POINTS when it
    is under BUILD_MERGE_MAX_RATIO of that leader's own runs, so a popular
    one-point alternative stays a build of its own. A choice flip always joins:
    as a card its only change would be that flip, which the leader already shows
    as the choice node's per-option shares."""
    leaders = []
    for e in sorted(entries, key=lambda e: -e["runs"]):
        best, best_d = None, None
        for lead in leaders:
            # d <= 1 allows at most 2 differing nodes (4 items in the symmetric difference)
            if len(e["key"] ^ lead["key"]) > 2 * (BUILD_MERGE_MAX_POINTS + 1):
                continue
            d = points_distance(e["key"], lead["key"])
            if d <= BUILD_MERGE_MAX_POINTS and (best_d is None or d < best_d):
                best, best_d = lead, d
        if best is not None and (
            e["runs"] < BUILD_MERGE_MAX_RATIO * best["members"][0]["runs"]
            or is_choice_flip(e["key"], best["key"])
        ):
            best["members"].append(e)
            best["runs"] += e["runs"]
        else:
            leaders.append({"key": e["key"], "runs": e["runs"], "members": [e]})
    leaders.sort(key=lambda c: -c["runs"])
    return leaders


def diff_nodes(a, b):
    """Chips turning build ``b`` into ``a``: [(sign, node_id, entry, rank)]."""
    da, db = dict(a), dict(b)
    chips = []
    for nid in sorted(da.keys() | db.keys()):
        x, y = da.get(nid), db.get(nid)
        if x == y:
            continue
        if x and y and x[0] == y[0]:
            chips.append(("~", nid, x[0], x[1]))
            continue
        if x:
            chips.append(("+", nid, x[0], x[1]))
        if y:
            chips.append(("-", nid, y[0], y[1]))
    return chips


def _flex(cluster):
    """Node-entry picks the cluster's members disagree on: {(nid, entry): % of runs}."""
    counts = Counter()
    for m in cluster["members"]:
        for nid, (entry, _rank) in m["key"]:
            counts[(nid, entry)] += m["runs"]
    total = cluster["runs"]
    flex = {}
    for k, c in counts.items():
        pct = c / total * 100.0
        if BUILD_FLEX_MIN_PCT <= pct <= 100.0 - BUILD_FLEX_MIN_PCT:
            flex[k] = round(pct, 1)
    return flex


def _finish(c, parent_runs):
    c["max_timed"] = max(m["max_timed"] for m in c["members"])
    c["max_depleted"] = max(m["max_depleted"] for m in c["members"])
    c["share"] = c["runs"] / parent_runs * 100.0
    c["flex"] = _flex(c)
    return c


def _summaries(clusters, parent_runs, min_runs):
    return [
        _finish(c, parent_runs) for c in clusters
        if c["runs"] >= min_runs and c["runs"] / parent_runs >= BUILD_MIN_SHARE
    ][:BUILD_TOP_N]


def _matcher(clusters):
    """key -> index of the cluster that holds it exactly, else of the nearest
    leader within BUILD_MERGE_MAX_POINTS, else None. Used to place top-50
    strings, which need not occur in the general population."""
    exact = {m["key"]: i for i, c in enumerate(clusters) for m in c["members"]}

    def match(key):
        if key in exact:
            return exact[key]
        best, best_d = None, None
        for i, c in enumerate(clusters):
            if len(key ^ c["key"]) > 2 * (BUILD_MERGE_MAX_POINTS + 1):
                continue
            d = points_distance(key, c["key"])
            if d <= BUILD_MERGE_MAX_POINTS and (best_d is None or d < best_d):
                best, best_d = i, d
        return best
    return match


def _is_top(count, parent_count):
    return count >= BUILD_TOP50_MIN_LOADOUTS and count >= BUILD_TOP50_BADGE_SHARE * parent_count


def _group(items, section):
    """Sum loadout items into one entry per ``section`` ("core" / "cls") key."""
    groups = {}
    for it in items:
        k = it[section]
        g = groups.setdefault(k, {"key": k, "runs": 0, "max_timed": 0, "max_depleted": 0})
        g["runs"] += it["runs"]
        g["max_timed"] = max(g["max_timed"], it["max_timed"])
        g["max_depleted"] = max(g["max_depleted"], it["max_depleted"])
    return list(groups.values())


def _picks(core, cls):
    return {str(nid): [entry, rank] for nid, (entry, rank) in (*core, *cls)}


def _core_view(c, build_id, items, lead_core, top_loads, top_total):
    """Display dict for one core cluster with its class variants and top-50 counts.
    ``top_loads`` are the decoded top-50 strings matched to this cluster."""
    member_keys = {m["key"] for m in c["members"]}
    in_core = [it for it in items if it["core"] in member_keys]
    all_variants = cluster_builds(_group(in_core, "cls"))
    variants = _summaries(all_variants, c["runs"], BUILD_MIN_VARIANT_RUNS)
    match = _matcher(all_variants)
    variant_top = Counter()
    for t in top_loads:
        k = match(t["cls"])
        if k is not None:
            variant_top[id(all_variants[k])] += 1
    out_variants, srcs = [], []
    for j, v in enumerate(variants, 1):
        v_members = {m["key"] for m in v["members"]}
        pool = [it for it in in_core if it["cls"] in v_members]
        # prefer the exact core + variant leader, then the core cluster
        exact = [it for it in pool if it["core"] == c["key"] and it["cls"] == v["key"]]
        srcs.append(max(exact or pool, key=lambda it: it["runs"]))
        view = _display(v, f"{build_id}.v{j}", srcs[-1], variants[0]["key"])
        view["top50_count"] = variant_top[id(v)]
        view["top50"] = _is_top(variant_top[id(v)], len(top_loads))
        out_variants.append(view)
    # A core card is its most-run variant, so B1 and B1.V1 paint and export the same build.
    src = srcs[0] if srcs else max(
        (it for it in in_core if it["core"] == c["key"]), key=lambda it: it["runs"]
    )
    out = _display(c, build_id, src, lead_core)
    out["variants"] = out_variants
    out["other_variant_share"] = max(0.0, 100.0 - sum(v["share"] for v in variants))
    out["top50_count"] = len(top_loads)
    out["top50"] = _is_top(len(top_loads), top_total)
    return out


def _decode_top50(top50, spec_id, full_node_order, nodes, budget, drops):
    """{hero_tree_id: [decoded top-50 string]} from (loadout_text, keystone_level)."""
    by_tree = defaultdict(list)
    for code, level in top50:
        core, cls, totals, active = canonical_build(code, spec_id, None, full_node_order, nodes)
        if cls is None:
            drops["top50_" + core] += 1
            continue
        if any(totals[g] < budget.get((g, active if g == "hero" else None), 0) for g in SECTIONS):
            drops["top50_incomplete"] += 1
            continue
        by_tree[active].append({"code": code, "core": core, "cls": cls, "level": int(level or 0)})
    return by_tree


def _top_only_extra(group, loads, lead_core, top_total):
    """The extra row for a top-50 build nobody else runs: no population stats,
    its string is the most common top-50 export in the group."""
    member_keys = {m["key"] for m in group["members"]}
    mine = [t for t in loads if t["core"] in member_keys]
    code = Counter(t["code"] for t in mine).most_common(1)[0][0]
    src = next(t for t in mine if t["code"] == code)
    return {
        "id": "t1",
        "runs": 0,
        "share": 0.0,
        "max_timed_key": max(t["level"] for t in mine),
        "max_depleted_key": 0,
        "merged": len(group["members"]) - 1,
        "code": code,
        "picks": _picks(src["core"], src["cls"]),
        "diff": diff_nodes(group["key"], lead_core) if lead_core else [],
        "flex": {},
        "variants": [],
        "other_variant_share": 0.0,
        "top50_count": len(mine),
        "top50": _is_top(len(mine), top_total),
    }


def build_hero_tree_builds(rows, spec_id, full_node_order, nodes, top50=()):
    """Build paths per hero tree from (hero_id, loadout, level, timed, runs) rows.

    ``top50`` holds the top-50 players' (loadout_text, keystone_level), one per
    player per dungeon; each is matched to a build (and variant) and counted.

    Returns ({hero_tree_id: tree}, drops) where drops = {reason: runs} (top-50
    drops count strings, under "top50_*"). A tree is {"runs", "coverage",
    "other_share", "low_coverage", "cores", "top50_total", "top50_extra"}; each
    core and variant carries id, runs, share, max_timed_key / max_depleted_key
    (0 = none), code (a real collected string), picks {node: [entry, rank]}, diff
    chips, flex picks, top50_count and top50 (the TOP badge). top50_extra is the
    top-50's most used build when it is not a listed core, else None.
    Raises when more than BUILD_MAX_DROP_SHARE of the runs cannot be decoded.
    """
    per_code = {}
    for hero_id, code, level, timed, runs in rows:
        k = (int(hero_id), code)
        rec = per_code.setdefault(k, {"runs": 0, "max_timed": 0, "max_depleted": 0})
        rec["runs"] += int(runs)
        side = "max_timed" if timed else "max_depleted"
        rec[side] = max(rec[side], int(level))

    drops = Counter()
    decoded = []
    totals_seen = defaultdict(Counter)
    for (hero_id, code), rec in per_code.items():
        if not hero_id:
            drops["no_hero_id"] += rec["runs"]
            continue
        core, cls, totals, _active = canonical_build(code, spec_id, hero_id, full_node_order, nodes)
        if cls is None:
            drops[core] += rec["runs"]
            continue
        for g in SECTIONS:
            totals_seen[(g, hero_id if g == "hero" else None)][totals[g]] += rec["runs"]
        decoded.append({"hero": hero_id, "code": code, "core": core, "cls": cls,
                        "totals": totals, **rec})

    total_runs = sum(r["runs"] for r in per_code.values())
    if total_runs and sum(drops.values()) > BUILD_MAX_DROP_SHARE * total_runs:
        raise ValueError(
            f"talentBuilds: spec {spec_id} dropped {dict(drops)} of {total_runs} runs; "
            "is data/static/talents/<spec>.json out of date?"
        )

    # The normal point budget per section is its most common total, so partial
    # (levelling / unfinished) builds drop without hardcoding patch numbers.
    budget = {k: c.most_common(1)[0][0] for k, c in totals_seen.items()}
    by_tree = defaultdict(list)
    for it in decoded:
        if any(it["totals"][g] < budget[(g, it["hero"] if g == "hero" else None)] for g in SECTIONS):
            drops["incomplete"] += it["runs"]
            continue
        by_tree[it["hero"]].append(it)
    top_by_tree = _decode_top50(top50, spec_id, full_node_order, nodes, budget, drops)

    result = {}
    for hero_id, items in by_tree.items():
        tree_runs = sum(it["runs"] for it in items)
        all_cores = cluster_builds(_group(items, "core"))
        cores = _summaries(all_cores, tree_runs, BUILD_MIN_RUNS)
        lead_core = cores[0]["key"] if cores else None

        loads = top_by_tree.get(hero_id, [])
        match = _matcher(all_cores)
        top_by_cluster = defaultdict(list)
        top_only = []
        for t in loads:
            k = match(t["core"])
            (top_only if k is None else top_by_cluster[id(all_cores[k])]).append(t)

        out_cores = [
            _core_view(c, f"b{i}", items, lead_core, top_by_cluster[id(c)], len(loads))
            for i, c in enumerate(cores, 1)
        ]

        # The top-50's most used build gets its own row when it is not listed.
        extra, extra_share = None, 0.0
        top_groups = cluster_builds(
            [{"key": k, "runs": n} for k, n in Counter(t["core"] for t in top_only).items()]
        )
        pop_best = max(all_cores, key=lambda c: len(top_by_cluster[id(c)]), default=None)
        pop_count = len(top_by_cluster[id(pop_best)]) if pop_best else 0
        only_count = top_groups[0]["runs"] if top_groups else 0
        if max(pop_count, only_count) >= BUILD_TOP50_MIN_LOADOUTS:
            if pop_count >= only_count and not any(pop_best is c for c in cores):
                _finish(pop_best, tree_runs)
                extra = _core_view(pop_best, "t1", items, lead_core, top_by_cluster[id(pop_best)], len(loads))
                extra_share = pop_best["share"]
            elif only_count > pop_count:
                extra = _top_only_extra(top_groups[0], top_only, lead_core, len(loads))

        coverage = sum(c["share"] for c in cores)
        result[hero_id] = {
            "runs": tree_runs,
            "coverage": coverage,
            "other_share": max(0.0, 100.0 - coverage - extra_share),
            "low_coverage": coverage < BUILD_LOW_COVERAGE * 100.0,
            "cores": out_cores,
            "top50_total": len(loads),
            "top50_extra": extra,
        }
    return result, dict(drops)


def _display(cluster, build_id, src, lead_key):
    return {
        "id": build_id,
        "runs": cluster["runs"],
        "share": cluster["share"],
        "max_timed_key": cluster["max_timed"],
        "max_depleted_key": cluster["max_depleted"],
        "merged": len(cluster["members"]) - 1,
        "code": src["code"],
        "picks": _picks(src["core"], src["cls"]),
        "diff": [] if cluster["key"] == lead_key else diff_nodes(cluster["key"], lead_key),
        "flex": cluster["flex"],
    }
