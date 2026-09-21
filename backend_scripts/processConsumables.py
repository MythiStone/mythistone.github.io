"""Build data/static/consumables.json from the Raidbots consumable catalogs.

Reads the five raidbots live lookups (flasks/potions/foods/augments/temp-enchants,
curled into data/static by getStaticData.yml) and emits one flat catalog the
collector and the spec-page generator both consume via commonUtils.

Raidbots entries carry no spell id, only itemId + name/shortName + icon, so the
buff-spell -> item link is made at ingest by normalized name (see
commonUtils.match_consumable_aura). This script only produces the normalized
name/shortName keys and a canonical item per name family. It is DB-free.

Only the current expansion's entries are kept (the max ``expansion`` present in
each file, which is always the live-patch content), so an old-expansion item
sharing a base name with a current one never shadows it.
"""

import json
import os

from commonUtils import (
    _CONSUMABLE_QUALITY_RE,
    normalize_consumable_name,
    normalize_consumable_short_name,
)

STATIC_DIR = "data/static"

# raidbots file (without .json) -> our consumable category
CATEGORY_BY_FILE = {
    "flasks": "flask",
    "potions": "potion",
    "foods": "food",
    "augments": "augment",
    "temp-enchants": "weapon",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_category(entries, category):
    """Collapse a raidbots array to one canonical entry per name family.

    Q1/Q2 variants share a base name, so they collapse to the highest
    craftingQuality variant; its itemId/icon represent the family."""
    current = max((e.get("expansion", 0) for e in entries), default=0)
    families = {}
    for e in entries:
        if e.get("expansion") != current:
            continue
        # Case-preserving display name: strip only the " (Quality N)" suffix.
        display_name = _CONSUMABLE_QUALITY_RE.sub("", (e.get("name") or "").strip()).strip()
        norm_name = normalize_consumable_name(e.get("name"))
        norm_short = normalize_consumable_short_name(e.get("shortName"))
        key = norm_name or norm_short
        if not key:
            continue
        cq = e.get("craftingQuality") or 0
        prev = families.get(key)
        if prev is None or cq > (prev.get("quality") or 0):
            families[key] = {
                "value": e.get("value"),
                "category": category,
                "item_id": e.get("itemId"),
                "name": display_name,
                "icon": e.get("icon"),
                "quality": e.get("craftingQuality"),
                "norm_name": norm_name,
                "norm_short": norm_short,
            }
    return list(families.values())


REQUIRED_CATEGORIES = ("flask", "potion", "food")


def main():
    catalog = []
    counts = {}
    for fname, category in CATEGORY_BY_FILE.items():
        path = os.path.join(STATIC_DIR, f"{fname}.json")
        entries = load_json(path)
        built = build_category(entries, category)
        catalog.extend(built)
        counts[category] = len(built)
        print(f"{fname}: {len(built)} {category} entries")

    empty = [c for c in REQUIRED_CATEGORIES if not counts.get(c)]
    if empty:
        raise RuntimeError(
            f"consumables catalog is missing required categories {empty} "
            f"(counts={counts}). The Raidbots catalogs or the current-expansion filter "
            f"produced nothing for them; refusing to write an incomplete consumables.json."
        )

    catalog.sort(key=lambda e: (e["category"], e["name"] or ""))
    out_path = os.path.join(STATIC_DIR, "consumables.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, sort_keys=True)
    print(f"Wrote {len(catalog)} consumables to {out_path}")


if __name__ == "__main__":
    main()
