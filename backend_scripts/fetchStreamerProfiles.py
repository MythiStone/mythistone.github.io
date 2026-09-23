"""Enrich streamer candidates (commonUtils.MIN_STREAMER_VODS+ POV videos) with the
Twitch/YouTube channel behind each video and the raider.io profile of each POV
character, caching everything in the DB so the VOD generator stays credential-free.

Needs DATABASE_*, RAIDERIO_API_KEY, TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET and
YOUTUBE_API_KEY. A video or character the platform no longer knows is data (stored
as 'gone' / skipped), any other API failure raises.
"""
import os
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

import databaseConnector
from commonUtils import MIN_STREAMER_VODS

TWITCH_API = "https://api.twitch.tv/helix"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
RAIDERIO_PROFILE_URL = "https://raider.io/api/v1/characters/profile"
RAIDERIO_PROFILE_FIELDS = ",".join([
    "mythic_plus_scores_by_season:current",
    "mythic_plus_ranks",
    "mythic_plus_best_runs",
    "mythic_plus_recent_runs",
    "mythic_plus_dungeon_run_counts",
    "gear",
    "talents",
])
# raider.io gear slot -> the armory slot names loadout-view.js lays out. Shirt and
# tabard are dropped.
GEAR_SLOTS = {
    "head": "HEAD", "neck": "NECK", "shoulder": "SHOULDER", "back": "BACK",
    "chest": "CHEST", "wrist": "WRIST", "hands": "HANDS", "waist": "WAIST",
    "legs": "LEGS", "feet": "FEET", "finger1": "FINGER_1", "finger2": "FINGER_2",
    "trinket1": "TRINKET_1", "trinket2": "TRINKET_2",
    "mainhand": "MAIN_HAND", "offhand": "OFF_HAND",
}
CHANNEL_MAX_AGE_DAYS = 7
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 6
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Minimum seconds between two requests to the same host. raider.io gets one call per
# character, so it is paced well below its per-minute limit. Twitch and YouTube are
# batched 50-100 ids per call and barely need it.
MIN_INTERVAL = {"raider.io": 0.35, "api.twitch.tv": 0.1, "www.googleapis.com": 0.1}
_last_call = {}


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _throttle(url):
    host = urlparse(url).hostname
    wait = MIN_INTERVAL.get(host, 0.1) - (time.monotonic() - _last_call.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.monotonic()


def _backoff(attempt, resp=None):
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    try:
        delay = float(retry_after)
    except (TypeError, ValueError):
        delay = 2 ** (attempt + 1)
    time.sleep(min(delay, 60))


def get_json(url, params=None, headers=None, not_found=(404,)):
    """Throttled GET that retries rate limits, 5xx and network errors with backoff.
    Returns None for a `not_found` status and raises once the retries run out."""
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        _throttle(url)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout):
            if last:
                raise
            _backoff(attempt)
            continue
        if resp.status_code in not_found:
            return None
        if resp.status_code in RETRY_STATUSES and not last:
            print(f"  {resp.status_code} from {urlparse(url).hostname}, retrying")
            _backoff(attempt, resp)
            continue
        resp.raise_for_status()
        return resp.json()


# --- Twitch ----------------------------------------------------------------

def twitch_headers():
    client_id = require_env("TWITCH_CLIENT_ID")
    resp = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": require_env("TWITCH_CLIENT_SECRET"),
            "grant_type": "client_credentials",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return {"Client-Id": client_id, "Authorization": f"Bearer {resp.json()['access_token']}"}


def twitch_video_owners(refs, headers):
    """{video_ref: user_id}. Helix 404s a request when none of its ids exist, so a
    404 batch is retried id by id to tell a dead id from a dead batch."""
    owners = {}
    for batch in chunks(refs, 100):
        data = get_json(f"{TWITCH_API}/videos", [("id", r) for r in batch], headers)
        if data is None and len(batch) > 1:
            for ref in batch:
                single = get_json(f"{TWITCH_API}/videos", [("id", ref)], headers)
                for v in (single or {}).get("data", []):
                    owners[v["id"]] = v["user_id"]
            continue
        for v in (data or {}).get("data", []):
            owners[v["id"]] = v["user_id"]
    return owners


def twitch_channels(user_ids, headers):
    rows = []
    for batch in chunks(user_ids, 100):
        data = get_json(f"{TWITCH_API}/users", [("id", u) for u in batch], headers)
        for u in (data or {}).get("data", []):
            rows.append(("twitch", u["id"], u.get("login"), u.get("display_name"),
                         u.get("profile_image_url"), u.get("description")))
    return rows


# --- YouTube ---------------------------------------------------------------

def youtube_video_owners(refs, api_key):
    owners = {}
    for batch in chunks(refs, 50):
        data = get_json(f"{YOUTUBE_API}/videos",
                        {"part": "snippet", "id": ",".join(batch), "key": api_key})
        for v in data.get("items", []):
            owners[v["id"]] = v["snippet"]["channelId"]
    return owners


def youtube_channels(channel_ids, api_key):
    rows = []
    for batch in chunks(channel_ids, 50):
        data = get_json(f"{YOUTUBE_API}/channels",
                        {"part": "snippet", "id": ",".join(batch), "key": api_key})
        for c in data.get("items", []):
            sn = c["snippet"]
            thumbs = sn.get("thumbnails") or {}
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
            rows.append(("youtube", c["id"], sn.get("customUrl"), sn.get("title"),
                         thumb, sn.get("description")))
    return rows


# --- raider.io -------------------------------------------------------------

def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def _trim_run(r):
    return {
        "cmid": r.get("map_challenge_mode_id"),
        "dungeon": r.get("dungeon"),
        "short_name": r.get("short_name"),
        "level": r.get("mythic_level"),
        "clear_ms": r.get("clear_time_ms"),
        "par_ms": r.get("par_time_ms"),
        "upgrades": r.get("num_keystone_upgrades") or 0,
        "score": r.get("score"),
        "url": r.get("url"),
        "completed_at": _epoch(r.get("completed_at")),
        "spec_id": (r.get("spec") or {}).get("id"),
    }


def world_ranks(ranks):
    """World ranks only (raider.io 0 = unranked): overall, class, and every spec the
    character is ranked in, since a player can rank in more than one spec."""
    def world(r):
        return (r or {}).get("world") or None
    return {
        "overall": world(ranks.get("overall")),
        "class": world(ranks.get("class")),
        "specs": {key[len("spec_"):]: world(r) for key, r in ranks.items()
                  if key.startswith("spec_") and world(r)},
    }


def build_details(data):
    """The slice of a raider.io profile the streamer page renders, kept small because
    it is stored per character in pov_character_profiles.details."""
    talents = data.get("talentLoadout") or {}
    spec_id = talents.get("loadout_spec_id")
    items = (data.get("gear") or {}).get("items") or {}
    slots = {}
    for rio_slot, slot in GEAR_SLOTS.items():
        it = items.get(rio_slot)
        if not it or not it.get("item_id"):
            continue
        slots[slot] = {
            "id": it["item_id"],
            "name": it.get("name"),
            "icon": it.get("icon"),
            "quality": it.get("item_quality"),
            "item_level": it.get("item_level"),
            "bonus": it.get("bonuses") or [],
            "enchant": it.get("enchant"),
            "gems": it.get("gems") or [],
        }
    return {
        "spec_id": spec_id,
        "role": data.get("active_spec_role"),
        "ilvl": (data.get("gear") or {}).get("item_level_equipped"),
        "world_ranks": world_ranks(data.get("mythic_plus_ranks") or {}),
        "best_runs": [_trim_run(r) for r in data.get("mythic_plus_best_runs") or []],
        "recent_runs": [_trim_run(r) for r in data.get("mythic_plus_recent_runs") or []],
        "run_counts": [
            {"short_name": c.get("short_name"), "dungeon": c.get("dungeon"),
             "total": c.get("season_runs_total") or 0, "timed": c.get("season_runs_timed") or 0}
            for c in data.get("mythic_plus_dungeon_run_counts") or []
        ],
        "talents": talents.get("loadout_text"),
        "slots": slots,
    }


def raiderio_profile(char_id, char, api_key):
    data = get_json(
        RAIDERIO_PROFILE_URL,
        {
            "region": char["region"],
            "realm": char["realm_slug"],
            "name": char["name"],
            "fields": RAIDERIO_PROFILE_FIELDS,
            "access_key": api_key,
        },
        not_found=(400, 404),  # raider.io answers 400 for an unknown character
    )
    if data is None:
        return None
    seasons = data.get("mythic_plus_scores_by_season") or []
    score = ((seasons[0].get("scores") or {}).get("all")) if seasons else None
    return (char_id, char["region"], char["realm_slug"], data.get("name") or char["name"],
            data.get("class"), data.get("active_spec_name"), score,
            data.get("thumbnail_url"), data.get("profile_url"), build_details(data))


def main():
    rio_key = require_env("RAIDERIO_API_KEY")
    yt_key = require_env("YOUTUBE_API_KEY")
    t_headers = twitch_headers()

    databaseConnector.init_connection_pool(
        require_env("DATABASE_HOST"),
        require_env("DATABASE_USER"),
        require_env("DATABASE_PASSWORD"),
        os.environ.get("DATABASE_NAME"),
        os.environ.get("DATABASE_PORT"),
        1,
    )
    conn = databaseConnector.get_connection()
    cursor = conn.cursor()
    try:
        candidates = databaseConnector.fetch_streamer_candidates(conn, cursor, MIN_STREAMER_VODS)
        print(f"{len(candidates)} streamer candidate(s) with >= {MIN_STREAMER_VODS} VODs")

        # 1. Channel behind each not-yet-resolved video.
        resolved = databaseConnector.fetch_video_channels(conn, cursor)
        pending = {"twitch": set(), "youtube": set()}
        for cand in candidates.values():
            for vtype, vref in cand["videos"]:
                if vtype in pending and (vtype, vref) not in resolved:
                    pending[vtype].add(vref)
        owners = {
            "twitch": twitch_video_owners(sorted(pending["twitch"]), t_headers),
            "youtube": youtube_video_owners(sorted(pending["youtube"]), yt_key),
        }
        video_rows = [
            (vtype, ref, owners[vtype].get(ref), "ok" if ref in owners[vtype] else "gone")
            for vtype, refs in pending.items() for ref in refs
        ]
        databaseConnector.upsert_video_channels(conn, cursor, video_rows)
        conn.commit()
        print(f"Resolved {len(video_rows)} video(s), "
              f"{sum(1 for r in video_rows if r[3] == 'gone')} gone")

        # 2. Channel profiles that are missing or stale.
        resolved = databaseConnector.fetch_video_channels(conn, cursor)
        fresh = databaseConnector.fetch_fresh_streamer_channel_ids(
            conn, cursor, CHANNEL_MAX_AGE_DAYS)
        wanted = {"twitch": set(), "youtube": set()}
        for cand in candidates.values():
            for vtype, vref in cand["videos"]:
                channel_id, status = resolved.get((vtype, vref), (None, None))
                if status == "ok" and vtype in wanted and (vtype, channel_id) not in fresh:
                    wanted[vtype].add(channel_id)
        channel_rows = (twitch_channels(sorted(wanted["twitch"]), t_headers)
                        + youtube_channels(sorted(wanted["youtube"]), yt_key))
        databaseConnector.upsert_streamer_channels(conn, cursor, channel_rows)
        conn.commit()
        print(f"Refreshed {len(channel_rows)} channel profile(s)")

        # 3. raider.io profile of every candidate character (scores move daily).
        profile_rows, missing = [], 0
        for cand in candidates.values():
            for char_id, char in cand["characters"].items():
                if not (char["region"] and char["realm_slug"] and char["name"]):
                    continue
                row = raiderio_profile(char_id, char, rio_key)
                if row is None:
                    missing += 1
                else:
                    profile_rows.append(row)
        databaseConnector.upsert_pov_character_profiles(conn, cursor, profile_rows)
        conn.commit()
        print(f"Stored {len(profile_rows)} raider.io profile(s), {missing} not found")
    finally:
        cursor.close()
        databaseConnector.close_quietly(conn)


if __name__ == "__main__":
    main()
