import os
import re
import json
import time
import requests
import databaseConnector
import commonUtils
from contextlib import closing
from aggregateData import get_current_season_id, get_access_token, fetch_json

# config
CLIENT_ID = os.environ["BLIZ_CLIENT_ID"]
CLIENT_SECRET = os.environ["BLIZ_CLIENT_SECRET"]
RAIDERIO_API_KEY = os.environ["RAIDERIO_API_KEY"]
NAMESPACE = "dynamic-us"
API_BASE = "https://us.api.blizzard.com"
ICON_DIR = "data/icons"
MDT_REPO = "Nnoggie/MythicDungeonTools"
MDT_RAW = f"https://raw.githubusercontent.com/{MDT_REPO}/master/"


def get_with_retry(url, **kwargs):
    resp = requests.get(url, **kwargs)
    if resp.status_code == 429:
        time.sleep(int(resp.headers.get("Retry-After", 1)))
        resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def mdt_dungeon_files():
    """Every '<Expansion>/<Dungeon>.lua' in MythicDungeonTools, by normalised file name."""
    tree = get_with_retry(f"https://api.github.com/repos/{MDT_REPO}/git/trees/master",
                          params={"recursive": "1"}).json()
    files = {}
    for t in tree["tree"]:
        m = re.fullmatch(r"[A-Za-z]+/([A-Za-z]+)\.lua", t["path"])
        if m:
            files.setdefault(_norm(m.group(1)), []).append(t["path"])
    return files


def mdt_enemy_blocks(dungeon_id, english_name, mdt_files):
    """One text block per enemy of the MythicDungeonTools file whose mapID is this challenge mode id."""
    hits = []
    for path in mdt_files.get(_norm(english_name), []):
        lua = get_with_retry(MDT_RAW + path).text
        if re.search(rf"\bmapID\s*=\s*{dungeon_id}\b", lua):
            hits.append(lua)
    if len(hits) != 1:
        raise RuntimeError(f"Expected one MythicDungeonTools file with mapID {dungeon_id} "
                           f"('{english_name}'), found {len(hits)}")
    return re.split(r"\n  \[\d+\] = \{", hits[0].split("MDT.dungeonEnemies", 1)[1])


def mdt_boss_npcs(dungeon_id, blocks):
    """(npc_id, name, add ids) of the enemies MDT flags isBoss with an encounterID (mini-bosses
    have none). A boss's adds are the enemies worth no forces in its MDT pull group. The
    encounterID values are placeholders in new dungeons, so they do not group the npcs."""
    bosses, adds = [], []
    for block in blocks:
        name = re.search(r'\["name"\]\s*=\s*"(.*)"', block)
        npc_id = re.search(r'\["id"\]\s*=\s*(\d+)', block)
        if not (name and npc_id):
            continue
        groups = set(re.findall(r'\["g"\]\s*=\s*(\d+)', block))
        if re.search(r'\["isBoss"\]\s*=\s*true', block) and re.search(r'\["encounterID"\]', block):
            bosses.append((int(npc_id.group(1)), name.group(1), groups))
        elif re.search(r'\["count"\]\s*=\s*0\b', block):
            adds.append((int(npc_id.group(1)), groups))
    if not bosses:
        raise RuntimeError(f"MythicDungeonTools lists no isBoss enemy for dungeon {dungeon_id}")
    return [(npc_id, name, {a for a, a_groups in adds if a_groups & groups})
            for npc_id, name, groups in bosses]


def mdt_enemies(dungeon_id, blocks):
    """Health, forces, creature type and spells of every MDT enemy, by npc id (str). The spell
    flags are MDT's own: interruptible and the dispel types (magic, poison, bleed, ...)."""
    enemies = {}
    for block in blocks:
        npc_id = re.search(r'\["id"\]\s*=\s*(\d+)', block)
        if not npc_id:
            continue
        health = re.search(r'\["health"\]\s*=\s*(\d+)', block)
        count = re.search(r'\["count"\]\s*=\s*(\d+)', block)
        creature_type = re.search(r'\["creatureType"\]\s*=\s*"(.*)"', block)
        if not (health and count and creature_type):
            raise RuntimeError(f"Dungeon {dungeon_id}: MDT enemy {npc_id.group(1)} has no health, "
                               f"count or creatureType")
        spells = re.search(r'\["spells"\]\s*=\s*\{(.*?)\n    \}', block, re.S)
        enemies[npc_id.group(1)] = {
            "health": int(health.group(1)),
            "count": int(count.group(1)),
            "type": creature_type.group(1),
            "spells": {sid: re.findall(r'\["(\w+)"\]\s*=\s*true', flags) for sid, flags
                       in re.findall(r'\[(\d+)\]\s*=\s*\{(.*?)\}', spells.group(1) if spells else "", re.S)},
        }
    if not enemies:
        raise RuntimeError(f"MythicDungeonTools lists no enemy for dungeon {dungeon_id}")
    return enemies


def journal_sections(sections):
    """The journal ability tree, trimmed to what the dungeon page's boss modal shows."""
    return [{"title": s.get("title"), "body_text": s.get("body_text"),
             "spell_id": (s.get("spell") or {}).get("id"),
             "sections": journal_sections(s.get("sections"))}
            for s in sections or []]


def journal_bosses(journal_id, headers):
    """[(encounter name, {creature names}, encounter json)] of a journal instance, in journal order."""
    params = {"namespace": "static-us", "locale": "en_US"}
    inst = get_with_retry(f"{API_BASE}/data/wow/journal-instance/{journal_id}",
                          headers=headers, params=params).json()
    out = []
    for e in inst.get("encounters") or []:
        enc = get_with_retry(f"{API_BASE}/data/wow/journal-encounter/{e['id']}",
                             headers=headers, params=params).json()
        out.append((e["name"], {c["name"] for c in enc.get("creatures") or []}, enc))
    return out


def group_bosses(dungeon_id, mdt_npcs, journal):
    """Journal bosses with the MDT boss npc ids (and their adds) that belong to each: a creature
    or boss name equal to the npc name, else one containing the other (Echo of Nalorakk -> Nalorakk)."""
    npc_ids = {name: set() for name, _, _ in journal}
    for npc_id, npc_name, add_ids in mdt_npcs:
        n = _norm(npc_name)
        for match in (lambda c: c == n, lambda c: c in n or n in c):
            found = {name for name, creatures, _ in journal
                     if any(match(_norm(c)) for c in creatures | {name})}
            if found:
                break
        if len(found) != 1:
            raise RuntimeError(f"Dungeon {dungeon_id}: MDT boss {npc_name} ({npc_id}) matches "
                               f"{len(found)} journal bosses ({sorted(found)})")
        npc_ids[found.pop()] |= {npc_id} | add_ids
    missing = [name for name, ids in npc_ids.items() if not ids]
    if missing:
        raise RuntimeError(f"Dungeon {dungeon_id}: no MDT boss npc for journal boss(es) {missing}")
    shared = [n for n in set().union(*npc_ids.values()) if sum(n in ids for ids in npc_ids.values()) > 1]
    if shared:
        raise RuntimeError(f"Dungeon {dungeon_id}: npc(s) {shared} belong to several journal bosses")
    return [{"name": name, "npc_ids": sorted(npc_ids[name]), "journal_encounter_id": enc["id"]}
            for name, _, enc in journal]



databaseConnector.init_connection_pool(
    os.environ.get("DATABASE_HOST"),
    os.environ.get("DATABASE_USER"),
    os.environ.get("DATABASE_PASSWORD"),
    os.environ.get("DATABASE_NAME"),
    os.environ.get("DATABASE_PORT"),
    1,
)


expansion_id = commonUtils.derive_expansion_id()

static_url = "https://raider.io/api/v1/mythic-plus/static-data"
static_params = {"access_key": RAIDERIO_API_KEY, "expansion_id": expansion_id}

sresp = requests.get(static_url, params=static_params)
sresp.raise_for_status()
raider_data = sresp.json()

print("Raider.IO static dungeons:")
for d in raider_data["dungeons"]:
    print(
        f"  journal-id={d['id']}, keystone-id={d['challenge_mode_id']}, short='{d['short_name']}'"
    )
token = get_access_token(CLIENT_ID, CLIENT_SECRET)
seasons = raider_data.get("seasons", [])

short_name_map = {}

slug_map = {}
current_season = get_current_season_id(token)
print(f"Current season ID: {current_season}")
max_season_id = max(s.get("blizzard_season_id", 0) for s in seasons)
print(f"Max season ID in Raider.IO data: {max_season_id}")
if max_season_id >= current_season:
    for season in seasons:
        if season.get("blizzard_season_id", 0) == current_season:
            for d in season.get("dungeons", []):
                short_name_map[d["challenge_mode_id"]] = d["short_name"]
                slug_map[d["challenge_mode_id"]] = d["slug"]
else:
    print(
        f"Warning: No season in Raider.IO data matches the current Blizzard season {current_season}. Using {max_season_id} as a fallback."
    )
    for season in seasons:
        if season.get("blizzard_season_id", 0) == max_season_id:
            for d in season.get("dungeons", []):
                short_name_map[d["challenge_mode_id"]] = d["short_name"]
                slug_map[d["challenge_mode_id"]] = d["slug"]

print("Full Map of Raider.IO short names:")
print(short_name_map)

# The journal has no npc ids, so boss npc ids come from MythicDungeonTools and the
# journal only groups them into bosses.
mdt_files = mdt_dungeon_files()
out = {}
# Journal text and MDT enemies for the dungeon page's detail modals, kept out of dungeons.json
# because the route and VOD finders inline that whole file.
details = {}
headers = {"Authorization": f"Bearer {token}"}
for dungeon_id in short_name_map:
    print(f"Fetching data for dungeon {dungeon_id}...")
    url = f"{API_BASE}/data/wow/mythic-keystone/dungeon/{dungeon_id}"
    params = {"namespace": NAMESPACE}
    resp = requests.get(url, headers=headers, params=params)
    # handle rate‐limit / transient errors
    if resp.status_code == 429:
        retry = int(resp.headers.get("Retry-After", 1))
        time.sleep(retry)
        resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    upgrades = {
        str(u["upgrade_level"]): {
            "upgrade_level": u["upgrade_level"],
            "qualifying_duration": u["qualifying_duration"],
        }
        for u in data.get("keystone_upgrades", [])
    }

    journal_id = data["dungeon"]["id"]
    journal_href = data["dungeon"].get("key", {}).get("href")

    media_url = f"{API_BASE}/data/wow/media/journal-instance/{journal_id}"
    media_params = {"namespace": "static-us"}
    try:
        mresp = requests.get(media_url, headers=headers, params=media_params)
        mresp.raise_for_status()
        media = mresp.json()
    except requests.exceptions.HTTPError as e:
        print(f"Warning: Failed to fetch media for journal instance {journal_id}: {e}")
        media = {"assets": []}

    mdt_blocks = mdt_enemy_blocks(dungeon_id, data["name"]["en_US"], mdt_files)
    journal = journal_bosses(journal_id, headers)
    bosses = group_bosses(dungeon_id, mdt_boss_npcs(dungeon_id, mdt_blocks), journal)
    print(f"  bosses: {bosses}")
    details[dungeon_id] = {
        "journal": {str(enc["id"]): {"description": enc.get("description"),
                                     "sections": journal_sections(enc.get("sections"))}
                    for _, _, enc in journal},
        "enemies": mdt_enemies(dungeon_id, mdt_blocks),
    }

    tile_asset = next(
        (a for a in media.get("assets", []) if a.get("key") == "tile"), None
    )
    icon_filename = None
    if tile_asset and tile_asset.get("value"):
        icon_url = tile_asset["value"]
        icon_filename = icon_url.rsplit("/", 1)[-1]
        try:
            img_resp = requests.get(icon_url)
            img_resp.raise_for_status()
            with open(os.path.join(ICON_DIR, icon_filename), "wb") as imgf:
                imgf.write(img_resp.content)
        except requests.RequestException as e:
            print(f"Error fetching icon for dungeon {dungeon_id}: {e}")

    out[dungeon_id] = {
        "name": data["name"],
        "slug": slug_map.get(dungeon_id),
        "keystone_upgrades": upgrades,
        "icon": icon_filename,
        "raiderio_short_name": short_name_map.get(dungeon_id),
        "bosses": bosses,
        "boss_npc_ids": sorted(i for b in bosses for i in b["npc_ids"]),
        # Blizzard Dungeon Journal instance id (matches the instanceId in
        # Raidbots equippable-items.json "sources"), used to map loot to dungeons.
        "journal_instance_id": journal_id,
    }
    with closing(databaseConnector.get_connection()) as conn:
        cursor = conn.cursor()
        databaseConnector.insert_dungeon_data(
            conn,
            cursor,
            dungeon_id=dungeon_id,
            slug=slug_map.get(dungeon_id),
            name_en_us=data["name"]["en_US"],
            up1=upgrades.get("1", {}).get("qualifying_duration"),
            up2=upgrades.get("2", {}).get("qualifying_duration"),
            up3=upgrades.get("3", {}).get("qualifying_duration"),
        )
        databaseConnector.commit_changes(conn)

os.makedirs("data/static", exist_ok=True)
print(f"Output is {len(out)} long")
if len(out) != 0:
    with open("data/static/dungeons.json", "w") as f:
        json.dump(out, f, indent=2)
    with open("data/static/dungeon_details.json", "w", encoding="utf-8") as f:
        json.dump(details, f, indent=2, ensure_ascii=False)
    print("Json files written")
