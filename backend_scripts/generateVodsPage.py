import os
import sys
import json
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pageGeneration import (
    load_notifications,
    generateSpecNav, make_jinja_env,
    generateDungeonNav,
    build_global_trends,
    rank_run_entries,
)
from generateSpecPages import (
    humanize_number,
    format_duration,
    format_utc_timestamp,
    upgrade_info,
    load_json,
    load_season_info,
    LOOKUP_DIR,
)

import databaseConnector
from commonUtils import (
    MIN_STREAMER_VODS,
    build_vod_embed_src,
    decode_loadout,
    filter_talent_tree_nodes,
    load_score_tiers,
    load_streamers,
    resolve_bonus_quality,
    score_color,
)


def fail(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(2)


def key_label(run):
    """Site-wide keystone notation: '++20' for two upgrades, '-20' when depleted."""
    upgrades = run.get("upgrades") or 0
    text = ("+" * upgrades if upgrades else "-") + str(run.get("level"))
    return text, "text-success" if upgrades else "text-danger"


# (max rank, item quality): a rank is coloured like an item of that rarity, so a
# top-3 rank reads as artifact and anything past 100k as common.
RANK_QUALITY_TIERS = [(3, 6), (10, 5), (100, 4), (10000, 3), (100000, 2)]


def rank_quality(rank):
    for limit, quality in RANK_QUALITY_TIERS:
        if rank <= limit:
            return quality
    return 1


QUESTION_ICON = "inv_misc_questionmark"
# Armory layout of the baked gear grid (loadout-view.css .gm-*): armour left/right,
# then weapons beside trinkets. Mirrors the spec page's Gear Overview.
GEAR_BLOCKS = [
    ((None, ["HEAD", "NECK", "SHOULDER", "BACK", "CHEST", "WRIST"]),
     (None, ["HANDS", "WAIST", "LEGS", "FEET", "FINGER_1", "FINGER_2"])),
    (("Weapon", ["MAIN_HAND", "OFF_HAND"]), ("Trinkets", ["TRINKET_1", "TRINKET_2"])),
]
TREE_PADDING = 150  # talent-tree coordinate units kept around each positioned column


def load_item_pages():
    """item id -> /items slug for every item that has an item page. Written by
    generateItemPages.py, which therefore has to run before this generator."""
    path = os.path.join("assets", "json", "items_index.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} is missing; run generateItemPages.py first")
    return {int(it["id"]): it["slug"] for it in load_json(path) if it.get("slug")}


def load_gem_enchant_lookup():
    """Icon, rarity and Wowhead ref for socketed gems (by item id) and enchants (by
    enchant id), from the same enchantments.json catalog the spec pages use."""
    gems, enchants = {}, {}
    for e in load_json(os.path.join(LOOKUP_DIR, "enchantments.json")):
        info = {"icon": e.get("itemIcon") or e.get("spellIcon"), "quality": e.get("quality"),
                "name": e.get("itemName") or e.get("displayName")}
        if e.get("slot") == "socket":
            if e.get("itemId") is not None:
                gems[int(e["itemId"])] = dict(info, ref=f"item={e['itemId']}")
        elif e.get("id") is not None:
            # The enchanting scroll, else the enchant spell (DK runes have no scroll).
            ref = (f"item={e['itemId']}" if e.get("itemId") is not None
                   else f"spell={e['spellId']}" if e.get("spellId") is not None
                   else f"item={e['id']}")
            enchants[int(e["id"])] = dict(info, ref=ref)
    return gems, enchants


def build_gear_view(slots, spec_id, ctx):
    """Blocks of two columns of slot tiles, links pre-resolved: the item page when
    one exists, else Wowhead, plus enchant/gem aux icons."""
    def tile(slot, item):
        params = ""
        if item.get("bonus"):
            params += "&bonus=" + ":".join(str(b) for b in item["bonus"])
        if spec_id:
            params += f"&spec={spec_id}"
        if item.get("enchant"):
            params += f"&ench={item['enchant']}"
        if item.get("gems"):
            params += "&gems=" + ":".join(str(g) for g in item["gems"])
        slug = ctx["item_pages"].get(int(item["id"]))
        if slug:
            href = f"/items/{slug}" + (f"?spec={spec_id}" if spec_id else "")
        else:
            href = f"https://www.wowhead.com/item={item['id']}" + ("?" + params[1:] if params else "")
        aux = []
        if item.get("enchant"):
            info = ctx["enchants"].get(int(item["enchant"]), {"ref": f"item={item['enchant']}"})
            aux.append(dict(info, label="Enchant"))
        for gem in item.get("gems") or []:
            aux.append(dict(ctx["gems"].get(int(gem), {"ref": f"item={gem}"}), label="Gem"))
        return {
            "label": slot.replace("_", " "), "id": item["id"], "name": item.get("name"),
            "icon": item.get("icon") or QUESTION_ICON, "quality": item.get("quality"),
            "href": href, "external": not slug, "wowhead": f"item={item['id']}{params}", "aux": aux,
        }

    blocks = []
    for panes in GEAR_BLOCKS:
        cols = [{"head": head, "tiles": [tile(s, slots[s]) for s in names if s in slots]}
                for head, names in panes]
        if any(c["tiles"] for c in cols):
            blocks.append(cols)
    return blocks


def load_talent_tree(spec_id, ctx):
    """Decode order + render nodes + hero subtrees for a spec, cached per build.
    Render nodes get the spec page's filtering; the decode order stays complete
    because the loadout bitstream walks every node in it."""
    cache = ctx["trees"]
    if spec_id not in cache:
        doc = load_json(os.path.join(LOOKUP_DIR, "talents", f"{spec_id}.json"))
        cache[spec_id] = {
            "order": doc["fullNodeOrder"],
            "nodes": filter_talent_tree_nodes(doc["nodes"]),
            "subTrees": doc.get("subTrees") or {},
        }
    return cache[spec_id]


def build_talent_view(code, spec_id, ctx):
    """The decoded build as positioned class/spec columns plus the hero column,
    or {"message": ...} when it cannot be drawn."""
    if not code or not spec_id:
        return {"message": "No talent loadout recorded."}
    tree = load_talent_tree(spec_id, ctx)
    nodes = tree["nodes"]
    selected = decode_loadout(code, tree["order"], nodes)
    if selected is None:
        return {"message": "Talent loadout could not be read."}

    def active(nid):
        sel = selected.get(int(nid))
        return bool(nodes[nid].get("free") or (sel and sel["purchased"]))

    def is_choice(node):
        return len(node.get("entries") or []) > 1

    def node_view(nid):
        node = nodes[nid]
        sel = selected.get(int(nid)) or {}
        entries = node.get("entries") or [{}]
        entry = entries[sel.get("entry_index", 0)] if sel.get("entry_index", 0) < len(entries) else entries[0]
        if node.get("type") == "tiered":
            ntype = "passive"
        elif is_choice(node):
            ntype = "choice"
        else:
            ntype = entry.get("type") or "passive"
        return {"ntype": ntype, "active": active(nid), "icon": entry.get("icon") or QUESTION_ICON,
                "spell_id": entry.get("spellId"), "name": entry.get("name") or ""}

    def column(ids):
        ids = [nid for nid in ids if nid in nodes]
        if not ids:
            return None
        xs = [nodes[n].get("x") or 0 for n in ids]
        ys = [nodes[n].get("y") or 0 for n in ids]
        minx, miny = min(xs) - TREE_PADDING, min(ys) - TREE_PADDING
        w = max(1, max(xs) + TREE_PADDING - minx)
        h = max(1, max(ys) + TREE_PADDING - miny)

        def left(n):
            return round(((nodes[n].get("x") or 0) - minx) / w * 100, 3)

        def top(n):
            return round(((nodes[n].get("y") or 0) - miny) / h * 100, 3)

        group = set(ids)
        edges = [
            {"x1": left(n), "y1": top(n), "x2": left(str(c)), "y2": top(str(c)),
             "active": active(n) and active(str(c))}
            for n in ids for c in nodes[n].get("next") or [] if str(c) in group
        ]
        return {"edges": edges,
                "nodes": [dict(node_view(n), left=left(n), top=top(n)) for n in ids]}

    # The hero tree is the subtree most purchased picks sit in.
    hero_counts = Counter(
        str(nodes[str(nid)]["subTreeId"]) for nid, sel in selected.items()
        if sel["purchased"] and str(nid) in nodes and nodes[str(nid)].get("subTreeId") is not None
    )
    hero = hero_counts.most_common(1)[0][0] if hero_counts else None
    groups = {"class": [], "spec": [], "hero": []}
    for nid, node in nodes.items():
        g = node.get("g")
        if g == "hero" and str(node.get("subTreeId")) != hero:
            continue
        if g in groups:
            groups[g].append(nid)
    if not any(nodes[n].get("x") or nodes[n].get("y") for n in groups["class"] + groups["spec"]):
        return {"message": "Talent tree layout unavailable for this spec."}
    hero_view = None
    if groups["hero"]:
        sub = tree["subTrees"].get(hero) or {}
        choice = sorted((n for n in groups["hero"] if is_choice(nodes[n])),
                        key=lambda n: (nodes[n].get("y") or 0, nodes[n].get("x") or 0))
        hero_view = {"name": sub.get("name") or "Hero tree", "icon": sub.get("icon") or QUESTION_ICON,
                     "nodes": [node_view(n) for n in choice]}
    return {"class": column(groups["class"]), "spec": column(groups["spec"]), "hero": hero_view}


def build_character_view(char, ctx):
    """Template-ready raider.io details for one character: tier-coloured score, the
    world ranks (overall, class, each ranked spec), one row per season dungeon (best run + timed/total counts), recent
    runs, and the baked gear grid and talent tree."""
    view = dict(char)
    view["score_color"] = score_color(char.get("score"), ctx["tiers"])
    details = char.get("details")
    if not details:
        return view
    view["ilvl"] = details.get("ilvl")
    ranks = details.get("world_ranks") or {}
    rank_rows = [("Overall", ranks.get("overall")), (char.get("class_name") or "Class", ranks.get("class"))]
    for sid, rank in sorted((ranks.get("specs") or {}).items(), key=lambda kv: kv[1]):
        spec = ctx["spec_lookup"].get(str(sid))
        rank_rows.append((spec["name"] if spec else f"Spec {sid}", rank))
    view["world_ranks"] = [
        {"label": label, "rank": rank, "quality": rank_quality(rank)}
        for label, rank in rank_rows if rank
    ]

    def with_key(run):
        run = dict(run, dungeon_meta=ctx["dungeon_lookup"].get(str(run.get("cmid"))))
        run["key_text"], run["key_css"] = key_label(run)
        return run

    best = {str(r["cmid"]): with_key(r) for r in details.get("best_runs") or []}
    counts = {c["short_name"]: c for c in details.get("run_counts") or []}
    rows = []
    for cmid, d in ctx["dungeon_lookup"].items():
        c = counts.get(d.get("raiderio_short_name")) or {}
        rows.append({"dungeon": d, "best": best.get(cmid),
                     "timed": c.get("timed", 0), "total": c.get("total", 0)})
    rows.sort(key=lambda r: (r["best"]["level"] if r["best"] else 0, r["timed"]), reverse=True)
    view["dungeon_rows"] = rows
    # Capped to the Best runs row count so the two side-by-side tables end level.
    view["recent_runs"] = [with_key(r) for r in (details.get("recent_runs") or [])[:len(rows)]]

    slots = {}
    for slot, item in (details.get("slots") or {}).items():
        quality = resolve_bonus_quality(item.get("bonus"), ctx["bonus_quality"])
        slots[slot] = dict(item, quality=quality if quality is not None else item.get("quality"))
    if slots or details.get("talents"):
        spec_id = details.get("spec_id")
        view["gear"] = build_gear_view(slots, spec_id, ctx)
        view["talents"] = build_talent_view(details.get("talents"), spec_id, ctx)
    return view


def build_streamer_pages(vods, streamers, profiles, ctx):
    """Group the (template-shaped) vods into one page payload per streamer and stamp
    `streamer_slug` on each vod that has a page. Returns pages sorted by VOD count."""
    pages = {}
    for v in vods:
        s = streamers.get(v.get("streamer_key"))
        if not s:
            continue
        v["streamer_slug"] = s["slug"]
        pages.setdefault(s["slug"], {"streamer": s, "vods": []})["vods"].append(v)

    out = []
    for slug, p in pages.items():
        s, page_vods = p["streamer"], p["vods"]
        rank_run_entries(page_vods)
        characters = []
        for char_id, c in s["characters"].items():
            prof = profiles.get(char_id) or {}
            characters.append(build_character_view(
                dict(c, id=char_id, **{k: v for k, v in prof.items() if v is not None}), ctx,
            ))
        characters.sort(key=lambda c: (c["vods"], c.get("score") or 0), reverse=True)
        dungeon_counts = Counter(v["dungeon"] for v in page_vods)
        spec_counts = Counter(v["pov_spec_id"] for v in page_vods if v.get("pov_spec_id"))
        scores = [c["score"] for c in characters if c.get("score")]
        # A streamer's world ranks are their best-ranked character's (lowest overall
        # rank), the same Overall / class / spec set the streamer page shows.
        ranked = [c for c in characters if c.get("world_ranks")]
        best_ranked = min(ranked, key=lambda c: (
            ((c.get("details") or {}).get("world_ranks") or {}).get("overall") or float("inf")
        ), default=None)
        best_ranks = ((best_ranked or {}).get("details") or {}).get("world_ranks") or {}
        channel = s["channel"]
        out.append({
            "slug": slug,
            "best_score_color": score_color(max(scores), ctx["tiers"]) if scores else None,
            "name": s["name"],
            "channel": channel,
            "avatar": (channel and channel.get("avatar_url"))
                      or next((c["thumbnail_url"] for c in characters if c.get("thumbnail_url")), None),
            "characters": characters,
            "vods": page_vods,
            "vod_count": len(page_vods),
            "highest_key": max(v["highest_key"] or 0 for v in page_vods),
            "latest": max(v["timestamp"] or 0 for v in page_vods),
            "best_score": max(scores) if scores else None,
            "world_ranks": best_ranked["world_ranks"] if best_ranked else [],
            # Raw ranks for the Streamers grid sort (vods-streamers.js).
            "sort_ranks": {
                "overall": best_ranks.get("overall"),
                "class": best_ranks.get("class"),
                "specs": best_ranks.get("specs") or {},
            },
            "dungeons": [d for d, _ in dungeon_counts.most_common()],
            "specs": [str(sid) for sid, _ in spec_counts.most_common()],
            "classes": sorted({ctx["spec_lookup"][str(sid)]["classID"] for sid in spec_counts
                               if str(sid) in ctx["spec_lookup"]}),
        })
    out.sort(key=lambda p: (p["vod_count"], p["highest_key"]), reverse=True)
    return out


def main(template_path, output_dir, limit, streamers_dir):
    if (
        not os.environ.get("DATABASE_HOST")
        or not os.environ.get("DATABASE_USER")
        or not os.environ.get("DATABASE_PASSWORD")
    ):
        fail(
            "Missing DB credentials. Ensure DATABASE_HOST, DATABASE_USER, DATABASE_PASSWORD are set in the environment."
        )

    env = make_jinja_env(os.path.dirname(template_path))
    env.filters["humanize"] = humanize_number
    env.filters["duration"] = format_duration
    env.filters["format_ts"] = format_utc_timestamp
    env.filters["upgrade_info"] = upgrade_info
    env.filters["vod_embed"] = build_vod_embed_src

    spec_lookup = load_json(os.path.join(LOOKUP_DIR, "specs.json"))
    class_lookup = load_json(os.path.join(LOOKUP_DIR, "classes.json"))
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    spell_lookup = load_json(os.path.join(LOOKUP_DIR, "spells.json"))
    npc_lookup = load_json(os.path.join(LOOKUP_DIR, "npcs.json"))
    season_info = load_season_info(LOOKUP_DIR)
    notifications = load_notifications(LOOKUP_DIR)

    try:
        databaseConnector.init_connection_pool(
            os.environ.get("DATABASE_HOST"),
            os.environ.get("DATABASE_USER"),
            os.environ.get("DATABASE_PASSWORD"),
            os.environ.get("DATABASE_NAME"),
            os.environ.get("DATABASE_PORT"),
            1,
        )
    except Exception as e:
        fail(f"init_connection_pool failed: {e}")

    conn = None
    try:
        conn = databaseConnector.get_connection()
        cursor = conn.cursor()
        databaseConnector.configure_read_session(conn, cursor)
    except Exception as e:
        fail(f"Failed to obtain DB connection: {e}")

    try:
        comp_vods = databaseConnector.fetch_comp_vods(
            conn, cursor, limit=limit if limit and limit > 0 else None
        )
        if not isinstance(comp_vods, dict):
            fail("fetch_comp_vods returned unexpected type (expected dict).")
        npc_map = {}
        for dungeon in dungeon_lookup:
            npc_map[dungeon] = databaseConnector.fetch_distinct_npc_ids_for_dungeon(
                conn, cursor, dungeon
            )
        bloodlust_spell_ids = databaseConnector.fetch_bloodlust_spell_ids(conn, cursor)
        streamers = load_streamers(conn, cursor)
        profiles = databaseConnector.fetch_pov_character_profiles(conn, cursor)
    except Exception as e:
        fail(f"Error fetching data from DB: {e}")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    bloodlust_id_strs = [str(x) for x in bloodlust_spell_ids]
    bloodlust_icon = next(
        (
            spell_lookup[sid]["icon"]
            for sid in ["2825", "32182", *bloodlust_id_strs]
            if sid in spell_lookup and spell_lookup[sid].get("icon")
        ),
        None,
    )

    vods = []
    for info in comp_vods.values():
        v = dict(info)
        v["highest_key"] = v.get("level")
        v["pov_spec_id"] = v.get("pov_spec")
        vods.append(v)
    gems, enchants = load_gem_enchant_lookup()
    streamer_pages = build_streamer_pages(vods, streamers, profiles, {
        "dungeon_lookup": dungeon_lookup,
        "spec_lookup": spec_lookup,
        "tiers": load_score_tiers(LOOKUP_DIR),
        "bonus_quality": load_json(os.path.join(LOOKUP_DIR, "bonus_quality_map.json")),
        "item_pages": load_item_pages(),
        "gems": gems,
        "enchants": enchants,
        "trees": {},
    })

    comp_vods_by_dungeon = defaultdict(list)
    for v in vods:
        comp_vods_by_dungeon[str(v.get("dungeon"))].append(v)
    for dungeon_vods in comp_vods_by_dungeon.values():
        rank_run_entries(dungeon_vods)

    # The finder JSON only needs the page slug, not the grouping keys.
    for info in comp_vods.values():
        slug = streamers.get(info.pop("streamer_key"), {}).get("slug")
        info.pop("pov_character_id")
        if slug:
            info["streamer_slug"] = slug

    common = dict(
        trends=build_global_trends(),
        generated_at=datetime.now(timezone.utc).timestamp(),
        spec_nav=generateSpecNav(spec_lookup, class_lookup),
        dungeon_nav=generateDungeonNav(dungeon_lookup),
        dungeon_lookup=dungeon_lookup,
        spec_lookup=spec_lookup,
        season_info=season_info,
        active_page="vods",
        notifications=notifications,
        min_streamer_vods=MIN_STREAMER_VODS,
    )

    template = env.get_template(os.path.basename(template_path))
    output_html = template.render(
        **common,
        comp_vods_by_dungeon=comp_vods_by_dungeon,
        streamer_pages=streamer_pages,
        specs=spec_lookup,
        class_lookup=class_lookup,
        spell_lookup=spell_lookup,
        bloodlust_spell_ids=bloodlust_spell_ids,
        bloodlust_id_strs=bloodlust_id_strs,
        bloodlust_icon=bloodlust_icon,
        npc_lookup=npc_lookup,
        npc_map=npc_map,
        breadcrumbs=[
            {"title": "Pages", "href": "/pages"},
            {"title": "VODs", "href": "/vods"},
        ],
    )

    streamer_template = env.get_template("streamer.html")
    os.makedirs(streamers_dir, exist_ok=True)
    for page in streamer_pages:
        html = streamer_template.render(
            **common,
            streamer=page,
            breadcrumbs=[
                {"title": "Pages", "href": "/pages"},
                {"title": "VODs", "href": "/pages/vods"},
                {"title": page["name"], "href": f"/streamers/{page['slug']}"},
            ],
        )
        with open(os.path.join(streamers_dir, f"{page['slug']}.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
    kept = {f"{p['slug']}.html" for p in streamer_pages}
    for fn in os.listdir(streamers_dir):
        if fn.endswith(".html") and fn not in kept:
            os.remove(os.path.join(streamers_dir, fn))
    print(f"Generated {len(streamer_pages)} streamer page(s) in {streamers_dir}/")

    comp_vods_path = os.path.join("assets", "json", "compVods.json")
    os.makedirs(os.path.dirname(comp_vods_path), exist_ok=True)
    with open(comp_vods_path, "w", encoding="utf-8") as fh:
        json.dump(comp_vods, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote compVods JSON to {comp_vods_path}")

    out_path = os.path.join(output_dir, "vods.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(output_html)
    print(f"Generated {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate vods.html using DB-only data")
    parser.add_argument("--template", required=True, help="Path to Jinja template file")
    parser.add_argument("--output_dir", required=True, help="Output directory to write generated HTML")
    parser.add_argument(
        "--limit", type=int, default=0, help="Optional limit to number of videos pulled (0 = no limit)"
    )
    parser.add_argument(
        "--streamers_dir", default="streamers", help="Output directory for the per-streamer pages"
    )
    args = parser.parse_args()
    main(args.template, args.output_dir, args.limit, args.streamers_dir)
