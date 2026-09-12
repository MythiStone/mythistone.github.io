"""Collect the latest official WoW hotfix notes per current-season dungeon and
per class specialization.

Credential-free static-data collector (no DB, no secrets). It scrapes Blizzard's
official hotfix notes and writes ``data/static/hotfixes.json``, which the dungeon
and spec page generators read directly (same model as ``patches.json``). It runs
as a step of the page build (``buildPages.yml``), not as a standalone workflow,
so ``hotfixes.json`` is regenerated each build and never committed.

Why scraping: there is no structured API for hotfix *narrative* text (wago.tools
only exposes raw DB2 data-table diffs, not readable notes). Discovery is still
JSON-clean, though: the news landing page links every hotfix article by a dated
slug, so we never hardcode an article id. The article body itself is
server-rendered HTML parsed with BeautifulSoup.

Source structure (worldofwarcraft.blizzard.com hotfix living-document):
- ``div.detail`` holds the whole article. Its children are, in document order, a
  date paragraph (text like "September 9, 2026"), then repeating
  ``<p><strong>Category</strong></p>`` headers each followed by a sibling ``<ul>``.
- Under the "Dungeons and Raids" category, each top-level ``<li>`` leads with a
  ``<strong>`` dungeon/raid name and carries a nested ``<ul>`` of bullets; a bullet
  may itself be a ``<li><strong>Boss</strong><ul>...</ul></li>`` subsection.
- Under the "Classes" category, each top-level ``<li>`` leads with a ``<strong>``
  class name and a nested ``<ul>`` whose children are, in document order: a spec
  subsection (``<li><strong>Spec</strong><ul>...</ul></li>``), a "Hero Talents"
  wrapper holding one subsection per hero-talent tree, or a leaf ``<li>`` that is a
  class-wide note not tied to any spec. Spec names collide across classes ("Holy"
  is Paladin and Priest), so matching is scoped to the current class; hero-tree
  names come from ``data/static/talents/<specId>.json`` (``subTrees``) and each
  tree maps to the two specs that share it. Class-wide notes are folded into every
  spec of the class (prefixed with the class name); hero-tree notes are prefixed
  with the tree name.
- Dungeon names match ``data/static/dungeons.json`` ``name.en_US`` verbatim, so we
  match by name and keep only the current-season dungeons (per-dungeon only: raids
  and general Mythic+/system entries are ignored).

Fails loudly (per repo policy): every HTTP call raises on error, discovery raises
if no hotfix article is found, and parsing raises if the "Dungeons and Raids"
section is never located (a markup change surfaces as a failed run, not silently
empty pages). A dungeon or spec legitimately having no hotfixes is a normal empty
list, and an article with no "Classes" section (a pure-dungeon hotfix) is allowed.
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
SPECS_JSON = os.path.join("data", "static", "specs.json")
CLASSES_JSON = os.path.join("data", "static", "classes.json")
TALENTS_DIR = os.path.join("data", "static", "talents")
HOTFIXES_JSON = os.path.join("data", "static", "hotfixes.json")

# Keep at most this many dated entries per dungeon / per spec (newest first).
PER_DUNGEON_LIMIT = 8
PER_SPEC_LIMIT = 8

# Category header that groups per-instance hotfixes. Matched as a prefix because
# the source occasionally renders it as "Dungeons and Raid" (a stray split node).
DUNGEONS_CATEGORY_PREFIX = "dungeons and raid"
# Category header that groups per-class/spec hotfixes.
CLASSES_CATEGORY_PREFIX = "classes"

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


def _flatten_ul(ul):
    """Flatten a bullet <ul> into note strings. A nested subsection
    (a <li> with its own <ul> under a <strong> label) becomes "Label: bullet"."""
    if ul is None:
        return []
    notes = []
    for li in ul.find_all("li", recursive=False):
        sub = li.find("ul")
        if sub is not None:
            # Subsection: <strong>Label</strong> then leaf bullets (e.g. a boss
            # under a dungeon).
            strong = li.find("strong")
            label = strong.get_text(" ", strip=True) if strong else ""
            for leaf in sub.find_all("li", recursive=False):
                text = leaf.get_text(" ", strip=True)
                if text:
                    notes.append(f"{label}: {text}" if label else text)
        else:
            text = li.get_text(" ", strip=True)
            if text:
                notes.append(text)
    return notes


def _extract_bullets(dungeon_li):
    """Flatten a matched dungeon <li>'s nested bullet list into note strings.
    Boss subsections (nested <ul> under a <strong>) become "Boss: bullet"."""
    return _flatten_ul(dungeon_li.find("ul"))


def load_spec_maps(
    specs_path=SPECS_JSON, classes_path=CLASSES_JSON, talents_dir=TALENTS_DIR
):
    """Build the name lookups the "Classes" section is matched against.

    Returns a dict with three normalized-name maps (spec ids are strings, matching
    ``specs.json`` keys and the spec generator's ``str(spec_id)`` lookup):
      - ``classes``: class_norm -> {"name", "key", "spec_ids": [...]}
      - ``specs``: (class_norm, spec_norm) -> spec_id
      - ``herotrees``: (class_norm, tree_norm) -> {"name", "spec_ids": [...]}

    Spec/hero-tree keys are scoped to the class because both name spaces collide
    across classes ("Holy" is Paladin and Priest; "Frostfire" is Fire and Frost
    Mage). Hero-tree names come from each spec's ``talents/<specId>.json`` subTrees.
    """
    with open(specs_path, "r", encoding="utf-8") as f:
        specs = json.load(f)
    with open(classes_path, "r", encoding="utf-8") as f:
        classes = json.load(f)

    class_by_id = {}   # classID (str) -> class entry
    classes_map = {}   # class_norm -> class entry
    for class_id, cdata in classes.items():
        name = cdata.get("name")
        if not name:
            continue
        entry = {"name": name, "key": _normalize_name(name), "spec_ids": []}
        class_by_id[str(class_id)] = entry
        classes_map[entry["key"]] = entry

    spec_map = {}    # (class_norm, spec_norm) -> spec_id
    herotrees = {}   # (class_norm, tree_norm) -> {"name", "spec_ids"}
    for spec_id, sdata in specs.items():
        cls = class_by_id.get(str(sdata.get("classID")))
        if cls is None:
            continue
        spec_id = str(spec_id)
        cls["spec_ids"].append(spec_id)
        spec_name = sdata.get("name")
        if spec_name:
            spec_map[(cls["key"], _normalize_name(spec_name))] = spec_id
        talents_path = os.path.join(talents_dir, f"{spec_id}.json")
        if not os.path.exists(talents_path):
            continue
        with open(talents_path, "r", encoding="utf-8") as f:
            tdata = json.load(f)
        for _tid, tinfo in (tdata.get("subTrees") or {}).items():
            tree_name = tinfo.get("name") if isinstance(tinfo, dict) else None
            if not tree_name:
                continue
            tree = herotrees.setdefault(
                (cls["key"], _normalize_name(tree_name)),
                {"name": tree_name, "spec_ids": []},
            )
            if spec_id not in tree["spec_ids"]:
                tree["spec_ids"].append(spec_id)

    if not spec_map:
        raise RuntimeError(
            f"No spec names found in {specs_path}/{classes_path}"
        )
    return {"classes": classes_map, "specs": spec_map, "herotrees": herotrees}


def _parse_class_li(class_li, class_key, class_entry, spec_maps):
    """Yield ``(spec_ids, note)`` pairs for one class's <li> in document order.

    A leaf bullet is class-wide (folded into every spec of the class, prefixed with
    the class name). A spec subsection yields that spec's bullets unprefixed. A
    hero-tree subsection (directly, or nested under a "Hero Talents" wrapper) yields
    the tree's specs, prefixed with the tree name. Any unrecognized subsection
    heading is kept as a class-wide note prefixed with the heading, so nothing is
    silently dropped.
    """
    inner = class_li.find("ul")
    if inner is None:
        return
    class_name = class_entry["name"]
    class_spec_ids = class_entry["spec_ids"]
    spec_by_name = spec_maps["specs"]
    trees_by_name = spec_maps["herotrees"]

    for li in inner.find_all("li", recursive=False):
        sub = li.find("ul")
        if sub is None:
            text = li.get_text(" ", strip=True)
            if text:
                yield class_spec_ids, f"{class_name}: {text}"
            continue

        strong = li.find("strong")
        heading = strong.get_text(" ", strip=True) if strong else ""
        heading_norm = _normalize_name(heading)

        spec_id = spec_by_name.get((class_key, heading_norm))
        if spec_id is not None:
            for note in _flatten_ul(sub):
                yield [spec_id], note
            continue

        tree = trees_by_name.get((class_key, heading_norm))
        if tree is not None:
            for note in _flatten_ul(sub):
                yield tree["spec_ids"], f"{tree['name']}: {note}"
            continue

        if heading_norm.startswith("hero talents"):
            for tree_li in sub.find_all("li", recursive=False):
                t_strong = tree_li.find("strong")
                t_heading = t_strong.get_text(" ", strip=True) if t_strong else ""
                t_tree = trees_by_name.get((class_key, _normalize_name(t_heading)))
                t_sub = tree_li.find("ul")
                if t_sub is not None:
                    bullets = _flatten_ul(t_sub)
                else:
                    leaf = tree_li.get_text(" ", strip=True)
                    bullets = [leaf] if leaf else []
                if t_tree is not None:
                    for note in bullets:
                        yield t_tree["spec_ids"], f"{t_tree['name']}: {note}"
                else:
                    label = t_heading or class_name
                    for note in bullets:
                        yield class_spec_ids, f"{label}: {note}"
            continue

        # Unrecognized subsection: keep as a class-wide note labeled by its heading.
        label = heading or class_name
        for note in _flatten_ul(sub):
            yield class_spec_ids, f"{label}: {note}"


def _add_note(by_key, key, date_ms, date_text, note):
    """Append one note into ``by_key[key][date_ms]`` (created on first use)."""
    entries = by_key.setdefault(key, {})
    entry = entries.setdefault(date_ms, {"date_text": date_text, "notes": []})
    entry["notes"].append(note)


def _finalize(by_key, limit):
    """Turn a {key: {date_ms: {...}}} accumulator into the JSON list shape:
    {key: [ {date_ts, date_text, notes}, ... ]} newest-first, capped to ``limit``."""
    result = {}
    for key, entries in by_key.items():
        ordered = sorted(entries.items(), key=lambda kv: kv[0], reverse=True)
        result[key] = [
            {"date_ts": date_ms, "date_text": e["date_text"], "notes": e["notes"]}
            for date_ms, e in ordered[:limit]
        ]
    return result


def parse_hotfixes(html, name_to_id, spec_maps):
    """Parse an article's HTML into per-dungeon and per-spec hotfix maps, each
    shaped {id: [ {date_ts, date_text, notes:[...]}, ... ]} (newest first, capped
    to PER_DUNGEON_LIMIT / PER_SPEC_LIMIT). Returns ``(per_dungeon, per_spec)``.

    Raises if the "Dungeons and Raids" category is never found (markup change). A
    missing "Classes" section is allowed (a pure-dungeon hotfix) and yields no
    spec entries."""
    soup = BeautifulSoup(html, "html.parser")
    detail = soup.find("div", class_="detail")
    if detail is None:
        raise RuntimeError("Hotfix article has no <div class='detail'> content container.")

    # dungeon id / spec id -> { date_ms: {"date_text": str, "notes": [...]} }
    by_dungeon = {}
    by_spec = {}
    current_date = None
    saw_dungeons_category = False

    for child in detail.children:
        if getattr(child, "name", None) is None:
            continue
        text = child.get_text(" ", strip=True)
        if not text:
            continue

        if child.name != "p":
            continue

        date = _parse_date(text)
        # A paragraph whose whole text IS the date is a section boundary. The
        # exact-match guard avoids mistaking a body paragraph that merely
        # mentions a date for one.
        if date and text.strip().rstrip(".") == date[1]:
            current_date = date
            continue

        strong = child.find("strong")
        if not strong:
            continue
        heading = strong.get_text(" ", strip=True).casefold()
        ul = child.find_next_sibling("ul")
        if ul is None or current_date is None:
            continue
        date_ms, date_text = current_date

        if heading.startswith(DUNGEONS_CATEGORY_PREFIX):
            saw_dungeons_category = True
            for li in ul.find_all("li", recursive=False):
                strong_name = li.find("strong")
                if strong_name is None:
                    continue
                key = _normalize_name(strong_name.get_text(" ", strip=True))
                cm_id = name_to_id.get(key)
                if cm_id is None:
                    continue  # raid or non-season dungeon: ignored
                for note in _extract_bullets(li):
                    _add_note(by_dungeon, cm_id, date_ms, date_text, note)

        elif heading.startswith(CLASSES_CATEGORY_PREFIX):
            for class_li in ul.find_all("li", recursive=False):
                strong_name = class_li.find("strong")
                if strong_name is None:
                    continue
                class_key = _normalize_name(strong_name.get_text(" ", strip=True))
                class_entry = spec_maps["classes"].get(class_key)
                if class_entry is None:
                    continue  # unknown class heading
                for spec_ids, note in _parse_class_li(
                    class_li, class_key, class_entry, spec_maps
                ):
                    for spec_id in spec_ids:
                        _add_note(by_spec, spec_id, date_ms, date_text, note)

    if not saw_dungeons_category:
        raise RuntimeError(
            "No 'Dungeons and Raids' section found in the hotfix article; "
            "the page structure may have changed."
        )

    return (
        _finalize(by_dungeon, PER_DUNGEON_LIMIT),
        _finalize(by_spec, PER_SPEC_LIMIT),
    )


def main():
    name_to_id = load_dungeon_name_map()
    spec_maps = load_spec_maps()

    print(f"Discovering the latest hotfix article from {NEWS_LANDING_URL} ...")
    article_url = discover_latest_article_url(_http_get(NEWS_LANDING_URL))
    print(f"Latest hotfix article: {article_url}")

    per_dungeon, per_spec = parse_hotfixes(
        _http_get(article_url), name_to_id, spec_maps
    )
    matched_dungeons = sum(1 for v in per_dungeon.values() if v)
    matched_specs = sum(1 for v in per_spec.values() if v)
    print(
        f"Parsed hotfixes for {matched_dungeons}/{len(name_to_id)} current-season "
        f"dungeons and {matched_specs} specs."
    )

    payload = {
        "generated_ts": int(datetime.now(timezone.utc).timestamp() * 1000),
        "source_url": article_url,
        "per_dungeon_limit": PER_DUNGEON_LIMIT,
        "per_spec_limit": PER_SPEC_LIMIT,
        "dungeons": per_dungeon,
        "specs": per_spec,
    }
    # Written last so a fetch/parse failure fails the job without touching the file.
    with open(HOTFIXES_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {HOTFIXES_JSON}")


if __name__ == "__main__":
    main()
