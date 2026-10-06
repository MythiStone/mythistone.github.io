"""Weekly playstyle tags for the talents the spec page's builds differ by.

Runs in getStaticData.yml with a local Ollama model. For every spec it computes
the same builds as generateSpecPages (talentBuilds on the same DB inputs),
collects the talents in their diffs, and asks the model, one talent per prompt
and from the spell description alone, for up to two tags from
talentBuilds.BUILD_TAGS plus whether the talent is a major or minor change. Each
talent is asked up to three times and only tags at least two answers agree on
are kept. Results go to data/static/talent_tags.json ({spellId: {"tags",
"impact", "name", "desc_hash", "model", "tagged_at"}}); the page build composes
"More X, Less Y" names from them (talentBuilds.compose_build_name), so a name
always matches the build it is shown on. data/static/talent_tag_overrides.json
is hand-maintained and wins over the model.

Descriptions come from wago.tools (Spell, with real values from SpellEffect,
SpellMisc and SpellDuration), downloaded every run because talents change between
patches: a talent is re-tagged whenever its rendered description changes (or
PROMPT_VERSION is bumped).

NAMER_FAKE=1 swaps the model for deterministic tags (local tests have no model);
--dry-run prints prompts and writes nothing; --eval scores the prompt against
localDev/talent_tag_gold.json.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone

import requests

import commonUtils
import databaseConnector
import talentBuilds

TAGS_PATH = os.path.join(commonUtils.LOOKUP_DIR, "talent_tags.json")
WAGO_CSV = "https://wago.tools/db2/{table}/csv"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("NAMER_MODEL", "qwen2.5:14b-instruct")
DESC_MAX_CHARS = 500
MAX_TAGS = 2
VOTES = 3              # answers per talent; the third is skipped when the first two agree
VOTE_TEMPERATURE = 0.5  # some spread between answers, or voting has nothing to vote on
SAVE_EVERY = 25        # talents between checkpoints, so a killed job keeps its progress
# Part of each talent's cache key: bump it when the prompt or tag list changes so
# the next weekly run re-tags everything.
PROMPT_VERSION = 4
MAX_REFERENCES = 3        # mentioned abilities whose description is added to a prompt
REFERENCE_MAX_CHARS = 250
GOLD_PATH = os.path.join(os.path.dirname(__file__), "localDev", "talent_tag_gold.json")

TAG_HELP = {
    "AOE": "hits or heals several targets: cleave, chains, splash, ground effects",
    "SINGLE_TARGET": "damage aimed at one target",
    "EXECUTE": "damage that only works or is stronger on targets below a certain threshold of health",
    "BURST": "big damage spikes or short damage cooldowns",
    "DAMAGE": "general damage increase with no clear number of targets",
    "PET_DAMAGE": "makes pets, minions, ghouls or other summons stronger or last longer",
    "SURVIVABILITY": "the player takes less damage: damage reduction, absorbs, armor, avoidance, defensive cooldowns",
    "SELF_HEALING": "heals the player, Leech, more healing received",
    "GROUP_SUPPORT": "helps allies: heals or shields them, group buffs, shared damage reduction",
    "UTILITY": "other utility no tag above covers: grips, threat, range, stealth",
    "INTERRUPT": "interrupts or silences spellcasting",
    "CC_HARD": "stuns, incapacitates or otherwise hinders enemies, and CAN NOT be broken by damage",
    "CC_SOFT": "stuns, incapacitates, disorients or otherwise hinders enemies, and CAN be broken by damage",
    "SLOW": "slows enemies",
    "ROOT": "roots enemies",
    "DISPEL": "removes magic, curse, poison, disease or enrage effects",
    "BATTLE_REZ": "resurrects an ally in combat",
    "MOVEMENT": "movement speed, dashes, teleports, freedom from roots",
}
assert set(TAG_HELP) == set(talentBuilds.BUILD_TAGS), "TAG_HELP and talentBuilds.BUILD_TAGS must list the same tags"

EXAMPLES = """- Your Ice Lance deals 5% increased damage and hits a second nearby target. -> {"reason": "hits an extra target", "tags": ["AOE"], "impact": "minor"}
- Kill Command has 1 additional charge and your pet deals 15% increased damage. -> {"reason": "Kill Command is the pet's attack", "tags": ["PET_DAMAGE"], "impact": "major"}
- Intercession costs 1 less Holy Power. -> {"reason": "cheaper in-combat resurrect", "tags": ["BATTLE_REZ"], "impact": "minor"}
- Reduces the cooldown of Kick by 2 sec. -> {"reason": "Kick is an interrupt", "tags": ["INTERRUPT"], "impact": "minor"}
- Increases your Armor by 6% and reduces damage taken from area of effect attacks by 4%. -> {"reason": "passive damage reduction", "tags": ["SURVIVABILITY"], "impact": "minor"}
- Become immune to all damage for 8 sec. 5 min cooldown. -> {"reason": "an immunity cooldown", "tags": ["SURVIVABILITY"], "impact": "major"}
- Increases Leech by 3%. -> {"reason": "Leech heals the player", "tags": ["SELF_HEALING"], "impact": "minor"}
- Rallying Cry increases the maximum health of party members by 10% for 10 sec. -> {"reason": "buffs the whole party", "tags": ["GROUP_SUPPORT"], "impact": "major"}
- Your damage dealt is increased by 3% while you are above 80% health. -> {"reason": "plain damage increase", "tags": ["DAMAGE"], "impact": "minor"}
- Ignore Pain costs 5 less Rage and absorbs 10% more damage. -> {"reason": "Ignore Pain is a defensive; the cost is a side detail", "tags": ["SURVIVABILITY"], "impact": "minor"}
- Execute deals 20% more damage to enemies below 35% health. -> {"reason": "bonus on low health targets", "tags": ["EXECUTE"], "impact": "minor"}
- Stuns all enemies within 8 yards for 3 sec. -> {"reason": "an area stun", "tags": ["CC_HARD"], "impact": "major"}"""

PROMPT = """You tag a World of Warcraft talent by what it does for the player in Mythic+, using only its description.
Allowed tags:
{tags}

Rules:
- Tag the main effect. A talent that changes another ability (its cooldown, cost, range, duration or charges) gets the tag of what that ability does: a cheaper resurrect is BATTLE_REZ, a faster interrupt is INTERRUPT, a longer defensive is SURVIVABILITY.
- Gaining or saving a resource is not a tag of its own: tag what the talent achieves, or use no tag.
- Use 0 to {max_tags} tags. No tag is fine for a tiny or unclear effect.
- "Abilities it mentions" only explain what a modified ability does; tag the talent itself.
- impact is "major" for a new ability, a cooldown or an effect that clearly changes how the spec plays, and "minor" for a small passive bonus or a tweak to an existing ability.

Examples:
{examples}

Talent:
{description}
{references}
Write a short reason, then the tags and the impact.
Respond with JSON only: {{"reason": "<a few words>", "tags": ["TAG", ...], "impact": "major" or "minor"}}
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
        self.name_ids = {}
        for r in fetch_table("SpellName", ["ID", "Name_lang"]):
            self.name_ids.setdefault(r["Name_lang"], []).append(int(r["ID"]))
        # the class a player spell belongs to (NPC copies of a name have none)
        self.class_set = {int(r["SpellID"]): int(r["SpellClassSet"])
                          for r in fetch_table("SpellClassOptions", ["SpellID", "SpellClassSet"])}
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
        text = re.sub(r"\$?\?[^\[\s]*\[", " ", text)                # conditional heads ($?s123[, ?c3[, $?a1&!c1[)
        text = re.sub(r"\]\s*\[[^\]]*\]", "", text).replace("]", "")  # keep the first branch
        text = re.sub(r"\$\{[^}]*\}|\$<[^>]*>", "X", text)            # formulas and variables
        text = re.sub(r"\$(\d*)([A-Za-z])(\d?)", lambda m: self._value(spell, m), text)
        return re.sub(r"\s+", " ", text).strip()


_CLASS_SPELLS = {}
# resources share their name with a spell ("Gain X Runic Power"), but are not abilities
RESOURCE_NAMES = {
    "Runic Power", "Runes", "Rage", "Mana", "Energy", "Focus", "Fury", "Pain", "Insanity",
    "Maelstrom", "Holy Power", "Astral Power", "Lunar Power", "Chi", "Combo Points",
    "Soul Shards", "Arcane Charges", "Essence",
}
_PHRASE_RE = re.compile(r"[A-Z][\w'-]*(?:[ ](?:of|the|and|[A-Z][\w'-]*))*")


def class_spells(class_name):
    """{talent name: spellId} over every spec's talent file of a class."""
    if class_name not in _CLASS_SPELLS:
        out = {}
        talent_dir = os.path.join(commonUtils.LOOKUP_DIR, "talents")
        for fname in sorted(os.listdir(talent_dir)):
            doc = commonUtils.load_json(os.path.join(talent_dir, fname))
            if doc.get("className") != class_name:
                continue
            for node in (doc.get("nodes") or {}).values():
                for e in node.get("entries") or []:
                    if e.get("name") and e.get("spellId"):
                        out.setdefault(e["name"], int(e["spellId"]))
        _CLASS_SPELLS[class_name] = out
    return _CLASS_SPELLS[class_name]


def referenced_abilities(text, description, own_name, class_name):
    """'- Name: description' lines for abilities a talent's text mentions, so a
    talent that modifies Anti-Magic Zone is tagged by what Anti-Magic Zone does.
    A one-word name only counts when it is a class talent (plain capitalised words
    like "Damage" are spell names too); longer names may be any of the class's
    spells (SpellClassOptions class set), using the lowest such id with a
    description. Resource names are never abilities."""
    known = class_spells(class_name)
    # the class's spell family: the class set most of its talents carry
    sets = Counter(text.class_set.get(i) for i in known.values() if text.class_set.get(i))
    family = sets.most_common(1)[0][0] if sets else None
    found = {}
    for phrase in _PHRASE_RE.findall(description):
        words = phrase.split(" ")
        # longest sub-phrase first, so "Death and Decay" wins over "Death"
        for size in range(len(words), 0, -1):
            hit = None
            for start in range(len(words) - size + 1):
                name = " ".join(words[start:start + size])
                if (name == own_name or name in found or name in RESOURCE_NAMES
                        or name.lower() in ("of", "the", "and")):
                    continue
                if name in known:
                    hit = (name, known[name])
                elif size > 1 and family is not None:
                    # only this class's version of the spell: other ids are NPC or old copies
                    ids = [i for i in sorted(text.name_ids.get(name, ()))
                           if text.raw.get(i) and text.class_set.get(i) == family]
                    if ids:
                        hit = (name, ids[0])
                if hit:
                    break
            if hit:
                found[hit[0]] = hit[1]
                break
        if len(found) >= MAX_REFERENCES:
            break
    lines = []
    for name, sid in found.items():
        desc = text.render(sid)[:REFERENCE_MAX_CHARS]
        if desc:
            lines.append(f"- {name}: {desc}")
    return ("Abilities it mentions:\n" + "\n".join(lines) + "\n") if lines else ""


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


def build_prompt(description, references=""):
    return PROMPT.format(
        max_tags=MAX_TAGS, examples=EXAMPLES, description=description or "no description",
        references=references,
        tags="\n".join(f"- {t}: {h}" for t, h in TAG_HELP.items()),
    )


def parse_answer(raw):
    """(tags, major, reason) from one model reply, or None when unusable."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    # models sometimes nest the answer one level under an id or a "talent" key
    if isinstance(data, dict) and "tags" not in data and len(data) == 1:
        inner = next(iter(data.values()))
        data = inner if isinstance(inner, dict) else data
    if not isinstance(data, dict):
        return None
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        return None
    tags = [str(t).strip().upper() for t in tags]
    tags = list(dict.fromkeys(t for t in tags if t in talentBuilds.BUILD_TAGS))[:MAX_TAGS]
    major = str(data.get("impact", "")).strip().lower() == "major"
    return tags, major, str(data.get("reason") or "")


def ask_once(prompt, seed):
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": MODEL, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": VOTE_TEMPERATURE, "seed": seed, "num_ctx": 4096},
    }, timeout=1800)
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    answer = parse_answer(raw)
    if answer is None:
        print(f"  unusable model reply: {raw[:200]!r}")
    return answer


def tag_talent(spell_id, description, references=""):
    """(tags, major, reason) voted over up to VOTES answers, or None if the model
    gave no usable answer. A tag survives when at least two answers give it."""
    if os.environ.get("NAMER_FAKE") == "1":
        tags = list(talentBuilds.BUILD_TAGS)
        return [tags[spell_id % len(tags)]], spell_id % 2 == 0, "fake"
    prompt = build_prompt(description, references)
    answers = []
    for seed in range(VOTES):
        answer = ask_once(prompt, seed)
        if answer is not None:
            answers.append(answer)
        if len(answers) == 2 and set(answers[0][0]) == set(answers[1][0]) and answers[0][1] == answers[1][1]:
            break
    if not answers:
        return None
    if len(answers) == 1:
        return answers[0]
    need = 2
    counts = Counter(t for tags, _major, _reason in answers for t in tags)
    tags = [t for t in talentBuilds.BUILD_TAGS if counts[t] >= need][:MAX_TAGS]
    major = sum(major for _tags, major, _reason in answers) >= need
    return tags, major, answers[0][2]


def evaluate(text):
    """Scores the prompt against hand labels (localDev/talent_tag_gold.json)."""
    gold = commonUtils.load_json(GOLD_PATH)
    class_name = commonUtils.load_json(
        os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{gold['spec']}.json"))["className"]
    exact = overlap = 0
    for sid, g in gold["tags"].items():
        want = set(g["tags"])
        desc = text.render(int(sid))[:DESC_MAX_CHARS]
        refs = referenced_abilities(text, desc, g["name"], class_name)
        if refs:
            print(f"  {g['name']} mentions:\n    " + refs.strip().replace("\n", "\n    "))
        result = tag_talent(int(sid), desc, refs)
        got, major, reason = result if result else ([], False, "no answer")
        got = set(got)
        exact += got == want
        hit = bool(got & want) or got == want
        overlap += hit
        mark = "ok  " if got == want else "part" if hit else "MISS"
        print(f"  eval {mark} {g['name']}: model {sorted(got)} {'major' if major else 'minor'} vs {sorted(want)} ({reason})")
    n = len(gold["tags"])
    print(f"tag eval: {exact}/{n} exact, {overlap}/{n} at least one right")


def check_model():
    if os.environ.get("NAMER_FAKE") == "1":
        return
    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=30)
    tags.raise_for_status()
    if not any(m.get("name", "").startswith(MODEL) for m in tags.json().get("models", [])):
        raise RuntimeError(f"Ollama at {OLLAMA_URL} does not have {MODEL}; run `ollama pull {MODEL}`")


def save(tags):
    tmp = TAGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(tags.items(), key=lambda kv: int(kv[0]))), f, indent=1, ensure_ascii=False)
    os.replace(tmp, TAGS_PATH)


def main(max_minutes, dry_run, only_spec):
    started = time.monotonic()
    check_model()
    text = SpellText()
    old = commonUtils.load_json(TAGS_PATH) if os.path.exists(TAGS_PATH) else {}
    season = commonUtils.current_season_id()
    dungeon_ids = {int(k) for k in commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "dungeons.json"))}
    spec_lookup = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "specs.json"))

    # tags depend only on the description, so a talent shared by several specs is asked once
    pending = {}  # spell_id -> (name, description, references, desc_hash)
    conn = databaseConnector.get_connection()
    try:
        cursor = conn.cursor()
        for spec_id in sorted(spec_lookup, key=int):
            if only_spec and int(spec_id) != only_spec:
                continue
            if not os.path.exists(os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{spec_id}.json")):
                continue
            lookup, trees = spec_trees(conn, cursor, int(spec_id), season, dungeon_ids)
            for sid, name in diff_talents(trees, lookup["nodes"]).items():
                if sid in pending:
                    continue
                desc = text.render(sid)[:DESC_MAX_CHARS]
                refs = referenced_abilities(text, desc, name, lookup["className"])
                h = hashlib.sha1(f"{PROMPT_VERSION}|{desc}|{refs}".encode("utf-8")).hexdigest()[:16]
                cached = old.get(str(sid))
                if not (cached and cached.get("desc_hash") == h):
                    pending[sid] = (name, desc, refs, h)
    finally:
        conn.close()

    print(f"{len(pending)} talents to tag")
    if dry_run:
        for sid, (name, desc, refs, _h) in list(pending.items())[:3]:
            print(f"--- {sid} {name}\n{build_prompt(desc, refs)}")
        return
    # earlier tags are kept: a talent that drops out of this week's builds can return
    tags = dict(old)
    tagged = 0
    for n, (sid, (name, desc, refs, h)) in enumerate(sorted(pending.items())):
        if time.monotonic() - started > max_minutes * 60:
            print(f"time box of {max_minutes} min reached; {len(pending) - n} talents stay untagged until next run")
            break
        result = tag_talent(sid, desc, refs)
        if result is None:
            print(f"  untagged {sid} {name}: no usable answer")
            continue
        found, major, reason = result
        tags[str(sid)] = {"tags": found, "impact": "major" if major else "minor", "name": name,
                          "desc_hash": h, "model": MODEL,
                          "tagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        tagged += 1
        print(f"  {name}: {found} {'major' if major else 'minor'} ({reason}) [{time.monotonic() - started:.0f}s]")
        if tagged % SAVE_EVERY == 0:
            save(tags)
    save(tags)
    print(f"talent tags: {len(tags)} talents ({tagged} new or re-tagged), written to {TAGS_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-minutes", type=float, default=300)
    parser.add_argument("--dry-run", action="store_true", help="print a few prompts, write nothing")
    parser.add_argument("--spec", type=int, help="only this spec id (testing)")
    parser.add_argument("--eval", action="store_true", help="score the prompt against localDev/talent_tag_gold.json")
    args = parser.parse_args()
    if args.eval:  # scores the prompt only; needs no database
        check_model()
        evaluate(SpellText())
        raise SystemExit(0)
    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST"), os.environ.get("DATABASE_USER"),
        os.environ.get("DATABASE_PASSWORD"), os.environ.get("DATABASE_NAME"),
        os.environ.get("DATABASE_PORT"), 1,
    )
    main(args.max_minutes, args.dry_run, args.spec)
