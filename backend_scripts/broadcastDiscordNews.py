"""Post the daily social post to every Discord channel subscribed via the bot's /news setup.

Runs in CI after generateSocialsPost.py. Needs DISCORD_BOT_TOKEN and DATABASE_*.
Channels the bot can no longer reach are unsubscribed. Any other failure is reported
after the loop and makes the script exit non-zero.
"""

import argparse
import json
import os
import sys
import time

import requests

import databaseConnector

API = "https://discord.com/api/v10"
SITE_BASE = "https://mythistone.com"
# Mirrors discord_bot.embeds.base_embed (brand colour, author, footer) so the post
# looks like every other bot reply. That module needs discord.py and the bot lookups.
BRAND_COLOR = 0x11151E
BRAND_NAME = "Mythistone"
BRAND_ICON = f"{SITE_BASE}/assets/img/favicon/web-app-manifest-192x192.png"
SUPPORT_FOOTER_TEXT = "Enjoying Mythistone? Support us on Patreon ❤"

# The channel, server or bot access is gone for good: drop the subscription.
GONE_CODES = {10003, 10004, 50001}
MISSING_PERMISSIONS = 50013
MAX_ATTEMPTS = 5
SEND_PAUSE_SECONDS = 0.5


def build_payload(post, image_name):
    for key in ("title", "social", "link"):
        if not post.get(key):
            raise ValueError(f"post.json is missing '{key}'")
    embed = {
        "title": post["title"][:256],
        "url": post["link"],
        "description": post["social"][:4096],
        "color": BRAND_COLOR,
        "image": {"url": f"attachment://{image_name}"},
        "author": {"name": BRAND_NAME, "url": SITE_BASE, "icon_url": BRAND_ICON},
        "footer": {"text": SUPPORT_FOOTER_TEXT, "icon_url": BRAND_ICON},
    }
    return {
        "embeds": [embed],
        "attachments": [{"id": 0, "filename": image_name}],
        "allowed_mentions": {"parse": []},
    }


def send(session, channel_id, payload, image_name, image_bytes):
    """POST one message. Returns the final response (retries rate limits)."""
    for _ in range(MAX_ATTEMPTS):
        resp = session.post(
            f"{API}/channels/{channel_id}/messages",
            data={"payload_json": json.dumps(payload)},
            files={"files[0]": (image_name, image_bytes, "image/png")},
            timeout=30,
        )
        if resp.status_code != 429:
            return resp
        time.sleep(float(resp.json().get("retry_after", 1)) + 0.1)
    return resp


def error_code(resp):
    try:
        return resp.json().get("code")
    except ValueError:
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--post-file", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--dry-run", action="store_true", help="print the payload, send nothing")
    args = p.parse_args()

    with open(args.post_file, "r", encoding="utf-8") as fh:
        post = json.load(fh)
    image_name = os.path.basename(args.image)
    with open(args.image, "rb") as fh:
        image_bytes = fh.read()
    payload = build_payload(post, image_name)

    databaseConnector.init_connection_pool(
        os.environ["DATABASE_HOST"],
        os.environ["DATABASE_USER"],
        os.environ["DATABASE_PASSWORD"],
        os.environ["DATABASE_NAME"],
        os.environ["DATABASE_PORT"],
        1,
    )
    conn = databaseConnector.get_live_connection()
    cursor = conn.cursor()
    try:
        subscriptions = databaseConnector.fetch_bot_news_channels(conn, cursor)
        print(f"{len(subscriptions)} subscribed channel(s)")

        if args.dry_run:
            print(json.dumps(payload, indent=2))
            for guild_id, channel_id in subscriptions:
                print(f"would post to channel {channel_id} (guild {guild_id})")
            return

        session = requests.Session()
        session.headers["Authorization"] = f"Bot {os.environ['DISCORD_BOT_TOKEN']}"
        sent, removed, failures = 0, 0, []
        for guild_id, channel_id in subscriptions:
            try:
                resp = send(session, channel_id, payload, image_name, image_bytes)
            except requests.RequestException as exc:
                failures.append(f"guild {guild_id} channel {channel_id}: {exc!r}")
                continue
            code = error_code(resp) if not resp.ok else None
            if resp.ok:
                sent += 1
            elif code in GONE_CODES:
                databaseConnector.delete_bot_news_channel(conn, cursor, guild_id)
                conn.commit()
                removed += 1
                print(f"unsubscribed guild {guild_id}: channel {channel_id} unreachable (code {code})")
            elif code == MISSING_PERMISSIONS:
                print(f"skipped guild {guild_id}: missing permissions in channel {channel_id}")
            else:
                failures.append(f"guild {guild_id} channel {channel_id}: HTTP {resp.status_code} {resp.text[:200]}")
            time.sleep(SEND_PAUSE_SECONDS)

        print(f"sent {sent}, unsubscribed {removed}, failed {len(failures)}")
        if failures:
            print("\n".join(failures), file=sys.stderr)
            sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
