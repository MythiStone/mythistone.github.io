"""Render the dungeon pages' preview images (assets/img/previews/<slug>.png).

Runs as its own CI job next to the page build: the keystone.guru route thumbnail
on each image can sit in a shared render queue for many minutes. Thumbnails are
cached by route key, so only a dungeon whose top route changed asks keystone.guru
again, and one that is not ready within the budget falls back to the dungeon's
previous thumbnail (retried on the next build).

Needs DATABASE_*, and KEYSTONE_GURU_USER / KEYSTONE_GURU_PW for cache misses.
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import databaseConnector
from commonUtils import LOOKUP_DIR, load_json, load_season_info
from image_generation.dungeon_overview import createDungeonOverviewImg, fetch_route_thumbnail


def fetch_preview_data(season, dungeon_ids):
    """Every DB row the previews need, read up front so no connection is held
    while the thumbnails render."""
    conn = databaseConnector.get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        databaseConnector.configure_read_session(conn, cursor)
        per_level = databaseConnector.fetch_runs_per_dungeon_per_level(conn, cursor, season)
        data = {}
        for dungeon_id in dungeon_ids:
            data[dungeon_id] = {
                "dungeon_totals": databaseConnector.fetch_dungeon_totals(conn, cursor, dungeon_id, season),
                "top_comps_data": databaseConnector.fetch_dungeon_top_comps(conn, cursor, dungeon_id, season),
                "per_level": [r for r in per_level if str(r.get("dungeon_id")) == str(dungeon_id)],
                "top_routes_data": databaseConnector.fetch_dungeon_top_routes(conn, cursor, dungeon_id),
            }
        cursor.close()
        return data
    finally:
        databaseConnector.close_quietly(conn)


def cached_routes(dungeon_dir):
    """Route keys cached for one dungeon, newest first."""
    if not os.path.isdir(dungeon_dir):
        return []
    pngs = [f for f in os.listdir(dungeon_dir) if f.endswith(".png")]
    pngs.sort(key=lambda f: os.path.getmtime(os.path.join(dungeon_dir, f)), reverse=True)
    return [os.path.splitext(f)[0] for f in pngs]


def load_cached(dungeon_dir, route_key):
    """(thumbnail, route) of a cached entry. The route sidecar carries what the
    image labels the map with, so a fallback map is not captioned as the new route."""
    with open(os.path.join(dungeon_dir, f"{route_key}.json"), encoding="utf-8") as fh:
        route = json.load(fh)
    return Image.open(os.path.join(dungeon_dir, f"{route_key}.png")).convert("RGBA"), route


def main(output_dir, cache_dir, budget_seconds):
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    season = load_season_info(LOOKUP_DIR)["blizzard_season_id"]
    data = fetch_preview_data(season, list(dungeon_lookup))

    deadline = time.monotonic() + budget_seconds
    executor = ThreadPoolExecutor(max_workers=8)
    pending = {}
    for dungeon_id, rows in data.items():
        top_routes = rows["top_routes_data"]
        route_key = top_routes[0].get("route_key") if top_routes else None
        dungeon_dir = os.path.join(cache_dir, str(dungeon_id))
        if route_key and route_key not in cached_routes(dungeon_dir):
            pending[dungeon_id] = executor.submit(
                fetch_route_thumbnail, dungeon_id, route_key, deadline=deadline)

    summary = []
    for dungeon_id, rows in data.items():
        top_routes = rows["top_routes_data"]
        route_key = top_routes[0].get("route_key") if top_routes else None
        dungeon_dir = os.path.join(cache_dir, str(dungeon_id))
        thumbnail, status = None, "no top route"
        if route_key:
            status = "cached"
            if dungeon_id in pending:
                thumbnail = pending[dungeon_id].result()
                status = "fetched"
                if thumbnail is not None:
                    os.makedirs(dungeon_dir, exist_ok=True)
                    thumbnail.save(os.path.join(dungeon_dir, f"{route_key}.png"))
                    with open(os.path.join(dungeon_dir, f"{route_key}.json"), "w", encoding="utf-8") as fh:
                        json.dump({"route_key": route_key, "specs": top_routes[0].get("specs", [])}, fh)
            cached = cached_routes(dungeon_dir)
            if thumbnail is None and cached:
                if route_key not in cached:
                    status = f"not ready, previous route {cached[0]} shown"
                use_key = route_key if route_key in cached else cached[0]
                thumbnail, route = load_cached(dungeon_dir, use_key)
                rows["top_routes_data"] = [route]
            elif thumbnail is None:
                status = "not ready, no map"
            # keep the route shown now and one older as the next fallback
            keep = [k for k in cached if k == route_key] + [k for k in cached if k != route_key][:1]
            for stale in set(cached) - set(keep):
                os.remove(os.path.join(dungeon_dir, f"{stale}.png"))
                os.remove(os.path.join(dungeon_dir, f"{stale}.json"))

        slug = dungeon_lookup[dungeon_id]["slug"]
        result = createDungeonOverviewImg(
            tmpdir=os.path.join("tmp", "img"),
            out_path=os.path.join(output_dir, f"{slug}.png"),
            dungeon_id=dungeon_id,
            season=season,
            route_thumbnail=thumbnail,
            **rows,
        )
        if result is None:
            raise RuntimeError(f"no preview rendered for dungeon {dungeon_id}")
        summary.append((slug, route_key or "", status))
        print(f"{slug}: {status}")
    executor.shutdown(wait=False)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("| Dungeon | Top route | Thumbnail |\n|---|---|---|\n")
            for slug, route_key, status in summary:
                fh.write(f"| {slug} | {route_key} | {status} |\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render the dungeon page preview images")
    parser.add_argument("--output_dir", default=os.path.join("assets", "img", "previews"))
    parser.add_argument("--cache_dir", default="route-thumbs", help="Thumbnail cache, one folder per dungeon")
    parser.add_argument("--budget_seconds", type=int, default=900,
                        help="Shared wait for all keystone.guru thumbnails that are not cached")
    args = parser.parse_args()

    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST", "127.0.0.1"),
        os.environ.get("DATABASE_USER", "root"),
        os.environ.get("DATABASE_PASSWORD", ""),
        os.environ.get("DATABASE_NAME", "Mythistone"),
        os.environ.get("DATABASE_PORT", "3306"),
        1,
    )
    main(args.output_dir, args.cache_dir, args.budget_seconds)
