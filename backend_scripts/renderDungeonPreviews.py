"""Render the dungeon pages' preview images (assets/img/previews/<slug>.png).

Runs as its own CI job next to the page build: the keystone.guru route thumbnail
on each image can sit in a shared render queue for a long time, and every job is
waited on until keystone.guru finishes it (completed, error or expired) or the
2h THUMBNAIL_TIMEOUT passes. Thumbnails are cached by route key, so only a
dungeon whose top route changed asks keystone.guru again, and one whose job
fails or times out shows the dungeon's previous route.

Needs DATABASE_*, and KEYSTONE_GURU_USER / KEYSTONE_GURU_PW for cache misses.
"""
import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import databaseConnector
from commonUtils import LOOKUP_DIR, load_json, load_season_info
from image_generation.dungeon_overview import (
    createDungeonOverviewImg,
    describe_job,
    submit_route_thumbnail,
    wait_route_thumbnail,
)


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


def save_cached(dungeon_dir, route, image):
    os.makedirs(dungeon_dir, exist_ok=True)
    image.save(os.path.join(dungeon_dir, f"{route['route_key']}.png"))
    with open(os.path.join(dungeon_dir, f"{route['route_key']}.json"), "w", encoding="utf-8") as fh:
        json.dump({"route_key": route["route_key"], "specs": route.get("specs", [])}, fh)


def top_route(top_routes):
    return next((r for r in top_routes if r.get("route_key")), None)


def fetch_thumbnail(dungeon_id, route_key):
    """(image, job) for a route, waiting until keystone.guru finishes the job."""
    job = submit_route_thumbnail(dungeon_id, route_key)
    if job is None:
        return None, None
    return wait_route_thumbnail(route_key, job)


def main(output_dir, cache_dir):
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    season = load_season_info(LOOKUP_DIR)["blizzard_season_id"]
    data = fetch_preview_data(season, list(dungeon_lookup))

    wanted = []
    for dungeon_id, rows in data.items():
        route = top_route(rows["top_routes_data"])
        cached = cached_routes(os.path.join(cache_dir, str(dungeon_id)))
        if route and route["route_key"] not in cached:
            print(f"dungeon {dungeon_id}: top route {route['route_key']} not cached, cached {cached}")
            wanted.append((dungeon_id, route))

    # one thread per job: a job is waited on until it finishes, so a smaller pool
    # would hold later jobs back from even being submitted
    pending = {}
    with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as executor:
        for dungeon_id, route in wanted:
            pending[dungeon_id] = (route, executor.submit(fetch_thumbnail, dungeon_id, route["route_key"]))

        fetched, jobs = set(), {}
        for dungeon_id, (route, future) in pending.items():
            image, jobs[dungeon_id] = future.result()
            if image is not None:
                save_cached(os.path.join(cache_dir, str(dungeon_id)), route, image)
                fetched.add(route["route_key"])

    summary = []
    for dungeon_id, rows in data.items():
        route = top_route(rows["top_routes_data"])
        route_key = route["route_key"] if route else None
        dungeon_dir = os.path.join(cache_dir, str(dungeon_id))
        thumbnail, status = None, "no top route"
        if route_key:
            cached = cached_routes(dungeon_dir)
            shown = route_key if route_key in cached else (cached[0] if cached else None)
            job = jobs.get(dungeon_id)
            missing = f"top route {job.get('status') if job else 'request failed'}"
            if shown == route_key:
                status = "fetched" if route_key in fetched else "cached"
            elif shown:
                status = f"{missing}, previous route {shown} shown"
            else:
                status = f"{missing}, no map"
            if shown:
                thumbnail, route = load_cached(dungeon_dir, shown)
                rows["top_routes_data"] = [route]
            # keep the route shown now and one older as the next fallback
            keep = {shown} if shown else set()
            keep.update([k for k in cached if k not in keep][:1])
            for stale in set(cached) - keep:
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
        summary.append((slug, route_key or "", status, describe_job(jobs[dungeon_id]) if dungeon_id in jobs else ""))
        print(f"{slug}: {status}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("| Dungeon | Top route | Thumbnail | keystone.guru job |\n|---|---|---|---|\n")
            for row in summary:
                fh.write("| " + " | ".join(row) + " |\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render the dungeon page preview images")
    parser.add_argument("--output_dir", default=os.path.join("assets", "img", "previews"))
    parser.add_argument("--cache_dir", default="route-thumbs", help="Thumbnail cache, one folder per dungeon")
    args = parser.parse_args()

    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST", "127.0.0.1"),
        os.environ.get("DATABASE_USER", "root"),
        os.environ.get("DATABASE_PASSWORD", ""),
        os.environ.get("DATABASE_NAME", "Mythistone"),
        os.environ.get("DATABASE_PORT", "3306"),
        1,
    )
    main(args.output_dir, args.cache_dir)
