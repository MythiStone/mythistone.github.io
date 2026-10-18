"""Render the dungeon pages' preview images (assets/img/previews/<slug>.png).

Runs as its own CI job next to the page build: the keystone.guru route thumbnail
on each image can sit in a shared render queue for many minutes. Thumbnails are
cached by route key, so only a dungeon whose top route changed asks keystone.guru
again. A job still queued at the end of the budget is saved in the cache and
polled again by the next build, which keeps its place in the queue. Until the
top route is ready the image shows the next-ranked route or the dungeon's
previous one.

Needs DATABASE_*, and KEYSTONE_GURU_USER / KEYSTONE_GURU_PW for cache misses.
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from PIL import Image

import databaseConnector
from commonUtils import LOOKUP_DIR, load_json, load_season_info
from image_generation.dungeon_overview import (
    createDungeonOverviewImg,
    describe_job,
    submit_route_thumbnail,
    wait_route_thumbnail,
)

JOBS_FILE = "jobs.json"


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


def load_jobs(cache_dir):
    """{route_key: job} of the keystone.guru jobs earlier builds left queued."""
    path = os.path.join(cache_dir, JOBS_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_jobs(cache_dir, jobs):
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, JOBS_FILE), "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=1)


def job_alive(job):
    """keystone.guru keeps a job, and its result, until expiresAt."""
    expires = job.get("expiresAt")
    if job.get("status") not in ("queued", "completed") or not expires:
        return False
    return datetime.fromisoformat(expires.replace("Z", "+00:00")) > datetime.now(timezone.utc)


def fetch_thumbnail(dungeon_id, route_key, saved_job, deadline):
    """(image, job) for a route: resume the saved job, else submit a new one.
    A queued job is only waiting for the render queue, so it is never replaced."""
    if saved_job and job_alive(saved_job):
        print(f"[{route_key}] resuming saved {describe_job(saved_job)}, expires {saved_job.get('expiresAt')}")
        image, job = wait_route_thumbnail(route_key, saved_job, deadline)
        if image is not None or job.get("status") == "queued":
            return image, job
        print(f"[{route_key}] saved job ended {job.get('status')}, submitting a new one")
    elif saved_job:
        print(f"[{route_key}] saved {describe_job(saved_job)} expired at {saved_job.get('expiresAt')}, submitting a new one")
    job = submit_route_thumbnail(dungeon_id, route_key)
    if job is None:
        return None, None
    return wait_route_thumbnail(route_key, job, deadline)


def save_cached(dungeon_dir, route, image):
    os.makedirs(dungeon_dir, exist_ok=True)
    image.save(os.path.join(dungeon_dir, f"{route['route_key']}.png"))
    with open(os.path.join(dungeon_dir, f"{route['route_key']}.json"), "w", encoding="utf-8") as fh:
        json.dump({"route_key": route["route_key"], "specs": route.get("specs", [])}, fh)


def ranked_routes(top_routes):
    """The top route and the next-ranked one, its stand-in while the top route has no thumbnail."""
    routes = [r for r in top_routes if r.get("route_key")]
    return routes[:1] + [r for r in routes[1:] if r["route_key"] != routes[0]["route_key"]][:1]


def main(output_dir, cache_dir, budget_seconds):
    dungeon_lookup = load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))
    season = load_season_info(LOOKUP_DIR)["blizzard_season_id"]
    data = fetch_preview_data(season, list(dungeon_lookup))
    saved_jobs = load_jobs(cache_dir)
    print(f"{len(saved_jobs)} saved keystone.guru jobs: "
          + (", ".join(f"{k} ({describe_job(j)})" for k, j in saved_jobs.items()) or "none"))

    deadline = time.monotonic() + budget_seconds
    executor = ThreadPoolExecutor(max_workers=8)
    pending = {}
    for dungeon_id, rows in data.items():
        ranked = ranked_routes(rows["top_routes_data"])
        cached = cached_routes(os.path.join(cache_dir, str(dungeon_id)))
        if not ranked or ranked[0]["route_key"] in cached:
            continue
        print(f"dungeon {dungeon_id}: ranked {[r['route_key'] for r in ranked]}, cached {cached}")
        for route in ranked:
            if route["route_key"] not in cached:
                pending[(dungeon_id, route["route_key"])] = (route, executor.submit(
                    fetch_thumbnail, dungeon_id, route["route_key"],
                    saved_jobs.get(route["route_key"]), deadline))

    queued_jobs, fetched, job_notes = {}, set(), {}
    for (dungeon_id, route_key), (route, future) in pending.items():
        image, job = future.result()
        job_notes.setdefault(dungeon_id, []).append(f"{route_key}: {describe_job(job)}")
        if image is not None:
            save_cached(os.path.join(cache_dir, str(dungeon_id)), route, image)
            fetched.add(route_key)
        elif job and job.get("status") == "queued":
            queued_jobs[route_key] = job
    executor.shutdown(wait=False)
    save_jobs(cache_dir, queued_jobs)
    print(f"saved {len(queued_jobs)} queued jobs for the next build: {list(queued_jobs) or 'none'}")

    summary = []
    for dungeon_id, rows in data.items():
        ranked = [r["route_key"] for r in ranked_routes(rows["top_routes_data"])]
        route_key = ranked[0] if ranked else None
        dungeon_dir = os.path.join(cache_dir, str(dungeon_id))
        thumbnail, status = None, "no top route"
        if route_key:
            cached = cached_routes(dungeon_dir)
            shown = next((k for k in ranked + cached if k in cached), None)
            if shown == route_key:
                status = "fetched" if route_key in fetched else "cached"
            elif shown in ranked:
                status = f"top route not ready, #2 route {shown} shown"
            elif shown:
                status = f"top route not ready, previous route {shown} shown"
            else:
                status = "top route not ready, no map"
            if shown:
                thumbnail, route = load_cached(dungeon_dir, shown)
                rows["top_routes_data"] = [route]
            # keep the top route, the route shown now and one older as the next fallback
            keep = {k for k in (route_key, shown) if k in cached}
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
        summary.append((slug, route_key or "", status, "<br>".join(job_notes.get(dungeon_id, []))))
        print(f"{slug}: {status}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("| Dungeon | Top route | Thumbnail | keystone.guru jobs |\n|---|---|---|---|\n")
            for row in summary:
                fh.write("| " + " | ".join(row) + " |\n")


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
