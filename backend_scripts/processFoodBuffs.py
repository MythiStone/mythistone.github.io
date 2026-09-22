"""Build data/static/food_buffs.json: a {well-fed buff spell id -> food item id} map.

Food is the one consumable whose aura (a generic, server-scripted "Well Fed" buff)
is not linked to its item in any game data (see the failed attempts documented in
AGENTS.md). SimulationCraft, however, hand-maintains that link per expansion in
``engine/player/unique_gear_<codename>.cpp``: each food's eat spell is registered
with ``consumables::*_food( <well-fed buff spell id>, ... ); // <food name>``. We
parse those lines, match the food name to raidbots foods.json (via the collapsed
food entries in consumables.json), and emit ``buff spell id -> item id``.

SimC covers the personal foods but not feasts or every quality tier, so
``data/static/food_buff_overrides.json`` ({spell_id: item_id}) is a hand-maintained
supplement (e.g. the primary-stat feast buff most players show). It wins over the
parsed map.

DB-free. The current expansion is auto-discovered: SimC renames its default branch to
the current expansion's codename each expansion (dragonflight -> thewarwithin ->
midnight -> ...), and the food table lives in ``unique_gear_<codename>.cpp`` on it, so
no hardcoded expansion map is needed.
"""

import json
import os
import re
import urllib.request

from commonUtils import normalize_consumable_name

STATIC_DIR = "data/static"
SIMC_REPO = "simulationcraft/simc"

# register_special_effect( <eat>, consumables::(selector|primary|secondary)_food( <buff>, ... ) ); // <names>
FOOD_LINE = re.compile(
    r"register_special_effect\(\s*\d+,\s*consumables::(?:selector|primary|secondary)_food\(\s*"
    r"(\d+)[^;]*;\s*//\s*(.+)"
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _gh(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def fetch_simc_food_source():
    """Auto-discover and fetch the current expansion's unique_gear file.

    SimC's default branch is the current expansion's codename, and it ships
    ``engine/player/unique_gear_<codename>.cpp``. If that exact file is missing (a
    naming change), fall back to the most recently committed unique_gear file, which
    is the one under active development for the live expansion."""
    branch = _gh(f"https://api.github.com/repos/{SIMC_REPO}")["default_branch"]
    listing = _gh(f"https://api.github.com/repos/{SIMC_REPO}/contents/engine/player?ref={branch}")
    files = {f["name"] for f in listing if isinstance(f, dict)}

    fname = f"unique_gear_{branch}.cpp"
    if fname not in files:
        candidates = [
            n for n in files
            if n.startswith("unique_gear_") and n.endswith(".cpp") and n != "unique_gear_helper.cpp"
        ]
        if not candidates:
            raise RuntimeError("no unique_gear_*.cpp files found in SimC engine/player")

        def last_commit(n):
            c = _gh(f"https://api.github.com/repos/{SIMC_REPO}/commits"
                    f"?path=engine/player/{n}&per_page=1&sha={branch}")
            return c[0]["commit"]["committer"]["date"] if c else ""

        fname = max(candidates, key=last_commit)

    url = f"https://raw.githubusercontent.com/{SIMC_REPO}/{branch}/engine/player/{fname}"
    print(f"Fetching SimC food data: {url}")
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60
    ).read().decode("utf-8", "replace")


def build_map(simc_src, food_item_by_norm_name, overrides):
    """{buff_spell_id(str) -> item_id(int)}. SimC gives buff -> food name(s); we
    resolve the name against the (normalized) food entries in consumables.json."""
    mapping = {}
    unresolved = []
    for m in FOOD_LINE.finditer(simc_src):
        buff_id = m.group(1)
        # comment may list several food names sharing the buff ("a / b / c")
        names = [n.strip() for n in m.group(2).split("/")]
        item_id = None
        for name in names:
            item_id = food_item_by_norm_name.get(normalize_consumable_name(name))
            if item_id is not None:
                break
        if item_id is not None:
            mapping[buff_id] = item_id
        else:
            unresolved.append((buff_id, names[0] if names else ""))

    # Manual supplement (feasts, quality tiers SimC omits) wins over the parsed map.
    for spell_id, item_id in overrides.items():
        mapping[str(spell_id)] = int(item_id)

    return mapping, unresolved


def main():
    simc_src = fetch_simc_food_source()

    consumables = load_json(os.path.join(STATIC_DIR, "consumables.json"))
    food_item_by_norm_name = {
        c["norm_name"]: c["item_id"]
        for c in consumables
        if c.get("category") == "food" and c.get("norm_name") and c.get("item_id") is not None
    }
    try:
        overrides = load_json(os.path.join(STATIC_DIR, "food_buff_overrides.json"))
    except (OSError, ValueError):
        overrides = {}

    mapping, unresolved = build_map(simc_src, food_item_by_norm_name, overrides)

    out_path = os.path.join(STATIC_DIR, "food_buffs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, sort_keys=True)
    print(f"Wrote {len(mapping)} food buff->item mappings to {out_path} "
          f"({len(overrides)} from overrides).")
    if unresolved:
        print(f"NOTE: {len(unresolved)} SimC food buffs had no matching item in "
              f"consumables.json (name mismatch or not in the current food catalog): "
              f"{[u[1] for u in unresolved][:10]}")


if __name__ == "__main__":
    main()
