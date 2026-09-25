"""Post selection, persistence and CLI entry point for the daily socials job.

main() owns the side effects that used to run at import time in the old
generateSocialsPost.py: the DB connection pool (skipped in --debug, which is
documented as DB-free) and creating the output directory.
"""

import argparse
import json
import os
import random
import time
from contextlib import closing
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont

import databaseConnector
import season_gate
from commonUtils import get_dungeon_lookup, get_spec_lookup, load_json, load_season_info
from image_generation import config
from image_generation.pil_helpers import apply_watermark_to_canvas
from image_generation.season_countdown import in_launch_window
from social_posts.context import load_season_context
from social_posts.links import build_site_link
from social_posts.snapshot import (
    find_baseline,
    find_movers,
    load_snapshots,
    record_snapshot,
    save_snapshots,
    snapshot_from_context,
)
from social_posts.voice import recent_records
from social_posts.posts import (
    createCompOverview,
    createDungeonOverview,
    createSpecOverview,
    create_MplusRun,
    create_dungeon_popularity_vs_ease,
    create_dungeon_tierlist,
    create_overall_spec_popularity,
    create_season_countdown,
    create_season_launch,
    create_spec_popularity_by_level,
    create_spec_popularity_vs_performance,
    create_underdog_spotlight,
    create_weekly_mover,
)

# Default location of the text records. In CI this is overridden with
# --socials-file so the records live alongside the images on the social-images
# branch (see .github/workflows/automatedSocialMediaPosts.yml); the local default
# keeps debug/test posts self-contained in the repo.
SOCIALS_FILE = os.path.join("data", "socials.json")
POST_FILE = os.path.join(config.OUTPUT_DIR, "post.json")
# Weekly standings snapshots for the weekly-mover post; CI overrides it with
# --snapshot-file so it lives on the social-images branch next to socials.json.
SNAPSHOT_FILE = os.path.join("data", "social_snapshot.json")

RUN_TYPES = ("highest_run", "longest_run", "shortest_run")
# Relative pick weight per post group. All spec overviews share one slot (and
# all dungeon overviews another), so the one-generator-per-spec fan-out no
# longer drowns out every other post type.
GROUP_WEIGHTS = {
    "spec_overview": 25,
    "dungeon_overview": 15,
    "runs": 15,
    "comp_overview": 10,
    "underdog_spotlight": 10,
    "dungeon_tierlist": 8,
    "spec_popularity_tierlist": 8,
    "spec_popularity_vs_performance": 7,
    "dungeon_popularity_by_level": 6,
    "spec_distribution_by_level": 6,
    # only offered when snapshot.find_movers found a big move, so boosted
    "weekly_mover": 30,
}
GROUP_POST_TYPES = {"runs": set(RUN_TYPES)}
MAX_SPEC_OVERVIEWS_PER_WEEK = 2
WEEKLY_MOVER_COOLDOWN_DAYS = 6
UNDERDOG_COOLDOWN_DAYS = 7


def _posts_since(donesocials, post_type, days):
    cutoff = (time.time() - days * 86400) * 1000
    return sum(
        1 for r in donesocials.values()
        if isinstance(r, dict) and r.get("post_type") == post_type and r.get("timestamp", 0) >= cutoff
    )


def blocked_groups(donesocials):
    """Groups the anti-repeat rules keep out today: whatever posted last, spec
    overviews past their weekly cap, and cooled-down one-offs."""
    blocked = set()
    last = recent_records(donesocials, limit=1)
    if last and last[0].get("post_type"):
        last_type = last[0]["post_type"]
        blocked |= {g for g, types in GROUP_POST_TYPES.items() if last_type in types}
        blocked.add(last_type)
    if _posts_since(donesocials, "spec_overview", 7) >= MAX_SPEC_OVERVIEWS_PER_WEEK:
        blocked.add("spec_overview")
    if _posts_since(donesocials, "underdog_spotlight", UNDERDOG_COOLDOWN_DAYS):
        blocked.add("underdog_spotlight")
    return blocked


def select_post(groups, donesocials, rng=random):
    """Weighted pick over {group: [generator, ...]} until one yields a new post.

    Groups blocked by the anti-repeat rules are skipped unless nothing else is
    left, in which case every group is tried again as a last resort."""
    blocked = blocked_groups(donesocials)
    allowed = {g: list(gens) for g, gens in groups.items() if gens and g not in blocked}
    fallback = {g: list(gens) for g, gens in groups.items() if gens and g in blocked}
    for pool in (allowed, fallback):
        while pool:
            names = list(pool)
            group = rng.choices(names, weights=[GROUP_WEIGHTS.get(g, 1) for g in names], k=1)[0]
            gens = pool[group]
            gen = gens.pop(rng.randrange(len(gens)))
            if not gens:
                del pool[group]
            post = gen()
            if post and post.get("bundle") and post.get("out_path") not in donesocials:
                return post
    return None


def create_socials_post(donesocials, api_key, url, snapshots=None):
    """
    Picks one post type by group weight (GROUP_WEIGHTS) under the anti-repeat
    rules, skipping posts already done. ``snapshots`` (the weekly standings list)
    gets today's snapshot appended and feeds the weekly-mover check.
    """
    print("Generating social media post...")

    spec_lookup = get_spec_lookup()
    dungeon_lookup = get_dungeon_lookup()

    # Prepare spec IDs for spec overview
    specs = [f for f in spec_lookup.keys()]

    # Prepare dungeon IDs for dungeon overview
    dungeons = []
    if isinstance(dungeon_lookup, dict):
        dungeons = [d.get("id", k) for k, d in dungeon_lookup.items()]
    elif isinstance(dungeon_lookup, list):
        dungeons = [d.get("id") for d in dungeon_lookup]

    season_info = load_season_info()
    current_season_id = int(season_info["blizzard_season_id"])

    # Launch-day gate: for the first 24h after the earliest regional start, at
    # least one region is live but the season is so fresh that the normal data
    # generators would error or render near-empty cards (barely any runs yet, and
    # the later regions have not even started). Post a "season has started"
    # announcement naming the live regions and how long until the rest instead.
    # Pure time + seasonInfo (no DB), so it runs before the DB gate below.
    if in_launch_window(season_info):
        print("Launch day: posting 'season has started' announcement instead of data.")
        post = create_season_launch(config.OUTPUT_DIR, donesocials, url, season_info)
        if post and post.get("bundle"):
            out_path = post["out_path"]
            if out_path not in donesocials:
                record = bundle_to_record(post)
                donesocials[out_path] = record
                return {"out_path": out_path, **record}
        # Announcement for today already recorded (or unbuildable): nothing new.
        # Do NOT fall through to the data generators, which are not ready today.
        return None

    # Pre-season gate: during the gap between seasons (DB wiped, no runs logged
    # for the current season yet) every normal generator would render an empty
    # "0 total runs tracked" card. Detect that the same way the Discord bot's
    # season-not-started guard does (season_gate) and post a release countdown
    # instead. Once the first keys are logged this flips back automatically.
    with closing(databaseConnector.get_connection()) as conn:
        cursor = conn.cursor()
        try:
            started = season_gate.season_has_started(conn, cursor, current_season_id)
        finally:
            cursor.close()
    if not started:
        print("Season has no runs yet: posting release countdown instead of data.")
        post = create_season_countdown(
            config.OUTPUT_DIR, donesocials, url, season_info
        )
        if post and post.get("bundle"):
            out_path = post["out_path"]
            if out_path not in donesocials:
                record = bundle_to_record(post)
                donesocials[out_path] = record
                return {"out_path": out_path, **record}
        # Countdown for today already recorded (or unbuildable): nothing new to post.
        return None

    ctx = load_season_context(current_season_id)
    movers = []
    if snapshots is not None:
        today = date.today()
        baseline = find_baseline(snapshots, current_season_id, today)
        movers = find_movers(baseline, ctx) if baseline else []
        record_snapshot(snapshots, snapshot_from_context(ctx, current_season_id, today), today)

    def spec_gen(sid):
        return lambda: createSpecOverview(
            config.OUTPUT_DIR, donesocials, api_key, url, sid, current_season_id
        )

    def dungeon_gen(did):
        return lambda: createDungeonOverview(
            config.OUTPUT_DIR, donesocials, api_key, url, did, current_season_id
        )

    def run_gen(run_type):
        return lambda: create_MplusRun(run_type, current_season_id, donesocials, api_key, url)

    def season_gen(fn):
        return lambda: fn(config.OUTPUT_DIR, donesocials, api_key, url, current_season_id)

    groups = {
        "spec_overview": [spec_gen(sid) for sid in specs or ["62"]],
        "dungeon_overview": [dungeon_gen(did) for did in dungeons],
        "runs": [run_gen(rt) for rt in RUN_TYPES],
        "comp_overview": [season_gen(createCompOverview)],
        "underdog_spotlight": [season_gen(create_underdog_spotlight)],
        "dungeon_tierlist": [season_gen(create_dungeon_tierlist)],
        "spec_popularity_tierlist": [season_gen(create_overall_spec_popularity)],
        "spec_popularity_vs_performance": [season_gen(create_spec_popularity_vs_performance)],
        "dungeon_popularity_by_level": [season_gen(create_dungeon_popularity_vs_ease)],
        "spec_distribution_by_level": [season_gen(create_spec_popularity_by_level)],
    }
    if movers and not _posts_since(donesocials, "weekly_mover", WEEKLY_MOVER_COOLDOWN_DAYS):
        print(f"Weekly mover eligible: {movers[0]['name']} {movers[0]['changes']}")
        groups["weekly_mover"] = [
            lambda: create_weekly_mover(
                config.OUTPUT_DIR, donesocials, api_key, url, current_season_id, movers[0]
            )
        ]

    post = select_post(groups, donesocials)
    if not post:
        # All options exhausted
        return None
    record = bundle_to_record(post)
    donesocials[post["out_path"]] = record
    return {"out_path": post["out_path"], **record}


def bundle_to_record(post):
    """Flatten a generator result into the record stored in socials.json."""
    bundle = post["bundle"]
    social = bundle["social"]
    return {
        "title": bundle["title"],
        "post_type": post.get("post_type", ""),
        "link": post.get("link", ""),
        # one humorous text used across every social platform
        "social": social,
        "blog": bundle["blog"],
        # legacy field kept so the workflow (and older consumers) keep working
        "post": social,
        "persona": bundle.get("persona", ""),
        "judge_score": bundle.get("judge_score"),
        "timestamp": int(time.time() * 1000),
    }


def create_debug_post(url):
    """Offline test post: no database, no Blizzard API, no OpenRouter.

    Renders a synthetic image and a canned text bundle so the whole
    socials.json -> blog page pipeline can be exercised locally.
    """
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    out_path = os.path.join(
        config.OUTPUT_DIR, f"debug_test_{now.strftime('%Y-%m-%d_%H-%M-%S')}.png"
    )

    canvas = Image.new("RGB", (config.WIDTH, config.HEIGHT), "#222222")
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.truetype(config.FONT_FILE, config.TITLE_SIZE)
    small_font = ImageFont.truetype(config.FONT_FILE, config.SMALL_SIZE)
    draw.text(
        (config.WIDTH // 2, config.HEIGHT // 2 - 60),
        "Blog Display Test",
        font=title_font,
        fill=(255, 255, 255),
        anchor="mm",
    )
    draw.text(
        (config.WIDTH // 2, config.HEIGHT // 2 + 40),
        f"generated {stamp}",
        font=small_font,
        fill=(200, 200, 200),
        anchor="mm",
    )
    canvas = apply_watermark_to_canvas(
        canvas, position="top_right", padding_x=30, padding_y=30
    )
    canvas.save(out_path, format="PNG")

    link = build_site_link(url, "pages/dashboard")
    bundle = {
        "title": f"Debug post from {stamp}",
        "social": f"[DEBUG] Blog display test generated {stamp}. #WoW #MythicPlus {link}",
        "blog": (
            f"This is a debug post generated locally at {stamp} to verify that "
            "images and text render correctly on the blog page.\n\n"
            "If you can read this on the blog with the image above, the "
            "socials.json record, the image pipeline and the card layout all "
            "work. Delete this entry from data/socials.json (and the PNG from "
            "data/social) when you are done."
        ),
    }
    return {
        "out_path": out_path,
        "bundle": bundle,
        "post_type": "debug_test",
        "link": link,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api-key")
    p.add_argument("--url", default="https://mythistone.com/")
    p.add_argument(
        "--debug",
        action="store_true",
        help="generate an offline test post (no DB, no Blizzard API, no OpenRouter) to preview on the blog page",
    )
    p.add_argument(
        "--socials-file",
        default=SOCIALS_FILE,
        help="path to the socials.json text records to read and update "
        "(CI points this at the social-images branch checkout)",
    )
    p.add_argument(
        "--snapshot-file",
        default=SNAPSHOT_FILE,
        help="path to the weekly standings snapshots used for the weekly-mover post "
        "(CI points this at the social-images branch checkout)",
    )
    args = p.parse_args()
    if not args.debug and not args.api_key:
        p.error("--api-key is required unless --debug is set")

    # Side effects that used to run at import time: the pool is only needed by
    # the real pipeline (--debug is documented as database-free).
    if not args.debug:
        databaseConnector.init_connection_pool(
            os.environ.get("DATABASE_HOST"),
            os.environ.get("DATABASE_USER"),
            os.environ.get("DATABASE_PASSWORD"),
            os.environ.get("DATABASE_NAME"),
            os.environ.get("DATABASE_PORT"),
            2,
        )
    config.ensure_output_dir()

    socials_file = args.socials_file
    if os.path.exists(socials_file):
        donesocials = load_json(socials_file)
    else:
        donesocials = {}
    if args.debug:
        result = create_debug_post(args.url)
        record = bundle_to_record(result)
        donesocials[result["out_path"]] = record
        post = {"out_path": result["out_path"], **record}
        print("DEBUG: offline test post created; do NOT commit this socials.json entry")
    else:
        snapshots = load_snapshots(args.snapshot_file)
        post = create_socials_post(donesocials, args.api_key, args.url, snapshots)
        save_snapshots(args.snapshot_file, snapshots)
    print(f"Generated post: {post}")
    os.makedirs(os.path.dirname(socials_file) or ".", exist_ok=True)
    with open(socials_file, "w") as f:
        json.dump(donesocials, f, indent=4)
    with open(POST_FILE, "w") as f:
        json.dump(post, f, indent=4)


if __name__ == "__main__":
    main()
