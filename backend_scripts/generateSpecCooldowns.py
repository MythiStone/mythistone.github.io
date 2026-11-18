"""Cooldown Usage modal of the spec pages: when a spec presses each cooldown in every dungeon.

generateSpecPages.py calls this next to spec_meta. Each spec gets one file fetched when the modal
opens, assets/json/spec_cooldowns/<spec_id>.json, built from the aggregated Warcraft Logs tables.
Findings describe observed timing and never claim why a spell was pressed.
"""
import glob
import json
import math
import os
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone

import databaseConnector
from commonUtils import LOOKUP_DIR, load_json
from pageGeneration import (
    wcl_boss_encounters,
    wcl_clock,
    wcl_cooldown_category,
    wcl_example_url,
    wcl_pull_npcs,
    wcl_spell_view,
)
from wclPullBuilder import INTERRUPT_NAMES

OUTPUT_DIR = os.path.join("assets", "json", "spec_cooldowns")

SPEC_FAMILY_MIN_PLAYER_PULLS = 30
SPEC_SPELL_MIN_CASTS = 15
USAGE_MIN_PLAYERS = 8
FREQUENT_COOLDOWN_S = 45

LINED_UP_MIN_SHARE = 0.35
LINED_UP_MIN_SAMPLES = 8
LINED_UP_MIN_LIFT = 1.25
LINED_UP_WITHIN_S = 1
ON_COOLDOWN_MIN_USAGE = 0.8
SAVED_MAX_USAGE = 0.5

TRASH_MAX_ROWS = 5
TARGETED_MIN_SHARE = 0.5
TARGET_MIN_SAMPLES = 8
TARGET_MOSTLY_SHARE = 0.5
NEAR_CATEGORIES = {"defensive", "utility", "healing"}
NEAR_MIN_SHARE = 0.25
NEAR_MIN_SAMPLES = 8
NEAR_MAX_SPELLS = 2
# Only summed offsets are stored: about three quarters of presses fall within 1.5 times the mean distance.
WINDOW_FROM_MEAN = 1.5
RELATION_MAX_S = 10


def load_lookups():
    """The static files every spec's cooldown data reads."""
    return {
        "cooldowns": load_json(os.path.join(LOOKUP_DIR, "player_cooldowns.json")),
        "categories": load_json(os.path.join(LOOKUP_DIR, "player_cooldown_categories.json")),
        "dungeon_spells": load_json(os.path.join(LOOKUP_DIR, "dungeon_spells.json")),
        "npc_names": load_json(os.path.join(LOOKUP_DIR, "npcs.json")).get("en_US", {}),
        "npc_icons": {os.path.basename(p)[len("npc_"):-len(".png")]
                      for p in glob.glob(os.path.join("data", "icons", "npc_*.png"))},
        "unlisted": set(),
        "unknown_spells": set(),
    }


def build_dungeon_contexts(dungeon_lookup, lookups):
    """Per dungeon data shared by all specs, read once per build: pull compositions and boss names."""
    contexts = {}
    with closing(databaseConnector.get_connection()) as conn:
        with conn.cursor(dictionary=True) as cursor:
            databaseConnector.configure_read_session(conn, cursor)
            for dungeon_id, dungeon in dungeon_lookup.items():
                key = str(dungeon_id)
                pull_rows = databaseConnector.fetch_wcl_dungeon_pulls(conn, cursor, key)
                signatures = {}
                for r in pull_rows:
                    signatures.setdefault(r['family_key'], r['pull_key'])
                encounters = wcl_boss_encounters(pull_rows, dungeon['bosses'])
                boss_names = {f"b:{found['encounter']}": dungeon['bosses'][idx]['name']
                              for idx, found in sorted(encounters.items())}
                contexts[key] = {"name": dungeon['name']['en_US'], "signatures": signatures,
                                 "boss_names": boss_names}
    return contexts


def trash_npcs(family, context, lookups, npcs_used):
    """[[npc id, count]] of a trash pull family, None when an npc has no name to show."""
    signature = context['signatures'].get(family)
    npcs = wcl_pull_npcs(signature) if signature else [(n, 1) for n in family.split(',')]
    if not npcs or any(n not in lookups['npc_names'] for n, _count in npcs):
        return None
    for n, _count in npcs:
        npcs_used.add(n)
    return [[n, count] for n, count in npcs]


def press_window(stats):
    """Whole seconds around the enemy cast that most presses in {n, offset, abs} fall within."""
    return min(max(1, math.ceil(stats['abs'] / stats['n'] * WINDOW_FROM_MEAN)), RELATION_MAX_S)


def lined_up_text(stats):
    """The words before the enemy spell's name, from the summed offsets of the presses."""
    offset = stats['offset'] / stats['n']
    if abs(offset) <= LINED_UP_WITHIN_S:
        return f"Usually pressed within {press_window(stats)}s of"
    seconds = round(abs(offset))
    return f"Usually pressed {seconds}s before" if offset < 0 else f"Usually pressed about {seconds}s after"


def lined_up_spell(relations, boss_totals, casts, lookups):
    """(enemy spell id, {n, offset, abs}) of the enemy spell this cooldown lines up with on a boss, or None.
    Lift compares its share of this cooldown's relation rows with its share of the whole boss's."""
    spell_total = sum(stats['n'] for stats in relations.values())
    boss_total = sum(boss_totals.values())
    best = None
    for pair, stats in relations.items():
        n = stats['n']
        if n < LINED_UP_MIN_SAMPLES or n / casts < LINED_UP_MIN_SHARE or (best and n <= best[0]):
            continue
        if (n / spell_total) / (boss_totals[pair] / boss_total) < LINED_UP_MIN_LIFT:
            continue
        if wcl_spell_view(pair[0], lookups['dungeon_spells'], set()):
            best = (n, pair[0], stats)
    return (best[1], best[2]) if best else None


def boss_finding(usage, relations, boss_totals, lookups, spells_used):
    """The one finding a boss row shows: lined up with an ability, on cooldown, saved, or plain usage."""
    casts, players = usage['casts'], usage['players']
    lined_up = lined_up_spell(relations, boss_totals, casts, lookups)
    if lined_up:
        spells_used.add(lined_up[0])
        return {"k": "lined_up", "t": lined_up_text(lined_up[1]), "s": str(lined_up[0])}
    share = casts / usage['possible'] if usage['possible'] else 0
    first_use = wcl_clock(usage['first_use_s'] / players)
    if share >= ON_COOLDOWN_MIN_USAGE:
        return {"k": "on_cooldown", "t": f"Used on cooldown, {min(100, round(share * 100))}% of possible casts"}
    if share < SAVED_MAX_USAGE:
        return {"k": "saved", "t": f"Saved, first used around {first_use}"}
    times = round(casts / players)
    amount = "once" if times <= 1 else f"{times} times"
    return {"k": "usage", "t": f"Used about {amount} per fight, first around {first_use}"}


def most_common_target(targets, casts, lookups, npcs_used):
    """[npc id, percent, label] of the enemy a targeted spell is cast on most, None for an untargeted one."""
    total = sum(targets.values())
    if total < TARGET_MIN_SAMPLES or total / casts < TARGETED_MIN_SHARE:
        return None
    for npc, n in targets.most_common():
        if str(npc) in lookups['npc_names']:
            if n < TARGET_MIN_SAMPLES:
                return None
            npcs_used.add(str(npc))
            label = "Mostly on" if n / total >= TARGET_MOSTLY_SHARE else "Often on"
            return [str(npc), round(n / total * 100), label]
    return None


def nearby_enemy_spells(relations, casts, lookups, spells_used):
    """[[enemy spell id, seconds]] the cooldown is most often pressed close to on a trash pull."""
    per_spell = defaultdict(Counter)
    for (enemy_spell, _npc), stats in relations.items():
        per_spell[enemy_spell].update(stats)
    near = []
    ranked = sorted(per_spell.items(), key=lambda item: (-item[1]['n'], item[0]))
    for enemy_spell, stats in ranked:
        n = stats['n']
        if n < NEAR_MIN_SAMPLES or n / casts < NEAR_MIN_SHARE:
            continue
        if wcl_spell_view(enemy_spell, lookups['dungeon_spells'], set()):
            spells_used.add(enemy_spell)
            near.append([str(enemy_spell), press_window(stats)])
    return near[:NEAR_MAX_SPELLS]


def cooldown_view(spell_id, spec_id, lookups):
    """How a logged player spell shows in the modal, None for one it must not list."""
    cooldown = lookups['cooldowns'].get(str(spell_id))
    if not cooldown:
        lookups['unknown_spells'].add(spell_id)
        return None
    if cooldown['name'] in INTERRUPT_NAMES:
        return None
    category = wcl_cooldown_category(cooldown['name'], spec_id, lookups['categories'])
    if category is None:
        lookups['unlisted'].add(cooldown['name'])
    return {"id": str(spell_id), "name": cooldown['name'], "icon": cooldown.get('icon'),
            "cat": category or 'other', "cd": cooldown.get('cooldown_s'),
            "freq": (cooldown.get('cooldown_s') or 0) < FREQUENT_COOLDOWN_S}


def build_dungeon(spec_id, context, rows, lookups, spells_used, npcs_used):
    """The spells of one spec in one dungeon that have at least one row to show."""
    player_pulls = {r['family_key']: int(r['player_pulls']) for r in rows['pulls']}
    # Cast rates pair the cooldown and spec pull tables. Relations, usage and targets are newer and
    # only compare with each other, so a spell's older casts never dilute their shares.
    casts = defaultdict(dict)
    for r in rows['cooldowns']:
        casts[r['spell_id']][r['family_key']] = int(r['casts'])
    usage = defaultdict(dict)
    for r in rows['usage']:
        usage[r['spell_id']][r['family_key']] = {
            "players": int(r['players_casting']), "casts": int(r['casts_sum']),
            "possible": int(r['possible_sum']), "first_use_s": int(r['first_use_s_sum'])}
    relations = defaultdict(lambda: defaultdict(Counter))
    family_totals = defaultdict(Counter)
    for r in rows['relations']:
        if not r['enemy_spell_id']:
            continue
        pair = (r['enemy_spell_id'], r['enemy_npc_id'])
        relations[(r['family_key'], r['spell_id'])][pair].update(
            n=int(r['n']), offset=int(r['offset_s_sum']), abs=int(r['abs_offset_s_sum']))
        family_totals[r['family_key']][pair] += int(r['n'])
    targets = defaultdict(Counter)
    for r in rows['targets']:
        targets[(r['family_key'], r['spell_id'])][r['target_npc_id']] += int(r['n'])
    examples = {}
    for r in rows['examples']:
        key = (r['family_key'], r['spell_id'])
        if key not in examples or r['keystone_level'] > examples[key]['keystone_level']:
            examples[key] = r

    def example_url(family, spell_id):
        example = examples.get((family, spell_id))
        return example and wcl_example_url(family, example)

    boss_order = list(context['boss_names'])
    abilities = []
    for spell_id, by_family in casts.items():
        view = cooldown_view(spell_id, spec_id, lookups)
        if not view:
            continue
        bosses, trash = [], []
        for family, n in by_family.items():
            family_usage = usage[spell_id].get(family)
            if (player_pulls.get(family, 0) < SPEC_FAMILY_MIN_PLAYER_PULLS or n < SPEC_SPELL_MIN_CASTS
                    or not family_usage or family_usage['casts'] < SPEC_SPELL_MIN_CASTS
                    or family_usage['players'] < USAGE_MIN_PLAYERS):
                continue
            spell_relations = relations.get((family, spell_id), {})
            if family.startswith('b:'):
                if family in context['boss_names']:
                    finding = boss_finding(family_usage, spell_relations, family_totals[family], lookups, spells_used)
                    bosses.append(dict(finding, boss=context['boss_names'][family], family=family,
                                       log=example_url(family, spell_id)))
                continue
            npcs = trash_npcs(family, context, lookups, npcs_used)
            if not npcs:
                continue
            row = {"npcs": npcs, "rate": round(n / player_pulls[family], 2), "casts": n,
                   "log": example_url(family, spell_id)}
            target = most_common_target(targets.get((family, spell_id), Counter()), family_usage['casts'],
                                        lookups, npcs_used)
            if target:
                row['target'] = target
            if view['cat'] in NEAR_CATEGORIES:
                near = nearby_enemy_spells(spell_relations, family_usage['casts'], lookups, spells_used)
                if near:
                    row['near'] = near
            trash.append(row)
        if bosses or trash:
            bosses.sort(key=lambda b: boss_order.index(b.pop('family')))
            trash.sort(key=lambda t: t['casts'], reverse=True)
            for row in trash:
                del row['casts']
            abilities.append(dict(view, boss=bosses, trash=trash[:TRASH_MAX_ROWS],
                                  casts=sum(by_family.values())))
    abilities.sort(key=lambda a: a['casts'], reverse=True)
    for ability in abilities:
        del ability['casts']
    return abilities


def write_spec_cooldowns(spec_id, contexts, lookups):
    """Writes the spec's JSON and returns its dungeons, or None when no dungeon has a row to show."""
    fetchers = {"cooldowns": databaseConnector.fetch_wcl_spec_cooldowns, "pulls": databaseConnector.fetch_wcl_spec_pulls,
                "relations": databaseConnector.fetch_wcl_spec_relations, "usage": databaseConnector.fetch_wcl_spec_usage,
                "targets": databaseConnector.fetch_wcl_spec_targets, "examples": databaseConnector.fetch_wcl_spec_examples}
    with closing(databaseConnector.get_connection()) as conn:
        with conn.cursor(dictionary=True) as cursor:
            databaseConnector.configure_read_session(conn, cursor)
            databaseConnector.prefetch(conn, cursor, [(fn, (int(spec_id),)) for fn in fetchers.values()])
            fetched = {name: fn(conn, cursor, int(spec_id)) for name, fn in fetchers.items()}

    by_dungeon = defaultdict(lambda: defaultdict(list))
    for name, rows in fetched.items():
        for r in rows:
            by_dungeon[str(r['dungeon_id'])][name].append(r)
    spells_used, npcs_used = set(), set()
    dungeons = {}
    for key, context in contexts.items():
        abilities = build_dungeon(spec_id, context, by_dungeon[key], lookups, spells_used, npcs_used)
        if abilities:
            dungeons[key] = abilities

    path = os.path.join(OUTPUT_DIR, f"{spec_id}.json")
    if not dungeons:
        if os.path.exists(path):
            os.remove(path)
        return None
    spells = {str(s): [view['name'], view['icon']] for s in spells_used
              for view in [wcl_spell_view(s, lookups['dungeon_spells'], set())]}
    npcs = {n: [lookups['npc_names'][n], int(n in lookups['npc_icons'])] for n in npcs_used}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"dungeons": dungeons, "spells": spells, "npcs": npcs}, f, separators=(",", ":"))
    return sorted(({"id": key, "name": contexts[key]['name']} for key in dungeons), key=lambda d: d['name'])


def report_cooldown_gaps(lookups):
    """Build log of spells waiting on a reviewed categories or cooldowns update. Never fails a build."""
    stamp = datetime.now(timezone.utc).isoformat()
    if lookups['unlisted']:
        print(f"[{stamp}] Cooldowns shown under Other, not in player_cooldown_categories.json: "
              f"{sorted(lookups['unlisted'])}")
    if lookups['unknown_spells']:
        print(f"[{stamp}] Logged spell ids skipped, not in player_cooldowns.json: {sorted(lookups['unknown_spells'])}")
