"""Generate the consumables browse page and one static page per consumable.

Mirrors the item-pages workflow (generateItemPages.py) but for the much smaller,
flatter consumable entity set: the aura consumables in data/static/consumables.json
(flask/potion/food/augment) plus the weapon-enchant oils in
data/static/temp-enchants.json. Usage lives in aggregated_consumables
(spec_id, season, hero_talent_id, spell_id, run_count) with NO dungeon/key-level
dimension, so these pages are spec/class-centric: which specs use each consumable
and each one's share within its category.

The DB stores only the buff spell id, so the spell -> item/category resolution is
the same build-time name match the spec page uses (commonUtils.match_consumable_aura);
weapon oils resolve via the temp-enchant effectId index. This generator inverts that
resolution so runs accumulate per consumable item, then writes:

  - consumables/<slug>.html      one server-rendered page per consumable
  - pages/consumables.html       the filterable browse grid
  - assets/json/consumables_index.json   the compact manifest the grid fetches
  - OG preview cards (best-effort)

It is credential-gated exactly like generateItemPages (needs the DATABASE_* exports
the seeder prints); every static lookup is DB-free.
"""

import os
import sys
import json
import random
import hashlib
import argparse
from contextlib import closing
from collections import defaultdict
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape

import databaseConnector
import commonUtils
from pageGeneration import (
    generateSpecNav, generateDungeonNav, build_consumable_slug_map,
    build_trends, trend_feeds_for_consumables, trend_feeds_for_consumable,
)
from generateSpecPages import LOOKUP_DIR, load_json, load_season_info

# Category display labels + order, mirroring CONSUMABLE_CATEGORY_LABELS in
# generateSpecPages so the browse filter and detail siblings read in the same
# order as the spec-page consumable sections.
CATEGORY_LABELS = [
    ("flask", "Flask"),
    ("potion", "Potion"),
    ("food", "Food"),
    ("weapon", "Weapon Enchant"),
    ("augment", "Augment Rune"),
]
CATEGORY_LABEL = {k: v for k, v in CATEGORY_LABELS}
CATEGORY_ORDER = {k: i for i, (k, _) in enumerate(CATEGORY_LABELS)}
# Readable noun for the intro copy.
CATEGORY_NOUN = {
    "flask": "flask", "potion": "combat potion", "food": "food buff",
    "weapon": "weapon enchant", "augment": "augment rune",
}

# Other consumables in the same category shown on a detail page.
TOP_SIBLINGS = 11

# A consumable only gets a page once it has been seen in at least this many
# tracked runs, so a single stray sample never spawns an empty page. The set is
# tiny (~40 entities), so the threshold is deliberately low.
CONSUMABLE_RENDER_MIN_RUNS = 5


def fail(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(2)


def load_static_lookups():
    """Load every DB-free static lookup the consumable build needs.

    ``entities`` is the merged catalog keyed by item id: aura consumables from
    consumables.json plus weapon-enchant oils from temp-enchants.json (category
    ``weapon``). ``temp_enchant_index`` (effectId -> item) is kept separately for
    the weapon-oil usage sweep, which is keyed by effectId, not item id.
    """
    season_info = load_season_info(LOOKUP_DIR)
    season = season_info.get("blizzard_season_id")

    spec_lookup = load_json(os.path.join(LOOKUP_DIR, "specs.json"))
    class_lookup = load_json(os.path.join(LOOKUP_DIR, "classes.json"))
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    notifications = load_json(os.path.join(LOOKUP_DIR, "notifications.json"))

    # spell -> consumable resolver (name / shortName / food-buff map).
    consumable_index = commonUtils.build_consumable_index(static_dir=LOOKUP_DIR)

    entities = {}
    for c in commonUtils.load_consumables(LOOKUP_DIR):
        iid = c.get("item_id")
        if iid is None:
            continue
        entities[int(iid)] = {
            "item_id": int(iid),
            "name": c.get("name") or f"Item {iid}",
            "icon": c.get("icon"),
            "quality": c.get("quality"),
            "category": c.get("category"),
        }
    temp_enchant_index = commonUtils.load_temp_enchant_index(LOOKUP_DIR)
    for meta in temp_enchant_index.values():
        iid = meta.get("item_id")
        if iid is None:
            continue
        entities[int(iid)] = {
            "item_id": int(iid),
            "name": meta.get("name") or f"Item {iid}",
            "icon": meta.get("icon"),
            "quality": meta.get("quality"),
            "category": "weapon",
        }

    slug_map = build_consumable_slug_map(entities)

    # Role int -> the /classes/<folder>/ page bucket (mirrors ROLE_FOLDERS in
    # pageGeneration.generateSpecNav so consumable-page spec links hit the same URLs).
    ROLE_FOLDERS = {0: "Tank", 1: "Healer", 2: "Dps"}

    def _class_color(color):
        if not isinstance(color, dict):
            return None
        try:
            return "#{:02x}{:02x}{:02x}".format(
                int(color["r"]), int(color["g"]), int(color["b"]))
        except (KeyError, TypeError, ValueError):
            return None

    specs_map = {}
    for sid, s in spec_lookup.items():
        c = class_lookup.get(s.get("classID", ""), {})
        role = int(s.get("role", 2))
        spec_name = s.get("name", "Unknown")
        class_name = c.get("name", "Unknown")
        specs_map[str(sid)] = {
            "name": spec_name,
            "className": class_name,
            "classSlug": (class_name or "").replace(" ", ""),
            "role": role,
            "icon": s.get("SpellIconFileId"),
            "color": _class_color(c.get("color")),
            "page": f"/classes/{ROLE_FOLDERS.get(role, 'Dps')}/{spec_name}_{class_name}",
        }

    return {
        "season_info": season_info,
        "season": season,
        "spec_lookup": spec_lookup,
        "class_lookup": class_lookup,
        "dungeon_lookup": dungeon_lookup,
        "notifications": notifications,
        "consumable_index": consumable_index,
        "entities": entities,
        "temp_enchant_index": temp_enchant_index,
        "slug_map": slug_map,
        "specs_map": specs_map,
    }


def build_payloads(season, ctx):
    """Sweep aggregated_consumables (+ weapon-oil enchant usage) once and assemble
    the per-consumable payloads + manifest. Opens and closes its own DB connection,
    so the pool must already be initialised. Returns ``(payloads, manifest)``.
    """
    consumable_index = ctx["consumable_index"]
    entities = ctx["entities"]
    temp_enchant_index = ctx["temp_enchant_index"]
    slug_map = ctx["slug_map"]
    spec_lookup = ctx["spec_lookup"]

    # item_id -> spec_id (str) -> runs
    runs_by_item = defaultdict(lambda: defaultdict(int))
    # category -> spec_id (str) -> runs   (per-spec category denominator)
    cat_spec_total = defaultdict(lambda: defaultdict(int))
    # category -> runs   (global category denominator)
    cat_total = defaultdict(int)

    effect_ids = list(temp_enchant_index.keys())
    spec_ids = [str(s) for s in spec_lookup.keys()]
    with closing(databaseConnector.get_connection()) as conn:
        cursor = conn.cursor()
        databaseConnector.configure_read_session(conn, cursor)
        for i, sp in enumerate(spec_ids, 1):
            print(f"[{datetime.now(timezone.utc).isoformat()}] sweeping spec {sp} ({i}/{len(spec_ids)})...")

            # Aura consumables (flask/potion/food/augment): resolve each buff spell
            # id to its consumable item, exactly like build_consumable_sections.
            for spell_id, name, icon, run_count in databaseConnector.fetch_consumable_count(
                    conn, cursor, sp, season):
                matched = commonUtils.match_consumable_aura(
                    {"id": spell_id, "name": name, "icon": icon}, consumable_index)
                if not matched:
                    continue
                item_id = matched.get("item_id")
                if item_id is None or int(item_id) not in entities:
                    continue
                rc = int(run_count)
                item_id = int(item_id)
                cat = entities[item_id]["category"]
                runs_by_item[item_id][sp] += rc
                cat_spec_total[cat][sp] += rc
                cat_total[cat] += rc

            # Weapon-enchant oils: a separate data source (enchant aggregation),
            # resolved via the effectId -> item index.
            if effect_ids:
                for enchant_id, run_count in databaseConnector.fetch_weapon_temp_enchant_usage(
                        conn, cursor, sp, season, effect_ids):
                    meta = temp_enchant_index.get(int(enchant_id))
                    if not meta:
                        continue
                    item_id = meta.get("item_id")
                    if item_id is None or int(item_id) not in entities:
                        continue
                    rc = int(run_count)
                    item_id = int(item_id)
                    runs_by_item[item_id][sp] += rc
                    cat_spec_total["weapon"][sp] += rc
                    cat_total["weapon"] += rc

    # ---- assemble per-consumable payloads -------------------------------
    payloads = {}
    manifest = []
    for item_id, per_spec in runs_by_item.items():
        total_runs = sum(per_spec.values())
        if total_runs < CONSUMABLE_RENDER_MIN_RUNS:
            continue
        ent = entities[item_id]
        cat = ent["category"]

        specs_rank = []
        for sp, runs in per_spec.items():
            denom = cat_spec_total[cat].get(sp, 0)
            # Share of this spec's own usage in the category that went to this
            # consumable (same "share within category" semantics as the spec page).
            share = round(runs / denom * 100, 1) if denom else None
            specs_rank.append({
                "spec_id": int(sp),
                "runs": int(runs),
                "cat_runs": int(denom) if denom else None,
                "share": share,
            })
        specs_rank.sort(key=lambda x: (x["runs"], x["share"] or 0), reverse=True)

        top_spec = int(max(per_spec, key=per_spec.get)) if per_spec else None
        cat_denom = cat_total.get(cat, 0)
        category_share = round(total_runs / cat_denom * 100, 1) if cat_denom else None

        payload = {
            "id": item_id,
            "name": ent["name"],
            "icon": ent["icon"],
            "quality": ent["quality"],
            "category": cat,
            "category_label": CATEGORY_LABEL.get(cat, cat.title()),
            "total_runs": int(total_runs),
            "category_runs": int(cat_denom) if cat_denom else None,
            "category_share": category_share,
            "specs": specs_rank,
        }
        payloads[item_id] = payload

        equipped_specs = sorted(int(sp) for sp, rc in per_spec.items() if rc > 0)
        manifest.append({
            "id": item_id,
            "name": ent["name"],
            "icon": ent["icon"],
            "quality": ent["quality"],
            "category": cat,
            "category_label": CATEGORY_LABEL.get(cat, cat.title()),
            "slug": slug_map[item_id],
            "runs": int(total_runs),
            "top_spec": top_spec,
            "specs": equipped_specs,
        })

    manifest.sort(key=lambda x: x["runs"], reverse=True)
    return payloads, manifest


def _intro_rng(item_id):
    """Deterministic per-consumable RNG so phrasing varies across consumables but
    never churns on rebuilds (same idea as generateItemPages._intro_rng)."""
    seed = int(hashlib.md5(str(item_id).encode("utf-8")).hexdigest()[:12], 16)
    return random.Random(seed)


def _spec_display(specs_map, spec_id):
    s = specs_map.get(str(spec_id))
    return f"{s['name']} {s['className']}".strip() if s else None


def build_consumable_intro(payload, specs_map, season_name):
    """A short paragraph summarizing the consumable's tracked usage. Every number is
    lifted from the payload the page already renders; clauses with no data drop."""
    rng = _intro_rng(payload["id"])
    name = payload["name"]
    noun = CATEGORY_NOUN.get(payload["category"], "consumable")
    article = "an" if noun[:1].lower() in "aeiou" else "a"
    total = payload.get("total_runs") or 0

    parts = [rng.choice([
        f"{name} is {article} {noun} tracked by MythiStone across {season_name} Mythic+ runs.",
        f"{name} is {article} {noun} seen on high-key {season_name} Mythic+ players.",
    ])]

    if payload.get("category_share") is not None and payload.get("category_runs"):
        parts.append(rng.choice([
            f"It appears in {total:,} tracked runs, {payload['category_share']}% of all "
            f"{payload['category_label'].lower()} usage this season.",
            f"So far it shows up in {total:,} runs, {payload['category_share']}% of "
            f"the {payload['category_label'].lower()} category's tracked usage.",
        ]))
    elif total:
        parts.append(f"It appears in {total:,} tracked runs this season.")

    specs = [s for s in payload.get("specs", []) if s.get("share") is not None]
    if specs:
        top = specs[0]
        spec_name = _spec_display(specs_map, top["spec_id"])
        if spec_name:
            parts.append(rng.choice([
                f"Its biggest audience is {spec_name} players, {top['share']}% of whose "
                f"{payload['category_label'].lower()} runs bring it.",
                f"{spec_name} players lean on it the most, running it in {top['share']}% of "
                f"their {payload['category_label'].lower()} picks.",
            ]))
    return " ".join(parts)


def build_meta_description(intro):
    if len(intro) <= 160:
        return intro
    return intro[:157].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _write_index(manifest):
    os.makedirs(os.path.join("assets", "json"), exist_ok=True)
    with open(os.path.join("assets", "json", "consumables_index.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"), ensure_ascii=False)
    print(f"[{datetime.now(timezone.utc).isoformat()}] wrote consumables manifest ({len(manifest)} entries)")


def main(template_path, output_dir, consumables_dir="consumables", debug=False,
         target_item=None, want_previews=True):
    ctx = load_static_lookups()
    season = ctx["season"]
    if not season:
        fail("blizzard_season_id missing from seasonInfo.json")
    if (
        not os.environ.get("DATABASE_HOST")
        or not os.environ.get("DATABASE_USER")
        or not os.environ.get("DATABASE_PASSWORD")
    ):
        fail("Missing DB credentials (DATABASE_HOST/USER/PASSWORD).")

    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST"),
        os.environ.get("DATABASE_USER"),
        os.environ.get("DATABASE_PASSWORD"),
        os.environ.get("DATABASE_NAME", "Mythistone"),
        os.environ.get("DATABASE_PORT", "3306"),
        1,
    )

    payloads, manifest = build_payloads(season, ctx)
    _write_index(manifest)

    season_info = ctx["season_info"]
    spec_lookup = ctx["spec_lookup"]
    class_lookup = ctx["class_lookup"]
    dungeon_lookup = ctx["dungeon_lookup"]
    slug_map = ctx["slug_map"]
    specs_map = ctx["specs_map"]
    notifications = ctx["notifications"]

    # Other consumables in the same category, ranked by usage, for the detail
    # page's "Other <category>" card (manifest is already sorted by runs desc).
    by_category = defaultdict(list)
    for m in manifest:
        by_category[m["category"]].append(m)

    env = Environment(
        loader=FileSystemLoader(os.path.dirname(template_path)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    spec_nav = generateSpecNav(spec_lookup, class_lookup)
    dungeon_nav = generateDungeonNav(dungeon_lookup)

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(consumables_dir, exist_ok=True)

    render_items = list(payloads.items())
    if debug:
        chosen = None
        if target_item:
            for iid in payloads:
                if str(iid) == str(target_item) or slug_map[iid] == target_item:
                    chosen = iid
                    break
            if chosen is None:
                print(f"--item '{target_item}' not found; falling back to the most-used consumable.")
        if chosen is None and manifest:
            chosen = manifest[0]["id"]
        render_items = [(chosen, payloads[chosen])] if chosen else []
        print(f"[debug] rendering only consumable {chosen} "
              f"({slug_map[chosen] if chosen else 'none'})")

    if not want_previews:
        preview_ids = set()
    elif debug:
        preview_ids = {iid for iid, _ in render_items}
    else:
        preview_ids = {m["id"] for m in manifest}

    # One live connection for the per-consumable + list-page trend bars. The
    # "consumables" lookup resolves the global-bar rows (keyed by item id) to each
    # consumable's name/icon/page link.
    consumables_lookup = {
        str(iid): {"name": e["name"], "icon": e["icon"], "slug": slug_map[iid]}
        for iid, e in ctx["entities"].items()
    }
    trend_lookups = {"specs": spec_lookup, "classes": class_lookup,
                     "consumables": consumables_lookup}
    trends_conn = databaseConnector.get_connection()
    trends_cursor = trends_conn.cursor()
    databaseConnector.configure_read_session(trends_conn, trends_cursor)
    global_trends = build_trends(
        trends_conn, trends_cursor, trend_feeds_for_consumables(), trend_lookups)

    detail_tmpl = env.get_template("consumable.html")
    for item_id, payload in render_items:
        slug = slug_map[item_id]
        siblings = [s for s in by_category.get(payload["category"], [])
                    if s["id"] != item_id][:TOP_SIBLINGS]
        intro = build_consumable_intro(payload, specs_map, season_info.get("name", ""))
        item_trends = build_trends(trends_conn, trends_cursor,
                                   trend_feeds_for_consumable(item_id), trend_lookups)
        if not item_trends:
            item_trends = global_trends
        html = detail_tmpl.render(
            trends=item_trends,
            consumable=payload,
            slug=slug,
            slug_map=slug_map,
            intro=intro,
            meta_description=build_meta_description(intro),
            has_preview=item_id in preview_ids,
            siblings=siblings,
            active_page="consumables",
            cur_page="consumables",
            breadcrumbs=[
                {"title": "Pages", "href": "/pages"},
                {"title": "Consumables", "href": "/pages/consumables"},
                {"title": payload["name"], "href": f"/consumables/{slug}"},
            ],
            spec_nav=spec_nav,
            dungeon_nav=dungeon_nav,
            season_info=season_info,
            notifications=notifications,
            specs_map=specs_map,
        )
        with open(os.path.join(consumables_dir, f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    print(f"[{datetime.now(timezone.utc).isoformat()}] wrote {len(render_items)} consumable page(s) to {consumables_dir}/")

    # Drop pages for consumables that no longer qualify, so a stale file can't
    # linger in the deploy or sitemap. Skipped in debug (renders one page).
    if not debug:
        kept = {f"{slug_map[iid]}.html" for iid, _ in render_items}
        removed = 0
        for fn in os.listdir(consumables_dir):
            if fn.endswith(".html") and fn not in kept:
                os.remove(os.path.join(consumables_dir, fn))
                removed += 1
        if removed:
            print(f"[{datetime.now(timezone.utc).isoformat()}] removed {removed} stale consumable page(s)")

    # OG preview card for the browse page itself (best-effort; a thumbnail failure
    # must never block the page build).
    overview_url = None
    if want_previews:
        try:
            from image_generation.consumable_overview import (
                OVERVIEW_REL_PATH, OVERVIEW_URL, render_consumables_overview)
            render_consumables_overview(manifest, season_info.get("name", ""), OVERVIEW_REL_PATH)
            overview_url = OVERVIEW_URL
        except Exception as e:
            print(f"WARN: failed to render consumables overview preview: {e}", file=sys.stderr)

    trends_conn.close()
    page = env.get_template(os.path.basename(template_path))
    page_html = page.render(
        trends=global_trends,
        active_page="consumables",
        cur_page="consumables",
        breadcrumbs=[
            {"title": "Pages", "href": "/pages"},
            {"title": "Consumables", "href": "/pages/consumables"},
        ],
        overview_url=overview_url,
        consumable_count=len(manifest),
        spec_nav=spec_nav,
        dungeon_nav=dungeon_nav,
        season_info=season_info,
        notifications=notifications,
        specs_map=specs_map,
    )
    with open(os.path.join(output_dir, "consumables.html"), "w", encoding="utf-8") as f:
        f.write(page_html)
    print(f"Generated {os.path.join(output_dir, 'consumables.html')}")

    # ---- per-consumable preview cards (OG images) ----------------------
    if want_previews:
        try:
            from image_generation.consumable_overview import render_consumable_previews
            if debug:
                chosen_ids = {iid for iid, _ in render_items}
                order = [m for m in manifest if m["id"] in chosen_ids]
            else:
                order = manifest
            render_consumable_previews(payloads, slug_map, order)
        except Exception as e:
            print(f"WARN: failed to render consumable preview cards: {e}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate the consumables browse page and one static page per consumable")
    parser.add_argument("--template", required=True, help="Path to the consumables browse page template")
    parser.add_argument("--output_dir", required=True, help="Directory to write the browse page (pages/)")
    parser.add_argument("--consumables_dir", default="consumables",
                        help="Directory to write per-consumable pages (default: consumables)")
    parser.add_argument("--debug", action="store_true",
                        help="Render only the browse page and a single consumable page")
    parser.add_argument("--item", dest="target_item",
                        help="In --debug, the consumable id or slug to render (default: most-used)")
    parser.add_argument("--no_previews", action="store_true",
                        help="Skip rendering the OG preview cards")
    args = parser.parse_args()
    main(args.template, args.output_dir, args.consumables_dir, args.debug,
         args.target_item, want_previews=not args.no_previews)
