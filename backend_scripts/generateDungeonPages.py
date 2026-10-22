import os
import glob
import json
import asyncio
import argparse
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import databaseConnector
import commonUtils
import compArchetypes
from pageGeneration import (
    load_notifications,
    generateSpecNav, make_jinja_env,
    generateDungeonNav,
    build_item_slug_map,
    ROLE_FOLDERS,
    build_trends,
    trend_feeds_for_dungeon,
)
from generateSpecPages import format_duration, format_utc_timestamp, format_iso_timestamp, load_json, load_season_info, upgrade_info
from generateItemPages import slot_for_item
from fetchNpcInfo import get_npc_names_retail
from image_generation.dungeon_overview import createDungeonOverviewImg, fetch_route_thumbnail

LOOKUP_DIR = "data/static"

# Latest Hotfixes card only shows fixes at most this many days old (age from build time).
HOTFIX_MAX_AGE_DAYS = 7

# Boss Pacing card: a "+N or higher" filter is offered once that many timed routes qualify.
PACING_MIN_ROUTES = 10
# Boss Pacing card: the Bloodlust icon marks a section only when this share of runs lust there.
LUST_ICON_MIN_PCT = 65

def parse_run_rows(rows):
    if not rows:
        return None
    rows = list(rows)
    if not rows:
        return None

    first = rows[0]
    is_dict = isinstance(first, dict)
    
    seen = set()
    members = []
    for r in rows:
        mid = r['member'] if is_dict else r[8]
        mspec = r['spec_id'] if is_dict else r[9]
        if mid is None:
            continue
        if mid in seen:
            continue
        seen.add(mid)
        members.append({
            "member_id": int(mid),
            "spec_id": int(mspec) if mspec is not None else None,
        })

    if is_dict:
        return {
            "run_id": int(first['run_id']) if first.get('run_id') is not None else None,
            "dungeon_id": first.get('dungeon_id'),
            "keystone_level": int(first['keystone_level']) if first.get('keystone_level') is not None else None,
            "duration": int(first['duration']) if first.get('duration') is not None else None,
            "timestamp": int(first['timestamp']) if first.get('timestamp') is not None else None,
            "faction": first.get('faction'),
            "region": first.get('region'),
            "season": int(first['season']) if first.get('season') is not None else None,
            "members": members,
        }
    else:
        return {
            "run_id": int(first[5]) if len(first) > 5 and first[5] is not None else None,
            "dungeon_id": first[0] if len(first) > 0 else None,
            "keystone_level": int(first[1]) if len(first) > 1 and first[1] is not None else None,
            "duration": int(first[2]) if len(first) > 2 and first[2] is not None else None,
            "timestamp": int(first[3]) if len(first) > 3 and first[3] is not None else None,
            "faction": first[4] if len(first) > 4 else None,
            "region": first[6] if len(first) > 6 else None,
            "season": int(first[7]) if len(first) > 7 and first[7] is not None else None,
            "members": members,
        }


def pull_boss_ids(top_npcs_str, dungeon_bosses):
    """Boss npc ids (str) in a lust pull signature ('npc_id:count,...'), in pull order."""
    ids = []
    for n in str(top_npcs_str or '').split(','):
        if n.strip() and int(n.split(':')[0].strip()) in dungeon_bosses:
            ids.append(n.split(':')[0].strip())
    return ids


def _spread(values):
    """(median, p25, p75) of a list, or Nones when it is empty."""
    if not values:
        return None, None, None
    if len(values) == 1:
        return values[0], values[0], values[0]
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q2, q1, q3


def route_lust(route_pulls, all_bosses):
    """Lust sections of one route from its (boss names, lusted) pulls in pull order.

    A boss spans its first to last pull. Its trash runs from the previous boss's last pull
    (or the key start), and ('trash', None) is everything after the last boss pull, only on
    routes that pull every boss (keystone.guru can drop a boss, which would make its
    trash look like the end of the run)."""
    span = {}
    for i, (names, _lusted) in enumerate(route_pulls):
        for name in names:
            span[name] = (span.get(name, (i, i))[0], i)
    lusted = [i for i, (_n, l) in enumerate(route_pulls) if l]
    sections = set()
    for name, (first, last) in span.items():
        prev = max((l for f, l in span.values() if l < first), default=-1)
        if any(first <= i <= last for i in lusted):
            sections.add(('boss', name))
        if any(prev < i < first for i in lusted):
            sections.add(('trash', name))
    if span.keys() >= all_bosses and any(i > max(l for _f, l in span.values()) for i in lusted):
        sections.add(('trash', None))
    return set(span), sections


def build_boss_pacing(encounter_rows, death_rows, pull_rows, dungeon_bosses, timer_ms):
    """Boss Pacing card data: one bucket per "+N or higher" key-level filter.

    The queries return timed routes only, so every number is a pace to beat. Pulls carry
    no timestamps, so a death is placed on the boss whose fight window holds it, else on
    the trash leading up to that route's next boss. Lust is placed by pull order instead
    (route_lust), over the routes that pull that boss, and joins the cards by boss name."""
    routes = {}
    boss_names = defaultdict(Counter)
    for r in encounter_rows or []:
        route = routes.setdefault(r['route_key'], {
            'level': int(r['keystone_level']),
            'duration': int(r['duration']), 'encounters': [], 'deaths': []})
        route['encounters'].append((int(r['started_at_ms']), int(r['ended_at_ms']), int(r['ordinal'])))
        if r.get('boss_name'):
            boss_names[int(r['ordinal'])][r['boss_name']] += 1
    for r in death_rows or []:
        route = routes.get(r['route_key'])
        if route is not None and r['died_at_ms'] is not None:
            route['deaths'].append(int(r['died_at_ms']))
    if not routes:
        return {"levels": [], "buckets": []}

    boss_of = {npc: b['name'] for b in dungeon_bosses for npc in b['npc_ids']}
    journal_names = {b['name'] for b in dungeon_bosses}
    pulls = defaultdict(list)
    for r in pull_rows or []:
        npcs = {int(n) for n in str(r['npc_ids'] or '').split(',') if n.strip()}
        pulls[r['route_key']].append(({boss_of[n] for n in npcs if n in boss_of}, bool(r['lusted'])))
    for key, route in routes.items():
        route['pulled'], route['lust'] = route_lust(pulls.get(key, []), journal_names)

    def death_segment(encounters, t):
        for start, end, ordinal in encounters:
            if start <= t <= end:
                return ('boss', ordinal)
            if t < start:
                return ('trash', ordinal)
        return ('trash', None)

    def pct(ms):
        return min(100.0, max(0.0, ms / timer_ms * 100))

    def bucket(key, members):
        starts, ends, lengths, trash = (defaultdict(list) for _ in range(4))
        deaths, death_runs, lust_runs = defaultdict(int), defaultdict(int), defaultdict(int)
        for route in members:
            encounters = sorted(route['encounters'])
            prev_end = 0
            for start, end, ordinal in encounters:
                starts[ordinal].append(start)
                ends[ordinal].append(end)
                lengths[ordinal].append(end - start)
                trash[ordinal].append(max(0, start - prev_end))
                prev_end = end
            trash[None].append(max(0, route['duration'] - prev_end))
            hit = set()
            for t in route['deaths']:
                seg = death_segment(encounters, t)
                deaths[seg] += 1
                hit.add(seg)
            for seg in hit:
                death_runs[seg] += 1
            for seg in route['lust']:
                lust_runs[seg] += 1

        n = len(members)

        def lust_stats(seg):
            """Share of the routes that pull this section's boss (every boss for the end)."""
            name = seg[1]
            m = sum(1 for r in members if (name in r['pulled'] if name else r['pulled'] >= journal_names))
            return {"pct": lust_runs[seg] / m * 100, "routes": m} if m >= PACING_MIN_ROUTES else None

        def death_stats(seg):
            return {"per_run": deaths[seg] / n, "run_pct": death_runs[seg] / n * 100}

        bosses = []
        for ordinal in sorted(starts, key=lambda o: statistics.median(starts[o])):
            start, p25, p75 = _spread(starts[ordinal])
            end = statistics.median(ends[ordinal])
            name = boss_names[ordinal].most_common(1)[0][0] if boss_names[ordinal] else None
            if name and name not in journal_names:
                raise RuntimeError(f"Raider.IO boss '{name}' is not a journal boss of this dungeon "
                                   f"{sorted(journal_names)}; rerun fetchDungeonData.py")
            bosses.append({
                "name": name or f"Boss {ordinal + 1}",
                "start": start, "start_p25": p25, "start_p75": p75, "end": end,
                "length": statistics.median(lengths[ordinal]),
                "trash_length": statistics.median(trash[ordinal]),
                "trash_deaths": death_stats(('trash', ordinal)),
                "boss_deaths": death_stats(('boss', ordinal)),
                "trash_lust": lust_stats(('trash', name)) if name else None,
                "boss_lust": lust_stats(('boss', name)) if name else None,
                "bar_left": pct(start), "bar_width": max(0.5, pct(end) - pct(start)),
            })
        # Bar labels alternate between two rows, so each may run until the boss after next.
        for i, cur in enumerate(bosses):
            limit = bosses[i + 2]["bar_left"] if i + 2 < len(bosses) else 100.0
            cur["label_width"] = limit - cur["bar_left"]
        after = {"length": statistics.median(trash[None]), "deaths": death_stats(('trash', None)),
                 "lust": lust_stats(('trash', None)),
                 "end": statistics.median(r['duration'] for r in members)}

        total_deaths = sum(deaths.values())
        boss_deaths = sum(c for (kind, _o), c in deaths.items() if kind == 'boss')
        max_per_run = max([b["trash_deaths"]["per_run"] for b in bosses]
                          + [after["deaths"]["per_run"]]) or 1
        return {
            "key": key,
            "routes": n,
            "deaths_per_run": total_deaths / n,
            "boss_death_pct": boss_deaths / total_deaths * 100 if total_deaths else None,
            "max_per_run": max_per_run,
            "bosses": bosses,
            "after": after,
        }

    # "Any key" covers the lowest level, so filters start one level above it, and a
    # level with no runs of its own would repeat the next level's numbers.
    levels = sorted({r['level'] for r in routes.values()})[1:]
    levels = [lvl for lvl in levels
              if sum(1 for r in routes.values() if r['level'] >= lvl) >= PACING_MIN_ROUTES]
    buckets = [bucket("", list(routes.values()))]
    buckets += [bucket(str(lvl), [r for r in routes.values() if r['level'] >= lvl]) for lvl in levels]
    return {"timer": timer_ms, "levels": levels, "buckets": buckets}


DUNGEON_INTRO_CLOSING = ("It is a snapshot of what is working right now, not a fixed guide, "
                         "so use it as a starting point for your own runs.")


def build_dungeon_intro(dungeon_id, dungeon_name, season_name, overall_stats, level_stats,
                        lust_timeline, dungeon_bosses, npc_names, team_comp_families):
    """Intro paragraphs from the numbers the dungeon page's cards already show.
    Clauses without data are dropped; the closing line always stays."""
    rng = commonUtils.intro_rng(dungeon_id)
    p1, p2 = [], []

    total = (overall_stats or {}).get('total_runs') or 0
    if total:
        timed = sum((overall_stats.get(f'upgrade_{i}') or 0) for i in (1, 2, 3))
        timed_pct = round(timed / total * 100, 1)
        p1.append(rng.choice([
            f"MythiStone has logged {total:,} {dungeon_name} runs in {season_name} so far, "
            f"and {timed_pct}% of them were timed.",
            f"{dungeon_name} has been run {total:,} times in tracked {season_name} Mythic+ so far, "
            f"with {timed_pct}% of those keys timed.",
        ]))

    timed_levels = [l['keystone_level'] for l in level_stats or []
                    if (l.get('upgrade_1') or 0) + (l.get('upgrade_2') or 0) + (l.get('upgrade_3') or 0) > 0]
    if timed_levels:
        top = max(timed_levels)
        p1.append(rng.choice([
            f"The highest key timed here is a +{top}.",
            f"Groups have timed it up to +{top}.",
        ]))

    for pull in lust_timeline or []:
        names = [npc_names.get(b) for b in pull_boss_ids(pull.get('top_npcs'), dungeon_bosses)]
        boss = commonUtils.join_names(names)
        if not boss or not pull.get('lust_count'):
            continue
        # Same numbers as the lust card row: lust_count / total_pulls_at_index.
        share = (f"{float(pull['lust_percentage']):.1f}% of the logged timed routes that pull "
                 f"it this way ({int(pull['lust_count']):,} of {int(pull['total_pulls_at_index']):,})")
        p2.append(rng.choice([
            f"The boss pull that gets Bloodlust most often is {boss}, lusted in {share}.",
            f"When groups save Bloodlust for a boss, it is most often {boss}, lusted in {share}.",
        ]))
        break

    fam = (team_comp_families or [None])[0]
    if fam and fam.get('runs'):
        comp = commonUtils.join_names(
            commonUtils.comp_spec_names(",".join(map(str, fam.get('c', [])))), cap=5)
        if comp:
            p2.append(rng.choice([
                f"The most played team comp is {comp}, with {fam['runs']:,} logged runs, "
                f"{fam['success']}% of them timed and a highest key of +{fam['mk']}.",
                f"{comp} is the most played team comp here at {fam['runs']:,} runs, "
                f"timing {fam['success']}% of them with a highest key of +{fam['mk']}.",
            ]))

    p2.append(DUNGEON_INTRO_CLOSING)
    return [" ".join(p) for p in (p1, p2) if p]

def main(template_path, output_dir, debug=False, target_dungeon=None, skip_previews=False):
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    spec_lookup = load_json(os.path.join(LOOKUP_DIR, "specs.json"))
    spell_lookup = load_json(os.path.join(LOOKUP_DIR, "spells.json"))
    class_lookup = load_json(os.path.join(LOOKUP_DIR, "classes.json"))
    season_info = load_season_info(LOOKUP_DIR)
    notifications = load_notifications(LOOKUP_DIR)
    # Latest per-dungeon hotfix notes, keyed by challenge_mode_id (str). Produced
    # by fetchDungeonHotfixes.py; source_url is the Blizzard hotfix post the notes
    # were scraped from (linked from the card header). Entries are filtered to the
    # last HOTFIX_MAX_AGE_DAYS below, and the template hides the card entirely for
    # any dungeon left with no recent hotfixes.
    hotfixes_data = load_json(os.path.join(LOOKUP_DIR, "hotfixes.json"))
    hotfix_cutoff_ms = (
        datetime.now(timezone.utc) - timedelta(days=HOTFIX_MAX_AGE_DAYS)
    ).timestamp() * 1000
    hotfixes_lookup = {
        dungeon_key: [e for e in entries if e["date_ts"] >= hotfix_cutoff_ms]
        for dungeon_key, entries in hotfixes_data.get("dungeons", {}).items()
    }
    hotfix_source_url = hotfixes_data.get("source_url")
    npcs_lookup = load_json(os.path.join(LOOKUP_DIR, "npcs.json"))
    # NPC model thumbnails downloaded by fetchNpcIcons.py -> data/icons/npc_<id>.png.
    # Set of npc_id strings that actually have an icon file, so the template only
    # renders <img> for npcs we have art for; the rest fall back to text.
    npc_icons = {
        os.path.basename(p)[len("npc_"):-len(".png")]
        for p in glob.glob(os.path.join("data", "icons", "npc_*.png"))
    }

    # npcs.json and the npc icons are refreshed only by the weekly static-data run,
    # which keys off the npc ids recorded in the DB's pulls. In the first week of a
    # season that run can fire before the collector has recorded a dungeon's routes,
    # leaving the ids the page references with no name (a hard crash) and no portrait
    # (a silent text fallback). Rather than wait for the next weekly run, self-heal on
    # demand: fetch the live Wowhead name dataset / MDT display map once and backfill.
    npcs_path = os.path.join(LOOKUP_DIR, "npcs.json")
    npc_name_cache = {"loaded": False, "data": {}}
    # MDT npc_id->displayId map + the persisted display-id record, both loaded lazily
    # on the first icon self-heal (the fetchNpcIcons pipeline is only imported then, so
    # the generator does not hard-depend on aiohttp/Pillow unless a heal is needed).
    npc_icon_cache = {"loaded": False, "display_map": {}, "prev": {}, "mod": None}

    def resolve_missing_npc_names(missing_ids):
        """Resolve npc ids absent from npcs.json against the live Wowhead dataset,
        persist them into npcs_lookup / npcs.json, and return the ids still unresolved."""
        if not missing_ids:
            return set()
        if not npc_name_cache["loaded"]:
            try:
                npc_name_cache["data"] = get_npc_names_retail()
            except Exception as e:
                print(f"[{datetime.now(timezone.utc).isoformat()}]  WARNING: could not fetch live NPC names to self-heal npcs.json: {e}")
                npc_name_cache["data"] = {}
            npc_name_cache["loaded"] = True

        resolved = set()
        changed = False
        for locale, id_map in npc_name_cache["data"].items():
            dest = npcs_lookup.setdefault(locale, {})
            for nid in missing_ids:
                if str(nid) in dest:
                    continue
                name = id_map.get(int(nid))
                if name is not None:
                    dest[str(nid)] = str(name)
                    changed = True
                    resolved.add(nid)
        if changed:
            with open(npcs_path, "w", encoding="utf-8") as f:
                json.dump(npcs_lookup, f, indent=2, ensure_ascii=False)
            print(f"[{datetime.now(timezone.utc).isoformat()}]  Self-healed npcs.json with {len(resolved)} newly-resolved npc name(s).")
        return set(missing_ids) - resolved

    def resolve_missing_npc_icons(missing_ids, icon_set):
        """Download portraits for referenced npc ids that have no icon yet, reusing the
        fetchNpcIcons pipeline (MDT displayId map -> Wowhead webthumb). Adds any id whose
        file now exists to icon_set (mutated in place) so the template renders it."""
        if not missing_ids:
            return
        if not npc_icon_cache["loaded"]:
            npc_icon_cache["loaded"] = True
            try:
                import fetchNpcIcons as _icons
                npc_icon_cache["mod"] = _icons
                npc_icon_cache["display_map"] = _icons.build_display_map(None)
                npc_icon_cache["prev"] = _icons.load_json(_icons.DISPLAY_IDS_PATH, {})
            except Exception as e:
                print(f"[{datetime.now(timezone.utc).isoformat()}]  WARNING: could not load MDT display map to self-heal npc icons: {e}")
                npc_icon_cache["mod"] = None

        icons = npc_icon_cache["mod"]
        if icons is None:
            return
        display_map = npc_icon_cache["display_map"]
        prev = npc_icon_cache["prev"]
        subset = {nid: display_map[nid] for nid in missing_ids if nid in display_map}
        if not subset:
            return
        try:
            asyncio.run(icons.download_images(subset, prev))
        except Exception as e:
            print(f"[{datetime.now(timezone.utc).isoformat()}]  WARNING: npc icon download failed during self-heal: {e}")
            return

        healed = 0
        for nid, display_id in subset.items():
            if os.path.exists(os.path.join("data", "icons", f"npc_{nid}.png")):
                icon_set.add(str(nid))
                prev[nid] = display_id
                healed += 1
        if healed:
            icons.save_display_ids(prev)
            print(f"[{datetime.now(timezone.utc).isoformat()}]  Self-healed {healed} newly-downloaded npc icon(s).")

    # Item metadata (from Raidbots) drives the "Best Loot" card: name/icon/ilvl/slot
    # plus the "sources" array that says which dungeon each item drops in.
    equippable_items = load_json(os.path.join(LOOKUP_DIR, "equippable-items.json"))
    item_lookup = {it["id"]: it for it in equippable_items}
    item_slug_map = build_item_slug_map(item_lookup)
    bonus_quality_lookup = load_json(os.path.join(LOOKUP_DIR, "bonus_quality_map.json"))

    # Reverse map: Blizzard journal instance id -> our dungeon key (challenge_mode_id).
    # journal_instance_id is written per dungeon by fetchDungeonData.py and equals the
    # instanceId Raidbots ships in each item's "sources". Without it a dungeon simply
    # has no loot to show (older data snapshots), so the card degrades to empty.
    instance_to_dungeon = {}
    for d_id, d_data in dungeon_lookup.items():
        jii = d_data.get("journal_instance_id")
        if jii is not None:
            instance_to_dungeon[int(jii)] = str(d_id)

    # dungeon key (str) -> set of item ids that drop there
    source_items_by_dungeon = defaultdict(set)
    for it in equippable_items:
        for src in it.get("sources", []) or []:
            d_id = instance_to_dungeon.get(src.get("instanceId"))
            if d_id:
                source_items_by_dungeon[d_id].add(it["id"])
    all_loot_item_ids = set().union(*source_items_by_dungeon.values()) if source_items_by_dungeon else set()

    spec_nav = generateSpecNav(spec_lookup, class_lookup)
    dungeon_nav = generateDungeonNav(dungeon_lookup)

    env = make_jinja_env(os.path.dirname(template_path))
    env.filters["humanize"] = commonUtils.humanize_number
    env.filters["duration"] = format_duration
    env.filters["format_ts"] = format_utc_timestamp
    env.filters["iso_ts"] = format_iso_timestamp
    env.filters["upgrade_info"] = upgrade_info
    template = env.get_template(os.path.basename(template_path))

    os.makedirs(output_dir, exist_ok=True)

    conn = databaseConnector.get_connection()
    thumbnail_executor = ThreadPoolExecutor(max_workers=8)
    try:
        current_season = season_info.get('blizzard_season_id', None)
        if not current_season:
            raise ValueError("Current season ID not found in seasonInfo.json")

        with conn.cursor(dictionary=True) as cursor:
            databaseConnector.configure_read_session(conn, cursor)

            # Same ids the lust queries filter on, so the "More Details" heatmap
            # link shows exactly the spells the Most Lusted Pulls table counted.
            bloodlust_spell_ids = databaseConnector.fetch_bloodlust_spell_ids(conn, cursor)
            if not bloodlust_spell_ids:
                raise RuntimeError(
                    "bloodlust_spells is empty — the lust timeline and the heatmap link both depend on it."
                )
            bloodlust_icon = commonUtils.bloodlust_icon(spell_lookup, bloodlust_spell_ids)
            if not bloodlust_icon:
                raise RuntimeError("No Bloodlust icon in spells.json for the Boss Pacing card.")

            print(f"[{datetime.now(timezone.utc).isoformat()}] Pre-fetching global dungeon success rates...")
            all_dungeon_runs = databaseConnector.fetch_runs_per_dungeon(conn, cursor, current_season)
            dungeon_runs_lookup = {str(d['dungeon_id']): d for d in all_dungeon_runs}
            
            all_dungeon_runs_per_level = databaseConnector.fetch_runs_per_dungeon_per_level(conn, cursor, current_season)
            dungeon_runs_per_level_lookup = {}
            for d in all_dungeon_runs_per_level:
                d_id = str(d['dungeon_id'])
                if d_id not in dungeon_runs_per_level_lookup:
                    dungeon_runs_per_level_lookup[d_id] = []
                dungeon_runs_per_level_lookup[d_id].append(d)

            # Fetch every dungeon's top routes first and kick off its
            # keystone.guru thumbnail job in a background thread (pure HTTP),
            # so the remote render's queue wait overlaps the per-dungeon DB
            # work. CI passes --skip-previews and renders the previews in
            # renderDungeonPreviews.py instead, where that wait blocks nothing.
            top_routes_by_dungeon = {}
            thumbnail_futures = {}
            # POV videos per route (all routes), to flag/link VODs on the top-routes card.
            route_videos_map = commonUtils.fetch_route_videos(conn, cursor)
            for dungeon_id, dungeon_data in dungeon_lookup.items():
                if target_dungeon and str(dungeon_id) != str(target_dungeon):
                    continue
                print(f"[{datetime.now(timezone.utc).isoformat()}] Fetching top routes for {dungeon_data['name']['en_US']} ({dungeon_id})")
                top_routes = databaseConnector.fetch_dungeon_top_routes(conn, cursor, dungeon_id)
                _upgrades = dungeon_data.get("keystone_upgrades") or {}
                for _r in top_routes:
                    _r["videos"] = route_videos_map.get(_r.get("route_key"), [])
                    _up = commonUtils.upgrade_info(
                        _r.get("duration"), _upgrades, _r.get("keystone_level")
                    )
                    _r["upgrade_css"] = _up["css"]
                    _r["upgrade_text"] = _up["text"]
                top_routes_by_dungeon[dungeon_id] = top_routes
                if not skip_previews and top_routes and top_routes[0].get('route_key'):
                    print(f"[{datetime.now(timezone.utc).isoformat()}] Requesting thumbnail for top route: {top_routes[0]['route_key']}")
                    thumbnail_futures[dungeon_id] = thumbnail_executor.submit(
                        fetch_route_thumbnail, dungeon_id, top_routes[0]['route_key']
                    )

            # Team-comp families per dungeon (same clustering as the comps page), so each
            # dungeon's popular comps are grouped with their flexible alternates. One scan
            # + one clustering pass, indexed by dungeon.
            print(f"[{datetime.now(timezone.utc).isoformat()}] Clustering team comps for dungeon pages...")
            team_families_by_dungeon = compArchetypes.cached_dungeon_archetypes(
                lambda: databaseConnector.fetch_all_comps(conn, cursor, current_season),
                current_season, spec_lookup, class_lookup,
                [str(k) for k in dungeon_lookup.keys()], top_n=6)

            # Global per-item usage across the meta, so each dungeon's loot can be
            # ranked by how much the current playerbase actually equips each drop.
            # Reuses the per-spec indexed query the item pages use (fast path);
            # summed across specs = total equipping runs, and the spec with the most
            # runs on an item is the "most used by" credit shown on the card.
            print(f"[{datetime.now(timezone.utc).isoformat()}] Pre-fetching item usage for dungeon loot ranking...")
            item_total_runs = defaultdict(int)
            item_top_spec = {}  # item_id -> (spec_id str, runs)
            item_bonus_runs = defaultdict(lambda: defaultdict(int))
            for spec_id in spec_lookup.keys():
                try:
                    spec_id_int = int(spec_id)
                except (TypeError, ValueError):
                    continue
                # the spec's two reads below in one round trip
                databaseConnector.prefetch(conn, cursor, [
                    (databaseConnector.fetch_item_spec_usage, (current_season, spec_id_int)),
                    (databaseConnector.fetch_item_bonus_usage, (current_season, spec_id_int)),
                ])
                rows = databaseConnector.fetch_item_spec_usage(conn, cursor, current_season, spec_id_int)
                for row in rows or []:
                    # item_id is VARCHAR in global_aggregated_items, so normalise to
                    # int to match the equippable-items.json ids the loot join uses.
                    raw_iid = row['item_id']
                    if not str(raw_iid).isdigit():
                        continue
                    iid = int(raw_iid)
                    runs = row['run_count'] or 0
                    if runs <= 0:
                        continue
                    item_total_runs[iid] += runs
                    prev = item_top_spec.get(iid)
                    if prev is None or runs > prev[1]:
                        item_top_spec[iid] = (str(spec_id), runs)
                for row in databaseConnector.fetch_item_bonus_usage(conn, cursor, current_season, spec_id_int) or []:
                    raw_iid = row['item_id']
                    if not str(raw_iid).isdigit():
                        continue
                    iid = int(raw_iid)
                    if iid not in all_loot_item_ids:
                        continue
                    runs = row['run_count'] or 0
                    if runs <= 0:
                        continue
                    item_bonus_runs[iid][row['bonus_list']] += runs

            # Most-used variant per loot item, so its bonus ids drive the rarity colour.
            item_top_bonus = {
                iid: max(combos.items(), key=lambda kv: kv[1])[0]
                for iid, combos in item_bonus_runs.items() if combos
            }

            for dungeon_id, dungeon_data in dungeon_lookup.items():
                print(f"[{datetime.now(timezone.utc).isoformat()}] Processing dungeon: {dungeon_data['name']['en_US']} ({dungeon_id})")
                if target_dungeon and str(dungeon_id) != str(target_dungeon):
                    continue

                print(f"[{datetime.now(timezone.utc).isoformat()}]Generating dungeon page for {dungeon_data['name']['en_US']} ({dungeon_id})")

                # Overall run totals for this dungeon, consumed by the social overview
                # image (createDungeonOverviewImg dungeon_totals=...).
                if not skip_previews:
                    local_total_res = databaseConnector.fetch_dungeon_totals(conn, cursor, dungeon_id, current_season)

                # Best loot: the items that drop in this dungeon, ranked by how much
                # the current meta actually equips them. Drop source comes from the
                # Raidbots "sources" field, joined to this dungeon via journal_instance_id;
                # usage comes from the global per-item sweep above.
                loot = []
                for iid in source_items_by_dungeon.get(str(dungeon_id), ()):
                    runs = item_total_runs.get(iid, 0)
                    if runs <= 0:
                        continue
                    item = item_lookup.get(iid)
                    if not item:
                        continue
                    slot_label, _slot_key = slot_for_item(item)
                    top_spec_id, _top_runs = item_top_spec.get(iid, (None, 0))
                    top_spec = spec_lookup.get(top_spec_id) if top_spec_id else None
                    top_class = class_lookup.get(str(top_spec.get('classID', '')), {}) if top_spec else {}
                    loot.append({
                        'id': iid,
                        'name': item.get('name', 'Unknown'),
                        'icon': item.get('icon', ''),
                        'quality': item.get('quality'),
                        'quality_override': commonUtils.resolve_bonus_quality(
                            item_top_bonus.get(iid), bonus_quality_lookup),
                        'ilvl': item.get('itemLevel'),
                        'slot': slot_label,
                        'slug': item_slug_map.get(iid),
                        'runs': runs,
                        'top_spec_name': top_spec.get('name') if top_spec else None,
                        'top_class_name': top_class.get('name') if top_spec else None,
                        'top_spec_role': str(top_spec.get('role', 2)) if top_spec else None,
                        'top_spec_icon': top_spec.get('SpellIconFileId', '') if top_spec else None,
                    })

                loot.sort(key=lambda x: x['runs'], reverse=True)
                top_loot = loot[:8]

                # Clustered team-comp families for this dungeon (popular ranking).
                team_comp_families = team_families_by_dungeon.get(
                    str(dungeon_id), {}).get('popular', [])

                # Top routes were fetched in the thumbnail pre-pass above
                top_routes = top_routes_by_dungeon.get(dungeon_id, [])

                closest_call_run = parse_run_rows(databaseConnector.fetch_dungeon_closest_call_run(conn, cursor, dungeon_id, current_season))
                shortest_run = parse_run_rows(databaseConnector.fetch_dungeon_shortest_run(conn, cursor, dungeon_id, current_season))
                longest_run = parse_run_rows(databaseConnector.fetch_dungeon_longest_run(conn, cursor, dungeon_id, current_season))
                highest_run = parse_run_rows(databaseConnector.fetch_dungeon_max_key_run(conn, cursor, dungeon_id, current_season))
                fastest_top_run = parse_run_rows(databaseConnector.fetch_dungeon_fastest_top_levels_run(conn, cursor, dungeon_id, current_season))

                lust_timeline = databaseConnector.fetch_dungeon_lust_timeline(conn, cursor, dungeon_id)
                skip_rates = databaseConnector.fetch_dungeon_skip_rates(conn, cursor, dungeon_id, current_season)
                dungeon_bosses = set(dungeon_data['boss_npc_ids'])
                boss_pacing = build_boss_pacing(
                    databaseConnector.fetch_dungeon_route_encounters(conn, cursor, dungeon_id),
                    databaseConnector.fetch_dungeon_route_deaths(conn, cursor, dungeon_id),
                    databaseConnector.fetch_dungeon_route_pull_lust(conn, cursor, dungeon_id),
                    dungeon_data['bosses'],
                    dungeon_data["keystone_upgrades"]["1"]["qualifying_duration"])

                # one batched round trip each instead of one query per skip/pull
                skip_examples = databaseConnector.fetch_example_skip_routes(
                    conn, cursor, dungeon_id, [skip['npc_id'] for skip in skip_rates[:15]]
                )
                for skip in skip_rates[:15]:
                    example_route = skip_examples.get(skip['npc_id'])
                    if example_route:
                        example_route['videos'] = route_videos_map.get(example_route['route_key'], [])
                        skip['example_route'] = example_route

                lust_examples = databaseConnector.fetch_example_lust_routes(
                    conn, cursor, dungeon_id,
                    [pull['top_npcs'] for pull in lust_timeline if pull.get('top_npcs')],
                )
                for pull in lust_timeline:
                    top_npcs_str = pull.get('top_npcs', '')
                    if top_npcs_str:
                        example_lust_route = lust_examples.get(top_npcs_str)
                        if example_lust_route:
                            example_lust_route['videos'] = route_videos_map.get(
                                example_lust_route['route_key'], [])
                            pull['example_route'] = example_lust_route

                # Validate lust_timeline contains at least one boss pull
                has_boss_lust = any(pull_boss_ids(pull.get('top_npcs'), dungeon_bosses)
                                    for pull in lust_timeline)

                # Only throw a validation error if there is actually lust data available
                if lust_timeline and len(lust_timeline) > 0 and not has_boss_lust:
                    raise RuntimeError(f"Dungeon {dungeon_data['name']['en_US']} ({dungeon_id}) has no lust pull marked as a boss. This indicates missing boss NPC data in dungeons.json (fetchDungeonData.py).")

                # Every NPC the page shows (the "Most Lusted Pulls" compositions and the
                # "Least Played NPCs" skip table) needs a name via npcs.json (else the template
                # renders the raw id / "Unknown NPC") and, ideally, a portrait icon. A miss
                # usually means npcs.json / the icon set is stale relative to the collected
                # pull_enemies ids (the week-1-of-season race, see resolve_missing_* above), so
                # self-heal both on demand instead of shipping a broken page or waiting a week.
                npc_names = npcs_lookup.get('en_US', {})
                referenced_npc_ids = set()
                for pull in lust_timeline:
                    top_npcs_str = pull.get('top_npcs', '')
                    if top_npcs_str:
                        for n in str(top_npcs_str).split(','):
                            n = n.split(':')[0].strip()
                            if n:
                                referenced_npc_ids.add(n)
                for skip in skip_rates:
                    n = str(skip.get('npc_id', '')).strip()
                    if n:
                        referenced_npc_ids.add(n)

                missing_name_ids = {n for n in referenced_npc_ids if n not in npc_names}
                if missing_name_ids:
                    still_missing = resolve_missing_npc_names(missing_name_ids)
                    if still_missing:
                        # On-demand self-heal already ran against the live Wowhead
                        # npc-names dataset and these ids are still unknown, so this is a
                        # genuine data gap (not the week-1 ordering race): the ids exist in
                        # collected pulls but neither npcs.json nor the live dataset knows
                        # them. Fail loudly rather than render bare numeric ids.
                        raise ValueError(
                            f"dungeon '{dungeon_data['name']['en_US']}' ({dungeon_id}) "
                            f"references NPC id(s) with no name in npcs.json or the live "
                            f"Wowhead npc-names dataset even after on-demand self-heal was "
                            f"attempted: {sorted(int(n) for n in still_missing)}. These ids "
                            f"come from collected pulls but are unknown to Wowhead, so this "
                            f"is a genuine data gap, not the week-1 ordering race "
                            f"(re-running fetchNpcInfo.py will not fix it)."
                        )

                missing_icon_ids = {n for n in referenced_npc_ids if n not in npc_icons}
                if missing_icon_ids:
                    resolve_missing_npc_icons(missing_icon_ids, npc_icons)

                # Fetch Overall Stats
                d_id_str = str(dungeon_id)
                overall_stats = dungeon_runs_lookup.get(d_id_str, {})
                level_stats = dungeon_runs_per_level_lookup.get(d_id_str, [])

                # Cards the user can toggle between inside a single card
                toggle_runs = [
                    {"name": "closest-call", "label": "Closest Call", "tab": "Closest", "data": closest_call_run, "icon": "timer", "show_margin": True},
                    {"name": "shortest", "label": "Shortest Run", "tab": "Shortest", "data": shortest_run, "icon": "sprint"},
                    {"name": "longest", "label": "Longest Run", "tab": "Longest", "data": longest_run, "icon": "hourglass_bottom"},
                ]
                # Stand-alone cards
                single_runs = [
                    {"name": "highest", "label": "Highest Run", "data": highest_run, "icon": "leaderboard"},
                    {"name": "fastest-top", "label": "Fastest (Top 3 Keys)", "data": fastest_top_run, "icon": "bolt",
                     "subtitle": "Fastest clear among the 3 highest key levels"},
                ]
                
                trends = build_trends(
                    conn,
                    cursor,
                    trend_feeds_for_dungeon(dungeon_id),
                    # specs -> popular-comp cluster, npcs -> lusted-pull portraits
                    # (en_US name map, portraits at /data/icons/npc_<id>.png),
                    # items -> best-loot icons + /items/<slug> links.
                    {"specs": spec_lookup, "npcs": npc_names, "items": item_lookup},
                )

                intro_paragraphs = build_dungeon_intro(
                    dungeon_id, dungeon_data['name']['en_US'], season_info.get('name', ''),
                    overall_stats, level_stats, lust_timeline, dungeon_bosses, npc_names,
                    team_comp_families)

                output_html = template.render(dungeon=dungeon_data,
                    intro_paragraphs=intro_paragraphs,
                    toggle_runs=toggle_runs,
                    trends=trends,
                    single_runs=single_runs,
                    lust_timeline=lust_timeline,
                    bloodlust_spell_ids=bloodlust_spell_ids,
                    skip_rates=skip_rates,
                    boss_pacing=boss_pacing,
                    lust_min_pct=LUST_ICON_MIN_PCT,
                    bloodlust_icon=bloodlust_icon,
                    npcs=npcs_lookup,
                    npc_icons=npc_icons,
                    bosses=dungeon_bosses,
                    top_routes=top_routes,
                    team_comp_families=team_comp_families,
                    top_loot=top_loot,
                    overall_stats=overall_stats,
                    level_stats=level_stats,
                    generated_at=datetime.now(timezone.utc).timestamp(),
                    specs=spec_lookup,
                    spec_nav=spec_nav,
                    role_lookup=ROLE_FOLDERS,
                    dungeon_nav=dungeon_nav,
                    current_dungeon=dungeon_data['name']['en_US'],
                    hotfixes=hotfixes_lookup.get(str(dungeon_id), []),
                    hotfix_source_url=hotfix_source_url,
                    dungeon_id=dungeon_id,
                    page_title=dungeon_data['name']['en_US'],
                    season_info=season_info,
                    notifications=notifications,
                    breadcrumbs=[
                        {"title": "Pages", "href": "/pages"},
                        {"title": "Dungeons", "href": "/dungeons"},
                    ],)
                
                
                slug = dungeon_data['slug']
                out_path = os.path.join(output_dir, f"{slug}.html")
                with open(out_path, "w", encoding="utf-8") as outf:
                    outf.write(output_html)
                    
                # Create Preview Image
                if not skip_previews:
                    preview_dir = os.path.join("assets", "img", "previews")
                    os.makedirs(preview_dir, exist_ok=True)
                    preview_path = os.path.join(preview_dir, f"{slug}.png")
                    try:
                        # resolve the background thumbnail job started in the
                        # pre-pass (None = no top route / job failed → no map)
                        thumb_future = thumbnail_futures.get(dungeon_id)
                        route_thumbnail = thumb_future.result() if thumb_future else None
                        # pass the already-fetched data so the image step doesn't
                        # re-run the same queries (incl. the season-wide per-level
                        # rollup, previously re-scanned once per dungeon)
                        createDungeonOverviewImg(
                            tmpdir=os.path.join("tmp", "img"),
                            out_path=preview_path,
                            dungeon_id=dungeon_id,
                            season=current_season,
                            conn=conn,
                            cursor=cursor,
                            dungeon_totals=local_total_res,
                            per_level=level_stats,
                            top_routes_data=top_routes,
                            route_thumbnail=route_thumbnail,
                        )
                    except Exception as e:
                        print(f"[{datetime.now(timezone.utc).isoformat()}]Failed to generate preview for {slug}: {e}")

                if debug:
                    break
    finally:
        thumbnail_executor.shutdown(wait=False)
        databaseConnector.close_quietly(conn)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate WoW M+ dungeon pages")
    parser.add_argument("--template", required=True, help="Path to HTML template file")
    parser.add_argument("--output_dir", required=True, help="Directory to write generated HTML pages")
    parser.add_argument("--debug", required=False, action="store_true")
    parser.add_argument("--dungeon", required=False)
    parser.add_argument("--skip-previews", action="store_true",
                        help="Do not render the preview images (CI renders them in renderDungeonPreviews.py)")

    args = parser.parse_args()

    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST", "127.0.0.1"),
        os.environ.get("DATABASE_USER", "root"),
        os.environ.get("DATABASE_PASSWORD", ""),
        os.environ.get("DATABASE_NAME", "Mythistone"),
        os.environ.get("DATABASE_PORT", "3306"),
        1,
    )
    main(args.template, args.output_dir, args.debug, args.dungeon, args.skip_previews)
