"""Build assets/json/search_index.json for the navbar search and /pages/search.

Every walked page declares its own entry through the search_meta macro
(templates/_search_macros.html). Items and consumables come from their manifests
instead, since there are hundreds of them and their pages are not walked.
Entry schema: {name, type, url, subtitle, keywords, icon | symbol}.
"""
import os
import json
from bs4 import BeautifulSoup
from commonUtils import humanize_number, load_json

OUTPUT_PATH = os.path.join("assets", "json", "search_index.json")

EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".claude",
    ".vscode",
    "assets",
    "backend_scripts",
    "templates",
    "data",
    "items",
    "consumables",
}
# Legal pages, the 404 page and the search page itself are not search results.
SKIP_FILES = {"404.html", "impressum.html", "privacy.html", "about.html", "search.html"}
SKIP_PREFIXES = ("pages/admin/",)

QUALITY_NAMES = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic",
                 5: "Legendary", 6: "Artifact", 7: "Heirloom"}


def collect_html_files(root="."):
    """Relative paths of every page the index walks."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if not fname.lower().endswith(".html") or fname in SKIP_FILES:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), root).replace(os.sep, "/")
            if not rel.startswith(SKIP_PREFIXES):
                files.append(rel)
    return sorted(files)


def path_to_url(relpath):
    if relpath == "index.html":
        return "/"
    return "/" + relpath[: -len(".html")]


def search_meta(soup, field):
    tag = soup.find("meta", attrs={"name": f"search:{field}"})
    return tag["content"].strip() if tag and tag.get("content") else None


def page_entries(relpaths):
    entries, missing = [], []
    for rel in relpaths:
        with open(rel, "r", encoding="utf-8") as fh:
            soup = BeautifulSoup(fh.read(), "html.parser")
        name, type_, subtitle = (search_meta(soup, f) for f in ("name", "type", "subtitle"))
        icon, symbol = search_meta(soup, "icon"), search_meta(soup, "symbol")
        if not (name and type_ and subtitle and (icon or symbol)):
            missing.append(rel)
            continue
        keywords = search_meta(soup, "keywords")
        entry = {
            "name": name,
            "type": type_,
            "url": path_to_url(rel),
            "subtitle": subtitle,
            "keywords": [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [],
        }
        if icon:
            entry["icon"] = icon
        else:
            entry["symbol"] = symbol
        entries.append(entry)
    if missing:
        raise RuntimeError(
            "Pages without search:* metas (call search_meta from _search_macros.html "
            "in their template, or skip them in generateSearchIndex.py):\n  "
            + "\n  ".join(missing)
        )
    return entries


def runs_label(runs):
    return f"{humanize_number(runs or 0)} runs"


def item_entries():
    entries = []
    for m in load_json(os.path.join("assets", "json", "items_index.json")):
        # Displayed rarity comes from the bonus ids when it differs from the base item.
        quality = QUALITY_NAMES.get(m.get("quality_override", m["quality"]), "")
        entries.append({
            "name": m["name"],
            "type": "Item",
            "url": f"/items/{m['slug']}",
            "subtitle": " · ".join(p for p in (f"{quality} {m['slot']}".strip(), runs_label(m["runs"])) if p),
            "keywords": [k for k in (m["slot"], quality) if k],
            "icon": f"/data/icons/{m['icon']}.png",
        })
    return entries


def consumable_entries():
    entries = []
    for m in load_json(os.path.join("assets", "json", "consumables_index.json")):
        entries.append({
            "name": m["name"],
            "type": "Consumable",
            "url": f"/consumables/{m['slug']}",
            "subtitle": f"{m['category_label']} · {runs_label(m['runs'])}",
            "keywords": [m["category_label"], m["category"]],
            "icon": f"/data/icons/{m['icon']}.png",
        })
    return entries


def main():
    entries = page_entries(collect_html_files())
    entries += item_entries() + consumable_entries()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, separators=(",", ":"))
    counts = {}
    for e in entries:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Wrote {len(entries)} entries ({counts}) to {OUTPUT_PATH}, "
          f"{os.path.getsize(OUTPUT_PATH) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
