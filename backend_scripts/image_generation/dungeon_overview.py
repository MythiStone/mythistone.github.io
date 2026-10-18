"""Renderer for the dungeon overview image (top comps + keystone.guru route
map) used for dungeon social posts and the dungeon pages' OG previews."""

import io
import os
import threading
import time

import requests
from PIL import Image, ImageDraw, ImageFont

import databaseConnector
from commonUtils import (
    find_dungeon_meta,
    format_comp_names,
    get_class_lookup,
    get_spec_lookup,
    humanize_number,
    sort_spec_ids_by_role,
)
from image_generation import config
from image_generation.pil_helpers import (
    LANCZOS,
    apply_watermark_to_canvas,
    dimmed_cover_bg,
    draw_header,
    draw_panel,
    paste_bordered_spec_icon,
    random_background_canvas,
    rounded_alpha,
)


# distinguishes "no thumbnail passed in, fetch it here" (default) from an
# explicitly passed pre-fetched result, which may legitimately be None (failed)
_THUMBNAIL_FETCH = object()

THUMBNAIL_POLL_INTERVAL = 10  # seconds between status polls
# Default wait for one route when no shared deadline is passed. A job sits
# "queued" until keystone.guru's shared render queue reaches it, and a failed
# render goes back to the end of that queue (up to 3 attempts, then "error").
THUMBNAIL_POLL_TIMEOUT = 25 * 60  # seconds
# keystone.guru validates these snake_case keys and silently drops any others.
THUMBNAIL_PAYLOAD = {
    "viewport_width": 900,
    "viewport_height": 600,
    "image_width": 900,
    "image_height": 600,
    "zoom_level": 2.2,
    "quality": 90,
}

_keystone_dungeons_lock = threading.Lock()
_keystone_dungeons_cache = None


def _get_keystone_dungeon_list(auth):
    """Fetch keystone.guru's dungeon list once per process (thread-safe); the
    list is static within a build and was previously re-fetched per dungeon."""
    global _keystone_dungeons_cache
    with _keystone_dungeons_lock:
        if _keystone_dungeons_cache is None:
            try:
                r = requests.get(
                    "https://keystone.guru/api/v1/dungeon", timeout=60, auth=auth
                )
                if r.status_code == 200:
                    _keystone_dungeons_cache = r.json().get("data", [])
                else:
                    print(
                        f"Failed to fetch dungeons from keystone.guru, "
                        f"status code: {r.status_code}"
                    )
                    _keystone_dungeons_cache = []
            except Exception as e:
                print(f"Error fetching dungeons from keystone.guru: {e}")
                _keystone_dungeons_cache = []
        return _keystone_dungeons_cache


def _keystone_auth():
    return requests.auth.HTTPBasicAuth(
        os.environ.get("KEYSTONE_GURU_USER", ""),
        os.environ.get("KEYSTONE_GURU_PW", ""),
    )


def describe_job(job):
    """One-line job state for logs and the build summary."""
    if not job:
        return "no job"
    text = f"job {job.get('id')} {job.get('status')}"
    if job.get("status") == "queued":
        text += f", queue {job.get('queueSize')}, eta {job.get('estimatedCompletion')}"
    return text


def submit_route_thumbnail(dungeon_id, route_key):
    """POST a thumbnail request and return the job of the floor we render, or None.

    keystone.guru creates a new job per floor on every POST (no dedup), so a
    caller that may outlive its wait should keep this job and poll it again
    instead of submitting anew. Combined-view dungeons use the highest floor
    (all floors combined), others the first.
    """
    dungeon_meta = find_dungeon_meta(dungeon_id) or {}
    name_text = dungeon_meta.get("name", {}).get("en_US", "")
    auth = _keystone_auth()

    combined_view_enabled = False
    for d in _get_keystone_dungeon_list(auth):
        d_name = d.get("name", "")
        d_key = d.get("key", d.get("slug", ""))
        if str(d.get("gameVersionId")) == str(dungeon_id) or str(d.get("id")) == str(dungeon_id) or d_name == name_text or d_key == dungeon_meta.get("slug"):
            combined_view_enabled = d.get("combinedViewEnabled", False)
            break

    url = f"https://keystone.guru/api/v1/route/{route_key}/thumbnail"
    try:
        r = requests.post(url, json=THUMBNAIL_PAYLOAD, timeout=60, auth=auth)
        if r.status_code != 200:
            print(f"Thumbnail request for route {route_key} failed, status code: {r.status_code}")
            return None
        jobs = r.json().get("data", [])
    except Exception as e:
        print(f"Error requesting thumbnail for route {route_key}: {e}")
        return None
    if not jobs:
        print(f"Thumbnail request for route {route_key} returned no jobs")
        return None
    pick = max if combined_view_enabled else min
    job = pick(jobs, key=lambda x: x.get("floorIndex", 0))
    print(f"Thumbnail requested for route {route_key} floor {job.get('floorIndex')}: {describe_job(job)}")
    return job


def wait_route_thumbnail(route_key, job, deadline=None):
    """Poll a thumbnail job until it leaves "queued" or the deadline passes.

    Returns (RGBA image or None, last known job). Only "queued" is worth
    waiting on; "error" and "expired" are final. `deadline` is a
    time.monotonic() value several jobs can share.
    """
    auth = _keystone_auth()
    if deadline is None:
        deadline = time.monotonic() + THUMBNAIL_POLL_TIMEOUT
    try:
        while job.get("status") == "queued" and time.monotonic() < deadline:
            time.sleep(THUMBNAIL_POLL_INTERVAL)
            poll_r = requests.get(job["links"]["status"], auth=auth, timeout=20)
            if poll_r.status_code == 404:
                # expired jobs are eventually deleted
                job = {**job, "status": "expired"}
            elif poll_r.status_code == 200:
                job = poll_r.json().get("data", job)

        if job.get("status") == "completed" and job.get("links", {}).get("result"):
            img_url = job["links"]["result"]
            img_r = requests.get(img_url, timeout=60)
            if img_r.status_code == 200:
                print(f"Thumbnail for route {route_key} fetched from {img_url}")
                return Image.open(io.BytesIO(img_r.content)).convert("RGBA"), job
            print(f"Getting image for {route_key} failed. Status: {img_r.status_code}")
            # the result link is gone, so the job is as good as expired
            return None, {**job, "status": "expired"}
    except Exception as e:
        print(f"Error polling thumbnail for route {route_key}: {e}")
        return None, job
    print(f"Thumbnail for route {route_key} not ready: {describe_job(job)}")
    return None, job


def fetch_route_thumbnail(dungeon_id, top_route_key, deadline=None):
    """Request, poll, and download the keystone.guru thumbnail for a route.

    Pure HTTP (no DB), so it can run in a background thread while the caller
    does per-dungeon DB work. Returns an RGBA PIL image, or None on any failure.
    """
    job = submit_route_thumbnail(dungeon_id, top_route_key)
    if job is None:
        return None
    return wait_route_thumbnail(top_route_key, job, deadline)[0]


def createDungeonOverviewImg(
    tmpdir,
    out_path,
    dungeon_id,
    season,
    conn=None,
    cursor=None,
    dungeon_totals=None,
    top_comps_data=None,
    per_level=None,
    top_routes_data=None,
    route_thumbnail=_THUMBNAIL_FETCH,
):
    """Render the dungeon overview image.

    The dungeon_totals / top_comps_data / per_level / top_routes_data keyword
    arguments accept data the caller already fetched for the dungeon page;
    anything left as None is fetched here, so standalone callers (social
    posts) keep working unchanged. `per_level` must already be filtered to
    this dungeon. `route_thumbnail` accepts a pre-fetched PIL image (or None
    for a failed pre-fetch); by default the thumbnail is fetched here.
    """
    spec_lookup = get_spec_lookup()
    class_lookup = get_class_lookup()
    WIDTH, HEIGHT = config.WIDTH, config.HEIGHT

    dungeon_meta = find_dungeon_meta(dungeon_id)
    if not dungeon_meta:
        print(f"Could not find dungeon meta for {dungeon_id}")
        return None

    name_text = dungeon_meta["name"]["en_US"]

    need_fetch = (
        dungeon_totals is None
        or top_comps_data is None
        or per_level is None
        or top_routes_data is None
    )
    if need_fetch:
        close_conn = False
        if conn is None or cursor is None:
            conn = databaseConnector.get_connection()
            cursor = conn.cursor(dictionary=True)
            close_conn = True

        try:
            # Fetch stats
            # Total Runs
            if dungeon_totals is None:
                dungeon_totals = databaseConnector.fetch_dungeon_totals(
                    conn, cursor, dungeon_id, season
                )

            # Top comps
            if top_comps_data is None:
                top_comps_data = databaseConnector.fetch_dungeon_top_comps(conn, cursor, dungeon_id, season)

            # Per-level rows for this dungeon (timed %, most-run key, highest key)
            if per_level is None:
                per_level = [
                    r for r in databaseConnector.fetch_runs_per_dungeon_per_level(conn, cursor, season)
                    if str(r.get("dungeon_id")) == str(dungeon_id)
                ]

            # Top routes
            if top_routes_data is None:
                top_routes_data = databaseConnector.fetch_dungeon_top_routes(conn, cursor, dungeon_id)
        finally:
            if close_conn:
                cursor.close()
                conn.close()

    tot = dungeon_totals
    play_count = 0
    if tot:
        val = list(tot[0].values())[0] if isinstance(tot[0], dict) else tot[0][0]
        play_count = int(val) if val else 0

    # canvas: dungeon art scaled to cover, random background as fallback
    dungeon_icon_path = None
    if dungeon_meta and "icon" in dungeon_meta:
        dungeon_icon_path = os.path.join(config.ICON_DIR, dungeon_meta["icon"])

    if dungeon_icon_path and os.path.exists(dungeon_icon_path):
        bg_img = Image.open(dungeon_icon_path)
        canvas = dimmed_cover_bg(bg_img, WIDTH, HEIGHT)
    else:
        canvas = random_background_canvas(WIDTH, HEIGHT, alpha=config.BG_ALPHA, base=config.BG)

    draw = ImageDraw.Draw(canvas, "RGBA")
    font_sm = ImageFont.truetype(config.FONT_FILE, config.SMALL_SIZE)

    draw_header(
        draw,
        name_text,
        f"{humanize_number(play_count)} total runs tracked",
        WIDTH,
        margin=50,
    )

    # quick stats block, right-aligned in the header zone
    timed_pct_str = highest_key = ""
    if per_level:
        timed = sum(int(r.get("upgrade_1", 0)) + int(r.get("upgrade_2", 0)) + int(r.get("upgrade_3", 0)) for r in per_level)
        total = sum(int(r.get("total_runs", 0)) for r in per_level)
        if total:
            timed_pct_str = f"{timed / total * 100:.0f}%"
        levels_run = [r for r in per_level if int(r.get("total_runs", 0)) > 0]
        if levels_run:
            highest_key = f"+{max(int(r['keystone_level']) for r in levels_run)}"
        stat_font = ImageFont.truetype(config.FONT_FILE, config.SMALL_SIZE + 4)
        stats = [(label, value) for label, value in (("Timed", timed_pct_str), ("Highest", highest_key)) if value]
        # bottom row sits on the header's subtitle line so the block reads as
        # part of the header instead of floating at the canvas edge
        for i, (label, value) in enumerate(stats):
            y = 124 - (len(stats) - 1 - i) * 42
            draw.text((WIDTH - 50, y), value, font=stat_font, fill=config.TEXT, anchor="ra")
            draw.text(
                (WIDTH - 50 - draw.textlength(value, font=stat_font) - 12, y),
                label.upper(), font=font_sm, fill=config.MUTED, anchor="ra",
            )

    # the route map's fixed geometry; the comps panel mirrors its vertical
    # extent so both blocks share top and bottom edges
    map_w, map_h = 600, 400
    map_x = WIDTH - map_w - 50
    map_y = 220

    pad = 20
    icon_sz = 48
    icon_gap = 5
    text_offset = 14

    comp_rows = []
    for r in top_comps_data[:5]:
        comp_str = r['comp'] if isinstance(r, dict) else r[0]
        comp_cnt = r['comp_count'] if isinstance(r, dict) else r[1]
        if not comp_str:
            continue
        spec_ids = sort_spec_ids_by_role(comp_str.split(','), spec_lookup)
        comp_rows.append((spec_ids, f"Runs: {humanize_number(int(comp_cnt))}"))

    # panel/content start at the header margin so they align with the divider
    panel_x1 = 50

    if comp_rows:
        # Measure Box Widths to wrap tightly like Spec Page panels
        top_comps_w = 0
        for spec_ids, runs_txt in comp_rows:
            r_box = draw.textbbox((0, 0), runs_txt, font=font_sm)
            icons_w = len(spec_ids) * icon_sz + (len(spec_ids) - 1) * icon_gap
            top_comps_w = max(top_comps_w, icons_w + text_offset + (r_box[2] - r_box[0]))
        box_pw = top_comps_w + (pad * 2)

        # heading above the panel, on the same line as the route map's label
        draw.text((panel_x1, map_y - 40), "Top Comps:", font=font_sm, fill=config.MUTED)
        draw_panel(draw, [(panel_x1, map_y), (panel_x1 + box_pw, map_y + map_h)], radius=15)

        # rows spread evenly over the panel's inner height
        avail_h = map_h - pad * 2
        for i, (spec_ids, runs_txt) in enumerate(comp_rows):
            row_cy = map_y + pad + (i + 0.5) * avail_h / len(comp_rows)
            x_offset = panel_x1 + pad
            for sid in spec_ids:
                paste_bordered_spec_icon(canvas, draw, sid, x_offset, int(row_cy - icon_sz / 2),
                                         icon_sz, spec_lookup, class_lookup)
                x_offset += icon_sz + icon_gap
            draw.text((x_offset - icon_gap + text_offset, row_cy), runs_txt,
                      font=font_sm, fill=config.TEXT, anchor="lm")

    # Top Route Image Integration
    if top_routes_data:
        top_route_key = top_routes_data[0]['route_key'] if isinstance(top_routes_data[0], dict) else top_routes_data[0][0]
        if not top_route_key:
            print("Top route key is missing or empty, cannot fetch thumbnail.")
        if top_route_key:
            if route_thumbnail is _THUMBNAIL_FETCH:
                print(f"Fetching thumbnail for top route: {top_route_key}")
                route_img = fetch_route_thumbnail(dungeon_id, top_route_key)
            else:
                route_img = route_thumbnail

            if route_img is not None:
                # Resize map to fix right side smoothly
                target_w = map_w
                target_h = int(target_w * (route_img.height / route_img.width))
                route_img = route_img.resize((target_w, target_h), LANCZOS)

                # Position on the right side
                img_x = map_x
                img_y = map_y

                # Add simple rounded mask using Pillow
                route_img = rounded_alpha(route_img, 15)

                # Paste map
                canvas.paste(route_img, (img_x, img_y), route_img)

                # Add label and route key
                draw.text(
                    (img_x, img_y - 40),
                    f"Top Route (keystone.guru/{top_route_key})",
                    font=font_sm,
                    fill=config.MUTED,
                )

                # Add team comp for this route
                if isinstance(top_routes_data[0], dict) and top_routes_data[0].get('specs'):
                    route_specs = top_routes_data[0]['specs']
                    if route_specs:
                        r_spec_ids = sort_spec_ids_by_role(
                            [str(s) for s in route_specs], spec_lookup
                        )
                        icon_w = 40
                        comp_x = img_x + target_w - (len(r_spec_ids) * (icon_w + 5))
                        comp_y = img_y - 45

                        for sid in r_spec_ids:
                            paste_bordered_spec_icon(canvas, draw, sid, int(comp_x), int(comp_y),
                                                     icon_w, spec_lookup, class_lookup)
                            comp_x += (icon_w + 5)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    canvas = apply_watermark_to_canvas(canvas, position="bottom_right", padding_x=30, padding_y=20)

    if out_path.lower().endswith((".jpg", ".jpeg")):
        canvas = canvas.convert("RGB")
    canvas.save(out_path)

    top_comp_str = ""
    if top_comps_data:
        first_comp = top_comps_data[0]
        comp_str = first_comp["comp"] if isinstance(first_comp, dict) else first_comp[0]
        top_comp_str = format_comp_names(comp_str)

    post_data = {
        "dungeon": name_text,
        "amount_data_source_runs": humanize_number(play_count),
        "timed_pct": timed_pct_str,
        "highest_key": highest_key,
        "top_comp": top_comp_str,
        "top_route": f"keystone.guru/{top_routes_data[0]['route_key'] if isinstance(top_routes_data[0], dict) else top_routes_data[0][0]}" if top_routes_data else "Unknown"
    }

    return {"out_path": out_path, "post_data": post_data}
