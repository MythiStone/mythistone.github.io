import os
import sys
import json
import argparse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from datetime import datetime, timezone

from pageGeneration import generateSpecNav, generateDungeonNav, build_global_trends
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


def fail(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(2)


def main(template_path, output_dir, limit):
    if (
        not os.environ.get("DATABASE_HOST")
        or not os.environ.get("DATABASE_USER")
        or not os.environ.get("DATABASE_PASSWORD")
    ):
        fail(
            "Missing DB credentials. Ensure DATABASE_HOST, DATABASE_USER, DATABASE_PASSWORD are set in the environment."
        )

    env = Environment(
        loader=FileSystemLoader(os.path.dirname(template_path)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["humanize"] = humanize_number
    env.filters["duration"] = format_duration
    env.filters["format_ts"] = format_utc_timestamp
    env.filters["upgrade_info"] = upgrade_info

    spec_lookup = load_json(os.path.join(LOOKUP_DIR, "specs.json"))
    class_lookup = load_json(os.path.join(LOOKUP_DIR, "classes.json"))
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    spell_lookup = load_json(os.path.join(LOOKUP_DIR, "spells.json"))
    npc_lookup = load_json(os.path.join(LOOKUP_DIR, "npcs.json"))
    season_info = load_season_info(LOOKUP_DIR)
    notifications = load_json(os.path.join(LOOKUP_DIR, "notifications.json"))

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

    template = env.get_template(os.path.basename(template_path))
    output_html = template.render(
        trends=build_global_trends(),
        generated_at=datetime.now(timezone.utc).timestamp(),
        spec_nav=generateSpecNav(spec_lookup, class_lookup),
        dungeon_nav=generateDungeonNav(dungeon_lookup),
        dungeon_lookup=dungeon_lookup,
        specs=spec_lookup,
        class_lookup=class_lookup,
        spell_lookup=spell_lookup,
        spec_lookup=spec_lookup,
        bloodlust_spell_ids=bloodlust_spell_ids,
        bloodlust_id_strs=bloodlust_id_strs,
        bloodlust_icon=bloodlust_icon,
        npc_lookup=npc_lookup,
        npc_map=npc_map,
        season_info=season_info,
        active_page="vods",
        notifications=notifications,
        breadcrumbs=[
            {"title": "Pages", "href": "/pages"},
            {"title": "VODs", "href": "/vods"},
        ],
    )

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
    args = parser.parse_args()
    main(args.template, args.output_dir, args.limit)
