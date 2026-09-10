"""Collect the latest official WoW hotfix notes per current-season dungeon.

Credential-free static-data collector (no DB, no secrets). It scrapes Blizzard's
official hotfix notes and writes ``data/static/hotfixes.json``, which the dungeon
page generator reads directly (same model as ``patches.json``).

Why scraping: there is no structured API for hotfix *narrative* text (wago.tools
only exposes raw DB2 data-table diffs, not readable dungeon notes). Discovery is
still JSON-clean, though: the news landing page links every hotfix article by a
dated slug, so we never hardcode an article id. The article body itself is
server-rendered HTML parsed with BeautifulSoup.

Source structure (worldofwarcraft.blizzard.com hotfix living-document):
- ``div.detail`` holds the whole article. Its children are, in document order, a
  date paragraph (text like "September 9, 2026"), then repeating
  ``<p><strong>Category</strong></p>`` headers each followed by a sibling ``<ul>``.
- Under the "Dungeons and Raids" category, each top-level ``<li>`` leads with a
  ``<strong>`` dungeon/raid name and carries a nested ``<ul>`` of bullets; a bullet
  may itself be a ``<li><strong>Boss</strong><ul>...</ul></li>`` subsection.
- Dungeon names match ``data/static/dungeons.json`` ``name.en_US`` verbatim, so we
  match by name and keep only the current-season dungeons (per-dungeon only: raids
  and general Mythic+/system entries are ignored).

Fails loudly (per repo policy): every HTTP call raises on error, discovery raises
if no hotfix article is found, and parsing raises if the "Dungeons and Raids"
section is never located (a markup change surfaces as a failed run, not silently
empty pages). A dungeon legitimately having no hotfixes is a normal empty list.
"""

import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mythistone-static-collector"
SITE_BASE = "https://worldofwarcraft.blizzard.com/en-us"
NEWS_LANDING_URL = f"{SITE_BASE}/news"

DUNGEONS_JSON = os.path.join("data", "static", "dungeons.json")
HOTFIXES_JSON = os.path.join("data", "static", "hotfixes.json")

# Keep at most this many dated entries per dungeon (newest first).
PER_DUNGEON_LIMIT = 8

# Category header that groups per-instance hotfixes. Matched as a prefix because
# the source occasionally renders it as "Dungeons and Raid" (a stray split node).
DUNGEONS_CATEGORY_PREFIX = "dungeons and raid"

_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()
_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b"
)
# Hotfix article links on the landing page, e.g. /news/24296142/hotfixes-september-9-2026
_HOTFIX_HREF_RE = re.compile(r'href="(/news/\d+/hotfixes[a-z0-9-]*)"', re.I)


def _http_get(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.text


def _normalize_name(text):
    """Lowercase, straighten curly apostrophes, collapse whitespace for matching."""
    return re.sub(r"\s+", " ", text.replace("’", "'").strip()).casefold()


def _parse_date(text):
    """Return (epoch_ms_utc_midnight, canonical_text) for a date string, or None."""
    m = _DATE_RE.search(text)
    if not m:
        return None
    month, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    dt = datetime(year, _MONTHS.index(month) + 1, day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000), f"{month} {day}, {year}"


def load_dungeon_name_map(path=DUNGEONS_JSON):
    """Map normalized en_US dungeon name -> challenge_mode_id (str) for the
    current-season dungeons in ``dungeons.json``."""
    with open(path, "r", encoding="utf-8") as f:
        dungeons = json.load(f)
    name_to_id = {}
    for cm_id, data in dungeons.items():
        name = data.get("name", {}).get("en_US")
        if name:
            name_to_id[_normalize_name(name)] = str(cm_id)
    if not name_to_id:
        raise RuntimeError(f"No dungeon names found in {path}")
    return name_to_id


def discover_latest_article_url(landing_html):
    """Pick the newest hotfix article URL from the news landing page (by the date
    embedded in each hotfix slug). Raises if none are present."""
    candidates = {}  # absolute_url -> date_ms
    for href in _HOTFIX_HREF_RE.findall(landing_html):
        parsed = _parse_date(href.replace("-", " "))
        candidates[f"{SITE_BASE}{href}"] = parsed[0] if parsed else -1
    if not candidates:
        raise RuntimeError(
            "No hotfix article link found on the news landing page "
            f"({NEWS_LANDING_URL}); the page structure may have changed."
        )
    return max(candidates, key=candidates.get)


def _extract_bullets(dungeon_li):
    """Flatten a matched dungeon <li>'s nested bullet list into note strings.
    Boss subsections (nested <ul> under a <strong>) become "Boss: bullet"."""
    inner = dungeon_li.find("ul")
    if inner is None:
        return []
    notes = []
    for li in inner.find_all("li", recursive=False):
        sub = li.find("ul")
        if sub is not None:
            # Boss/encounter subsection: <strong>Boss</strong> then leaf bullets.
            strong = li.find("strong")
            boss = strong.get_text(" ", strip=True) if strong else ""
            for leaf in sub.find_all("li", recursive=False):
                text = leaf.get_text(" ", strip=True)
                if text:
                    notes.append(f"{boss}: {text}" if boss else text)
        else:
            text = li.get_text(" ", strip=True)
            if text:
                notes.append(text)
    return notes


def parse_hotfixes(html, name_to_id):
    """Parse an article's HTML into {challenge_mode_id: [ {date_ts, date_text,
    notes:[...]}, ... ]} (newest first, capped to PER_DUNGEON_LIMIT).

    Raises if the "Dungeons and Raids" category is never found (markup change)."""
    soup = BeautifulSoup(html, "html.parser")
    detail = soup.find("div", class_="detail")
    if detail is None:
        raise RuntimeError("Hotfix article has no <div class='detail'> content container.")

    # dungeon id -> { date_ms: {"date_text": str, "notes": [...]} }
    by_dungeon = {}
    current_date = None
    saw_dungeons_category = False

    for child in detail.children:
        if getattr(child, "name", None) is None:
            continue
        text = child.get_text(" ", strip=True)
        if not text:
            continue

        if child.name == "p":
            date = _parse_date(text)
            # A paragraph whose whole text IS the date is a section boundary. The
            # exact-match guard avoids mistaking a body paragraph that merely
            # mentions a date for one.
            if date and text.strip().rstrip(".") == date[1]:
                current_date = date
                continue
            strong = child.find("strong")
            if strong and strong.get_text(" ", strip=True).casefold().startswith(
                DUNGEONS_CATEGORY_PREFIX
            ):
                saw_dungeons_category = True
                ul = child.find_next_sibling("ul")
                if ul is None or current_date is None:
                    continue
                date_ms, date_text = current_date
                for li in ul.find_all("li", recursive=False):
                    strong_name = li.find("strong")
                    if strong_name is None:
                        continue
                    key = _normalize_name(strong_name.get_text(" ", strip=True))
                    cm_id = name_to_id.get(key)
                    if cm_id is None:
                        continue  # raid or non-season dungeon: ignored
                    notes = _extract_bullets(li)
                    if not notes:
                        continue
                    entries = by_dungeon.setdefault(cm_id, {})
                    entry = entries.setdefault(
                        date_ms, {"date_text": date_text, "notes": []}
                    )
                    entry["notes"].extend(notes)

    if not saw_dungeons_category:
        raise RuntimeError(
            "No 'Dungeons and Raids' section found in the hotfix article; "
            "the page structure may have changed."
        )

    result = {}
    for cm_id, entries in by_dungeon.items():
        ordered = sorted(entries.items(), key=lambda kv: kv[0], reverse=True)
        result[cm_id] = [
            {"date_ts": date_ms, "date_text": e["date_text"], "notes": e["notes"]}
            for date_ms, e in ordered[:PER_DUNGEON_LIMIT]
        ]
    return result


def main():
    name_to_id = load_dungeon_name_map()

    print(f"Discovering the latest hotfix article from {NEWS_LANDING_URL} ...")
    article_url = discover_latest_article_url(_http_get(NEWS_LANDING_URL))
    print(f"Latest hotfix article: {article_url}")

    per_dungeon = parse_hotfixes(_http_get(article_url), name_to_id)
    matched = sum(1 for v in per_dungeon.values() if v)
    print(
        f"Parsed hotfixes for {matched}/{len(name_to_id)} current-season dungeons."
    )

    payload = {
        "generated_ts": int(datetime.now(timezone.utc).timestamp() * 1000),
        "source_url": article_url,
        "per_dungeon_limit": PER_DUNGEON_LIMIT,
        "dungeons": per_dungeon,
    }
    # Written last so a fetch/parse failure fails the job without touching the file.
    with open(HOTFIXES_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {HOTFIXES_JSON}")


if __name__ == "__main__":
    main()
