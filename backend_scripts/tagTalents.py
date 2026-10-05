"""Weekly playstyle tags for the talents the spec page's builds differ by.

Runs in getStaticData.yml with a local Ollama model. For every spec it computes
the same builds as generateSpecPages (talentBuilds on the same DB inputs),
collects the talents in their diffs, and asks the model for up to two tags per
talent from talentBuilds.BUILD_TAGS. Results go to data/static/talent_tags.json
({spellId: {"tags", "name", "desc_hash", "model", "tagged_at"}}). The page build
composes "More X, Less Y" names from them (talentBuilds.compose_build_name), so a
name always matches the build it is shown on. data/static/talent_tag_overrides.json
({spellId: [tags]}) is hand-maintained and wins over the model.

Descriptions come from wago.tools (Spell, with real values from SpellEffect,
SpellMisc and SpellDuration), downloaded every run because they change between
game builds. A talent is re-tagged only when its rendered description changes.

NAMER_FAKE=1 swaps the model for deterministic tags (local tests have no model);
--dry-run prints the prompts and writes nothing.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import time
from datetime import datetime, timezone

import requests

import commonUtils
import databaseConnector
import talentBuilds

TAGS_PATH = os.path.join(commonUtils.LOOKUP_DIR, "talent_tags.json")
WAGO_CSV = "https://wago.tools/db2/{table}/csv"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("NAMER_MODEL", "qwen2.5:7b-instruct")
BATCH_SIZE = 12        # talents per prompt
DESC_MAX_CHARS = 400   # per talent; keeps CPU prompt evaluation affordable
MAX_TAGS = 2

TAG_HELP = {
    "AOE": "damage or healing to many targets",
    "SINGLE_TARGET": "damage focused on one target",
    "BURST": "big damage spikes or short damage cooldowns",
    "DEFENSIVE": "an active defensive cooldown or immunity",
    "DAMAGE_REDUCTION": "passive damage taken reduction, absorbs or shields",
    "SELF_HEALING": "heals the player",
    "GROUP_HEALING": "heals party members",
    "INTERRUPT": "interrupts or silences spellcasting",
    "CC_HARD": "stuns, incapacitates, fears, disorients or knocks back",
    "CC_SOFT": "slows or roots",
    "MOVEMENT": "movement speed, dashes or teleports",
    "DISPEL": "removes magic, curse, poison, disease or enrage effects",
    "BATTLE_REZ": "resurrects an ally in combat",
    "UTILITY": "other group utility: buffs, damage reduction for allies, threat",
    "COOLDOWN_REDUCTION": "makes abilities come back sooner",
    "RESOURCE": "generates or saves the spec's resource",
}

PROMPT = """You tag World of Warcraft talents of {spec} by what they do for the player in Mythic+.
Allowed tags:
{tags}

TALENTS:
{talents}

Give each talent 0 to {max_tags} tags from the allowed list that best describe its main effect. Use no tag for a talent that only adds a little passive damage of no clear kind.
Respond with JSON only: {{"tags": {{"<talent id>": ["TAG", ...], ...}}}}
"""


def fetch_table(table, columns):
    """Rows of a wago.tools DB2 table as dicts, keeping only ``columns``."""
    resp = requests.get(WAGO_CSV.format(table=table), timeout=600)
    resp.raise_for_status()
    rows = [{c: r.get(c) for c in columns} for r in csv.DictReader(io.StringIO(resp.content.decode("utf-8")))]
    if not rows:
        raise RuntimeError(f"wago.tools {table} table came back empty")
    return rows


class SpellText:
    """Spell descriptions with their $s1 / $d / $t1 values filled in from the
    live client data, so the model sees '30% for 8 sec' instead of 'X% for X'."""

    def __init__(self):
        self.raw = {int(r["ID"]): r["Description_lang"]
                    for r in fetch_table("Spell", ["ID", "Description_lang"]) if r["Description_lang"]}
        self.effects, self.periods = {}, {}
        for r in fetch_table("SpellEffect", ["SpellID", "EffectIndex", "DifficultyID", "EffectBasePointsF", "EffectAuraPeriod"]):
            if r["DifficultyID"] != "0":
                continue
            key = (int(r["SpellID"]), int(r["EffectIndex"]))
            self.effects[key] = float(r["EffectBasePointsF"] or 0)
            self.periods[key] = int(r["EffectAuraPeriod"] or 0)
        durations = {int(r["ID"]): int(r["Duration"]) for r in fetch_table("SpellDuration", ["ID", "Duration"])}
        self.durations = {}
        for r in fetch_table("SpellMisc", ["SpellID", "DifficultyID", "DurationIndex"]):
            if r["DifficultyID"] == "0" and r["DurationIndex"] not in (None, "", "0"):
                self.durations[int(r["SpellID"])] = durations.get(int(r["DurationIndex"]), 0)

    @staticmethod
    def _num(value):
        value = abs(value)
        return f"{value:g}"

    def _value(self, spell, match):
        sid = int(match.group(1)) if match.group(1) else spell
        kind, idx = match.group(2).lower(), match.group(3)
        if kind in "smw" and idx:
            v = self.effects.get((sid, int(idx) - 1))
            return self._num(v) if v is not None else "X"
        if kind == "d":
            ms = self.durations.get(sid, 0)
            return f"{ms / 1000:g} sec" if ms > 0 else "X"
        if kind == "t" and idx:
            ms = self.periods.get((sid, int(idx) - 1), 0)
            return f"{ms / 1000:g}" if ms > 0 else "X"
        return "X"

    def render(self, spell, depth=0):
        text = self.raw.get(spell, "")
        if depth == 0:
            # a talent that grants an ability often only links its description
            text = re.sub(r"\$@spelldesc(\d+)", lambda m: " " + self.render(int(m.group(1)), 1), text)
        text = re.sub(r"\$@spell\w*?\d+", "", text)
        text = re.sub(r"\|c[0-9A-Fa-f]{8}|\|r", "", text)
        text = re.sub(r"\$[lL]([^:;]+):([^;]+);", r"\2", text)       # $lpoint:points;
        text = re.sub(r"\$\?[^\[]*\[", "", text)                     # conditional heads
        text = re.sub(r"\]\s*\[[^\]]*\]", "", text).replace("]", "")  # keep the first branch
        text = re.sub(r"\$\{[^}]*\}|\$<[^>]*>", "X", text)            # formulas and variables
        text = re.sub(r"\$(\d*)([A-Za-z])(\d?)", lambda m: self._value(spell, m), text)
        return re.sub(r"\s+", " ", text).strip()


def spec_trees(conn, cursor, spec_id, season, dungeon_ids):
    lookup = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{spec_id}.json"))
    rows = databaseConnector.fetch_loadout_key_levels(conn, cursor, spec_id, season)
    top = databaseConnector.fetch_top50_loadouts(conn, cursor, spec_id, season, limit=50)
    trees, _drops = talentBuilds.build_hero_tree_builds(
        rows, spec_id, lookup["fullNodeOrder"], lookup["nodes"],
        top50=talentBuilds.top50_inputs(top, dungeon_ids),
    )
    return lookup, trees


def diff_talents(trees, nodes):
    """{spell_id: talent name} for every talent a shown build or variant changes."""
    out = {}
    for tree in trees.values():
        cores = tree["cores"] + ([tree["top50_extra"]] if tree["top50_extra"] else [])
        for b in cores + [v for c in cores for v in c["variants"]]:
            for _sign, nid, entry, _rank in b["diff"]:
                node = nodes[str(nid)]
                entries = node.get("entries") or [{}]
                e = entries[entry] if entry < len(entries) else entries[0]
                if e.get("spellId"):
                    out[int(e["spellId"])] = e.get("name") or node.get("name")
    return out


def ask_model(prompt, batch):
    if os.environ.get("NAMER_FAKE") == "1":
        tags = list(talentBuilds.BUILD_TAGS)
        return {sid: [tags[sid % len(tags)]] for sid, _name, _desc in batch}
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": MODEL, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }, timeout=1800)
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    # 7B models often drop the {"tags": ...} wrapper
    if isinstance(data, dict) and isinstance(data.get("tags"), dict):
        data = data["tags"]
    wanted = {str(sid): sid for sid, _name, _desc in batch}
    answer = {}
    if isinstance(data, dict):
        for key, value in data.items():
            sid = wanted.get(str(key).strip())
            if sid is None:
                continue
            if isinstance(value, str):
                value = [value]
            if isinstance(value, list):
                tags = [str(t).strip().upper() for t in value if str(t).strip().upper() in talentBuilds.BUILD_TAGS]
                answer[sid] = list(dict.fromkeys(tags))[:MAX_TAGS]
    if not answer:
        print(f"  no usable tags in model reply: {raw[:300]!r}")
    return answer


def check_model():
    if os.environ.get("NAMER_FAKE") == "1":
        return
    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=30)
    tags.raise_for_status()
    if not any(m.get("name", "").startswith(MODEL) for m in tags.json().get("models", [])):
        raise RuntimeError(f"Ollama at {OLLAMA_URL} does not have {MODEL}; run `ollama pull {MODEL}`")


def main(max_minutes, dry_run, only_spec):
    started = time.monotonic()
    check_model()
    text = SpellText()
    old = commonUtils.load_json(TAGS_PATH) if os.path.exists(TAGS_PATH) else {}
    season = commonUtils.current_season_id()
    dungeon_ids = {int(k) for k in commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "dungeons.json"))}
    spec_lookup = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "specs.json"))

    # earlier tags are kept: a talent that drops out of this week's builds can return
    tags = dict(old)
    work = []  # (spec name, [(spell_id, name, description, desc_hash)])
    conn = databaseConnector.get_connection()
    try:
        cursor = conn.cursor()
        for spec_id in sorted(spec_lookup, key=int):
            if only_spec and int(spec_id) != only_spec:
                continue
            if not os.path.exists(os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{spec_id}.json")):
                continue
            lookup, trees = spec_trees(conn, cursor, int(spec_id), season, dungeon_ids)
            spec_name = f'{lookup.get("specName", "")} {lookup.get("className", "")}'.strip()
            pending = []
            for sid, name in sorted(diff_talents(trees, lookup["nodes"]).items()):
                desc = text.render(sid)[:DESC_MAX_CHARS]
                h = hashlib.sha1(desc.encode("utf-8")).hexdigest()[:16]
                cached = old.get(str(sid))
                if not (cached and cached.get("desc_hash") == h):
                    pending.append((sid, name, desc, h))
            if pending:
                work.append((spec_name, pending))
    finally:
        conn.close()

    tagged = 0
    batches = [(spec, items[i:i + BATCH_SIZE]) for spec, items in work for i in range(0, len(items), BATCH_SIZE)]
    for n, (spec, batch) in enumerate(batches):
        if time.monotonic() - started > max_minutes * 60:
            left = sum(len(b) for _s, b in batches[n:])
            print(f"time box of {max_minutes} min reached; {left} talents stay untagged until next run")
            break
        prompt = PROMPT.format(
            spec=spec, max_tags=MAX_TAGS,
            tags="\n".join(f"- {t}: {h}" for t, h in TAG_HELP.items()),
            talents="\n".join(f"- {sid} {name}: {desc or 'no description'}" for sid, name, desc, _h in batch),
        )
        if dry_run:
            print(prompt)
            continue
        answer = ask_model(prompt, [(sid, name, desc) for sid, name, desc, _h in batch])
        for sid, name, _desc, h in batch:
            if sid not in answer:
                print(f"  untagged {spec} {sid} {name}")
                continue
            tags[str(sid)] = {"tags": answer[sid], "name": name, "desc_hash": h, "model": MODEL,
                              "tagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
            tagged += 1
        print(f"  {spec}: tagged {tagged} so far, {time.monotonic() - started:.0f}s")
    if dry_run:
        return
    with open(TAGS_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(tags.items(), key=lambda kv: int(kv[0]))), f, indent=1, ensure_ascii=False)
    print(f"talent tags: {len(tags)} talents ({tagged} new or re-tagged), written to {TAGS_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-minutes", type=float, default=240)
    parser.add_argument("--dry-run", action="store_true", help="print the prompts, write nothing")
    parser.add_argument("--spec", type=int, help="only this spec id (testing)")
    args = parser.parse_args()
    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST"), os.environ.get("DATABASE_USER"),
        os.environ.get("DATABASE_PASSWORD"), os.environ.get("DATABASE_NAME"),
        os.environ.get("DATABASE_PORT"), 1,
    )
    main(args.max_minutes, args.dry_run, args.spec)
