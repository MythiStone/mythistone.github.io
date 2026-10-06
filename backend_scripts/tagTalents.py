"""Weekly playstyle tags for the talents the spec page's builds differ by.

Runs in getStaticData.yml with a local Ollama model. For every spec it computes
the same builds as generateSpecPages (talentBuilds on the same DB inputs),
collects the talents in their diffs, and asks the model, one talent per prompt
and from the spell description alone, for up to two tags from
talentBuilds.BUILD_TAGS plus whether the talent is a major or minor change. Each
talent is asked up to three times and only tags at least two answers agree on
are kept. Results go to data/static/talent_tags.json ({spellId: {"tags",
"impact", "name", "version", "prompt_version", "desc", "mentions", "model",
"tagged_at"}}); the page build composes "More X, Less Y" names from them
(talentBuilds.compose_build_name), so a name always matches the build it is shown
on. data/static/talent_tag_overrides.json is reviewed by hand (the talent tags
page and its local admin build) and wins over the model while its version matches.

Descriptions come from wago.tools (Spell, with real values from SpellEffect,
SpellMisc and SpellDuration), downloaded every run because talents change between
patches. A talent's version (talent_version) ignores numbers: a new damage value
only refreshes the stored text, new wording (or a PROMPT_VERSION bump) re-tags it.

NAMER_FAKE=1 swaps the model for deterministic tags (local tests have no model);
--dry-run prints prompts and writes nothing; --eval scores the prompt against
the hand labels in localDev/talent_tag_gold*.json.
"""
import argparse
import ast
import csv
import glob
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
WAGO_BUILDS = "https://wago.tools/api/builds/latest"
FETCH_ATTEMPTS = 4
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("NAMER_MODEL", "qwen2.5:14b-instruct")
DESC_MAX_CHARS = 500
MAX_TAGS = 2
VOTES = 3              # answers per talent; the third is skipped when the first two agree
VOTE_TEMPERATURE = 0.5  # some spread between answers, or voting has nothing to vote on
SAVE_EVERY = 25        # talents between checkpoints, so a killed job keeps its progress
# Part of each talent's cache key: bump it when the prompt or tag list changes so
# the next weekly run re-tags everything.
PROMPT_VERSION = 5
MAX_REFERENCES = 3        # mentioned abilities whose description is added to a prompt
REFERENCE_MAX_CHARS = 250
# hand-labelled specs for --eval; build them with localDev/buildTalentTagAdmin.py
GOLD_GLOB = os.path.join(os.path.dirname(__file__), "localDev", "talent_tag_gold*.json")

TAG_HELP = {
    "AOE": "hits or heals several targets: cleave, chains, splash, ground effects",
    "SINGLE_TARGET": "damage aimed at one target, including buffs to an ability that hits one target",
    "EXECUTE": "damage that only works or is stronger on targets below a health threshold, only when the text names that threshold",
    "BURST": "big damage spikes or short damage cooldowns",
    "DAMAGE": "general damage increase with no clear number of targets",
    "PET_DAMAGE": "makes pets, minions, ghouls or other summons stronger or last longer, or gives them new attacks or effects",
    "SURVIVABILITY": "the player takes less damage: damage reduction, absorbs, armor, avoidance, defensive cooldowns",
    "SELF_HEALING": "heals the player, Leech, more healing received",
    "GROUP_SUPPORT": "helps allies: heals or shields them, group buffs, shared damage reduction",
    "UTILITY": "other utility no tag above covers: grips, threat, range, stealth",
    "INTERRUPT": "interrupts or silences spellcasting",
    "CC_HARD": "stuns, incapacitates or otherwise hinders enemies, and CAN NOT be broken by damage",
    "CC_SOFT": "stuns, incapacitates, disorients or otherwise hinders enemies, and CAN be broken by damage",
    "SLOW": "slows enemies",
    "ROOT": "roots enemies",
    "DISPEL": "removes magic, curse, poison, disease or enrage effects from allies or enemies (breaking free of your own roots is MOVEMENT)",
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
- Stuns all enemies within 8 yards for 3 sec. -> {"reason": "an area stun", "tags": ["CC_HARD"], "impact": "major"}
- Your pet's bites have a chance to make the target bleed for X damage over 6 sec. -> {"reason": "the pet gains a bleed", "tags": ["PET_DAMAGE"], "impact": "minor"}
- The cooldown of Consecration is reduced by 3 sec. -> {"reason": "Consecration is a ground area effect", "tags": ["AOE"], "impact": "minor"}
- Chaos Bolt deals 15% increased damage. -> {"reason": "Chaos Bolt hits one target", "tags": ["SINGLE_TARGET"], "impact": "minor"}
- Removes all root effects and increases your movement speed by 50% for 3 sec. -> {"reason": "breaks roots and runs", "tags": ["MOVEMENT"], "impact": "major"}"""

PROMPT = """You tag a World of Warcraft talent by what it does for the player in Mythic+, using only its description.
Allowed tags:
{tags}

Rules:
- Tag the main effect. A talent that changes another ability (its cooldown, cost, range, duration or charges) gets the tag of what that ability does: a cheaper resurrect is BATTLE_REZ, a faster interrupt is INTERRUPT, a longer defensive is SURVIVABILITY but one that protects the group is GROUP_SUPPORT, a faster ground area effect is AOE.
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


_LIVE_BUILD = []


def live_build():
    """The live retail client version. wago.tools serves the newest build (often
    the PTR) unless a build is named, and PTR text and numbers differ from live."""
    if not _LIVE_BUILD:
        resp = requests.get(WAGO_BUILDS, timeout=60)
        resp.raise_for_status()
        _LIVE_BUILD.append(resp.json()["wow"]["version"])
        print(f"wago.tools tables from live build {_LIVE_BUILD[0]}")
    return _LIVE_BUILD[0]


def fetch_table(table, columns):
    """Rows of a live-build wago.tools DB2 table as dicts, keeping only ``columns``."""
    for attempt in range(FETCH_ATTEMPTS):
        resp = requests.get(WAGO_CSV.format(table=table), params={"build": live_build()}, timeout=600)
        # a build-pinned table is exported on demand and the gateway times out now and then
        if resp.status_code not in (502, 503, 504) or attempt == FETCH_ATTEMPTS - 1:
            break
        print(f"wago.tools {table}: {resp.status_code}, retrying")
        time.sleep(30 * (attempt + 1))
    resp.raise_for_status()
    rows = [{c: r.get(c) for c in columns} for r in csv.DictReader(io.StringIO(resp.content.decode("utf-8")))]
    if not rows:
        raise RuntimeError(f"wago.tools {table} table came back empty")
    return rows


_TOKEN_RE = r"\$(\d*)([A-Za-z])(\d?)"
_ARITH_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)
# $?a137020[Frost text]?c1[Arcane text][otherwise]: a chain of conditions, then an optional else.
# Blizzard sometimes types "$?a1][x][y]", and $@switch<2>[one][two] picks by a value we lack.
_COND_HEAD = re.compile(r"(?:\$@switch<[^>]*>|\$?\?([^\[\]\s]*)\]?)\s*\[")
_COND_NEXT = re.compile(r"\s*\?([^\[\]\s]*)\]?\s*\[")
_COND_ELSE = re.compile(r"\s*\[")


def _branch(text, start):
    """(content, end) of the bracket opening at text[start], nested brackets included."""
    depth = 0
    for i in range(start, len(text)):
        depth += {"[": 1, "]": -1}.get(text[i], 0)
        if depth == 0:
            return text[start + 1:i], i + 1
    return text[start + 1:], len(text)  # Blizzard typo: unclosed, keep the rest


class SpellText:
    """Spell descriptions as one spec reads them: $s1 / $d / $t1 values filled in
    from the live client data, so the model sees '30% for 8 sec' instead of
    'X% for X', and $?c3[Frost][Arcane] conditions resolved for that spec."""

    def __init__(self):
        self.raw = {int(r["ID"]): r["Description_lang"]
                    for r in fetch_table("Spell", ["ID", "Description_lang"]) if r["Description_lang"]}
        radii = {int(r["ID"]): float(r["Radius"] or 0) for r in fetch_table("SpellRadius", ["ID", "Radius"])}
        self.effects, self.periods, self.radii = {}, {}, {}
        for r in fetch_table("SpellEffect", ["SpellID", "EffectIndex", "DifficultyID", "EffectBasePointsF",
                                             "EffectAuraPeriod", "EffectRadiusIndex_0", "EffectRadiusIndex_1"]):
            if r["DifficultyID"] != "0":
                continue
            key = (int(r["SpellID"]), int(r["EffectIndex"]))
            self.effects[key] = float(r["EffectBasePointsF"] or 0)
            self.periods[key] = int(r["EffectAuraPeriod"] or 0)
            # the radius sits in either slot (the second is the max radius)
            self.radii[key] = radii.get(int(r["EffectRadiusIndex_0"] or 0)) or radii.get(int(r["EffectRadiusIndex_1"] or 0), 0)
        self.stacks, self.proc_cooldowns = {}, {}
        for r in fetch_table("SpellAuraOptions", ["SpellID", "DifficultyID", "CumulativeAura", "ProcCategoryRecovery"]):
            if r["DifficultyID"] == "0":
                self.stacks[int(r["SpellID"])] = int(r["CumulativeAura"] or 0)
                self.proc_cooldowns[int(r["SpellID"])] = int(r["ProcCategoryRecovery"] or 0)
        self.names, self.name_ids = {}, {}
        for r in fetch_table("SpellName", ["ID", "Name_lang"]):
            self.names[int(r["ID"])] = r["Name_lang"]
            self.name_ids.setdefault(r["Name_lang"], []).append(int(r["ID"]))
        # the class a player spell belongs to (NPC copies of a name have none)
        self.class_set = {int(r["SpellID"]): int(r["SpellClassSet"])
                          for r in fetch_table("SpellClassOptions", ["SpellID", "SpellClassSet"])}
        durations = {int(r["ID"]): int(r["Duration"]) for r in fetch_table("SpellDuration", ["ID", "Duration"])}
        self.durations = {}
        for r in fetch_table("SpellMisc", ["SpellID", "DifficultyID", "DurationIndex"]):
            if r["DifficultyID"] == "0" and r["DurationIndex"] not in (None, "", "0"):
                self.durations[int(r["SpellID"])] = durations.get(int(r["DurationIndex"]), 0)
        # $?c3 is the spec's 1-based place in its class
        self.spec_index = {int(r["ID"]): int(r["OrderIndex"]) + 1
                           for r in fetch_table("ChrSpecialization", ["ID", "OrderIndex"])}
        self.spec_spells = {}  # spec auras and baseline spells, e.g. 137020 for Frost Mage
        for r in fetch_table("SpecializationSpells", ["SpecID", "SpellID"]):
            self.spec_spells.setdefault(int(r["SpecID"]), set()).add(int(r["SpellID"]))

    @staticmethod
    def _num(value):
        value = abs(value)
        return f"{value:g}"

    @classmethod
    def _seconds(cls, sec):
        """'15 sec', '2 min' or '1 hour', the way the game words durations."""
        if sec >= 3600 and sec % 3600 == 0:
            n = sec // 3600
            return f"{n:g} hour" + ("s" if n != 1 else "")
        if sec >= 60 and sec % 60 == 0:
            return f"{sec // 60:g} min"
        return f"{cls._num(sec)} sec"

    def _number(self, spell, match):
        """What an $s1 / $a1 / $t1 / $d / $u token (or $123s1) stands for, durations
        in seconds, or None when the client data has no value for it."""
        sid = int(match.group(1)) if match.group(1) else spell
        kind, idx = match.group(2).lower(), match.group(3)
        key = (sid, int(idx) - 1 if idx else 0)
        if kind in "smw":
            return self.effects.get(key) if idx else None
        if kind == "a":
            return self.radii.get(key) or None
        if kind == "t":
            return self.periods.get(key, 0) / 1000 or None
        if kind == "d":
            ms = self.durations.get(sid, 0)
            return ms / 1000 if ms > 0 else None
        if kind == "u":
            return self.stacks.get(sid) or None
        return None

    def _value(self, spell, match):
        # 0 base points mean the value scales with attack or spell power: X, not "deals 0 damage"
        v = self._number(spell, match)
        if not v:
            return "X"
        return self._seconds(v) if match.group(2).lower() == "d" else self._num(v)

    def _proc_cooldown(self, spell):
        ms = self.proc_cooldowns.get(spell, 0)
        return self._num(ms / 1000) if ms else "X"

    def _formula(self, spell, match):
        """A ${$s1/-1000} formula computed from the token values, or X when it uses
        anything but token values and plain arithmetic."""
        values = [self._number(spell, m) for m in re.finditer(_TOKEN_RE, match.group(1))]
        if None in values:
            return "X"
        it = iter(values)
        expr = re.sub(_TOKEN_RE, lambda _m: f"({next(it)})", match.group(1))
        try:
            tree = ast.parse(expr, mode="eval")
            if not all(isinstance(n, _ARITH_NODES) for n in ast.walk(tree)):
                return "X"
            value = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}})
        except (SyntaxError, ZeroDivisionError):
            return "X"
        return self._num(round(value, 2)) if value else "X"

    def _has(self, spec, spell):
        """Whether ``spec`` has ``spell`` for a $?a / $?s condition. Only the spec's
        own spells count: like an untalented Wowhead tooltip, optional talents,
        forms, glyphs, set bonuses and other specs' spells read as absent, so the
        description shows the base version."""
        return spell in self.spec_spells.get(spec, ())

    def _condition(self, expr, spec):
        """A condition like a137020&!c1 for ``spec``. Unknown forms ($owb==2,
        pet checks) count as true, which keeps the first branch."""
        expr = re.sub(r"[\s$?]", "", expr or "")
        if not expr or not re.fullmatch(r"[!&|()A-Za-z0-9]+", expr):
            return True
        known = True

        def atom(m):
            nonlocal known
            kind, n = m.group(1).lower(), int(m.group(2))
            if kind == "c":
                return f" {n == self.spec_index[spec]} "
            if kind in "as":
                return f" {self._has(spec, n)} "
            known = False
            return " True "
        py = re.sub(r"([A-Za-z])(\d+)", atom, expr).replace("&", " and ").replace("|", " or ").replace("!", " not ")
        if not known or re.search(r"[A-Za-z0-9]", re.sub(r"True|False|and|or|not", "", py)):
            return True
        try:
            return bool(eval(py, {"__builtins__": {}}))
        except SyntaxError:
            return True

    def _conditions(self, text, spec):
        """Text with every $?cond[...]?cond[...][...] chain replaced by the first
        branch whose condition holds for ``spec``, else the else branch."""
        out, pos = [], 0
        while m := _COND_HEAD.search(text, pos):
            out.append(text[pos:m.start()])
            chosen = None
            while m:
                body, pos = _branch(text, m.end() - 1)
                if chosen is None and self._condition(m.group(1), spec):
                    chosen = body
                m = _COND_NEXT.match(text, pos)
            if e := _COND_ELSE.match(text, pos):
                body, pos = _branch(text, e.end() - 1)
                chosen = body if chosen is None else chosen
            out.append(self._conditions(chosen or "", spec))
        out.append(text[pos:])
        return "".join(out)

    def render(self, spell, spec, depth=0):
        """The description of ``spell`` as a player of ``spec`` reads it."""
        text = self.raw.get(spell, "")
        if depth == 0:
            # a talent that grants an ability often only links its description
            text = re.sub(r"\$@spell(?:desc|tooltip)(\d+)", lambda m: " " + self.render(int(m.group(1)), spec, 1), text)
        text = re.sub(r"\$@spellname(\d+)", lambda m: self.names.get(int(m.group(1)), ""), text)
        text = re.sub(r"\$@spell\w*?\d+", "", text)
        text = re.sub(r"\|c[0-9A-F]{8}|\|r", "", text, flags=re.IGNORECASE)
        # $lstack:stacks; picks by the number before it, known only once values are in
        text = re.sub(r"\$[lL]([^:;]+):([^;]+);", "\x00\\1\x01\\2\x02", text)
        text = self._conditions(text, spec)
        text = re.sub(r"\$/(\d+);(\d*[A-Za-z]\d?)", r"${$\2/\1}", text)       # $/1000;s1 is $s1 / 1000
        text = re.sub(r"\$\{([^}]*)\}(?:\.\d)?", lambda m: self._formula(spell, m), text)  # ".1" is a decimals format
        text = re.sub(r"\$<[^>]*>", "X", text)                            # variables
        text = re.sub(r"\$(\d*)proccooldown", lambda m: self._proc_cooldown(int(m.group(1) or spell)), text)
        text = re.sub(_TOKEN_RE, lambda m: self._value(spell, m), text)
        text = re.sub(r"(?<![\d.])1(\s+(?:\w+\s+)?)\x00([^\x01]*)\x01[^\x02]*\x02", r"1\1\2", text)
        text = re.sub(r"\x00[^\x01]*\x01([^\x02]*)\x02", r"\1", text)
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


def referenced_abilities(text, description, own_name, class_name, spec):
    """[{id, name, desc}] for abilities a talent's text mentions, so a talent that
    modifies Anti-Magic Zone is tagged by what Anti-Magic Zone does (mentions_prompt)
    and the talent tags page can show them.
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
    mentions = []
    for name, sid in found.items():
        desc = text.render(sid, spec)[:REFERENCE_MAX_CHARS]
        if desc:
            mentions.append({"id": sid, "name": name, "desc": desc})
    return mentions


def mentions_prompt(mentions):
    """The prompt's '- Name: description' block for referenced_abilities' output."""
    lines = [f"- {m['name']}: {m['desc']}" for m in mentions]
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


def build_prompt(description, mentions=()):
    return PROMPT.format(
        max_tags=MAX_TAGS, examples=EXAMPLES, description=description or "no description",
        references=mentions_prompt(mentions),
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


def tag_talent(spell_id, description, mentions=()):
    """(tags, major, reason) voted over up to VOTES answers, or None if the model
    gave no usable answer. A tag survives when at least two answers give it."""
    if os.environ.get("NAMER_FAKE") == "1":
        tags = list(talentBuilds.BUILD_TAGS)
        return [tags[spell_id % len(tags)]], spell_id % 2 == 0, "fake"
    prompt = build_prompt(description, mentions)
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


def gold_files():
    """[(path, [spec docs], is_list)] for localDev/talent_tag_gold*.json. A file
    holds one spec ({"spec", "tags"}) or a list of them."""
    out = []
    for path in sorted(glob.glob(GOLD_GLOB)):
        data = commonUtils.load_json(path)
        out.append((path, data if isinstance(data, list) else [data], isinstance(data, list)))
    if not out:
        raise RuntimeError(f"no gold files match {GOLD_GLOB}")
    return out


def evaluate(text):
    """Scores the prompt against every hand-labelled spec (localDev/talent_tag_gold*.json)."""
    for gold in (doc for _path, docs, _is_list in gold_files() for doc in docs):
        class_name = commonUtils.load_json(
            os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{gold['spec']}.json"))["className"]
        exact = overlap = impact_ok = impact_n = 0
        extra, missing = Counter(), Counter()
        for sid, g in gold["tags"].items():
            want = set(g["tags"])
            desc = text.render(int(sid), gold["spec"])[:DESC_MAX_CHARS]
            mentions = referenced_abilities(text, desc, g["name"], class_name, gold["spec"])
            if mentions:
                print(f"  {g['name']} mentions:\n    " + mentions_prompt(mentions).strip().replace("\n", "\n    "))
            result = tag_talent(int(sid), desc, mentions)
            got, major, reason = result if result else ([], False, "no answer")
            got = set(got)
            exact += got == want
            hit = bool(got & want) or got == want
            overlap += hit
            extra.update(got - want)
            missing.update(want - got)
            impact = "major" if major else "minor"
            impact_mark = ""
            if g.get("impact"):
                impact_n += 1
                impact_ok += impact == g["impact"]
                impact_mark = "" if impact == g["impact"] else f" (gold {g['impact']})"
            mark = "ok  " if got == want else "part" if hit else "MISS"
            print(f"  eval {mark} {g['name']}: model {sorted(got)} {impact}{impact_mark} vs {sorted(want)} ({reason})")
        n = len(gold["tags"])
        print(f"tag eval spec {gold['spec']}: {exact}/{n} exact, {overlap}/{n} at least one right, "
              f"impact {impact_ok}/{impact_n}")
        print(f"  over-tagged: {dict(extra.most_common())}\n  under-tagged: {dict(missing.most_common())}")


def check_model():
    if os.environ.get("NAMER_FAKE") == "1":
        return
    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=30)
    tags.raise_for_status()
    if not any(m.get("name", "").startswith(MODEL) for m in tags.json().get("models", [])):
        raise RuntimeError(f"Ollama at {OLLAMA_URL} does not have {MODEL}; run `ollama pull {MODEL}`")


def talent_version(desc):
    """What a talent does, ignoring its numbers: the same version survives a damage
    or cooldown tweak, new wording is a new version. Tags and overrides are tied to it."""
    masked = re.sub(r"\d+(?:\.\d+)?|\bX\b", "#", desc)
    return hashlib.sha1(masked.encode("utf-8")).hexdigest()[:16]


def save(tags):
    tmp = TAGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(tags.items(), key=lambda kv: int(kv[0]))), f, indent=1, ensure_ascii=False)
    os.replace(tmp, TAGS_PATH)


def backfill(text):
    """Adds desc, mentions and version to tag entries that lack them, without the DB or
    the model, rendered for the first spec whose tree has the talent (the weekly run
    renders for the first spec whose builds change it, so a rare talent may differ).
    Their tags stay and so does their missing prompt_version: the next run re-tags them."""
    tags = commonUtils.load_json(TAGS_PATH)
    owners = {}
    for spec_id in sorted(text.spec_index):
        path = os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{spec_id}.json")
        if not os.path.exists(path):
            continue
        lookup = commonUtils.load_json(path)
        for node in lookup["nodes"].values():
            for e in node.get("entries") or []:
                if e.get("spellId"):
                    owners.setdefault(str(e["spellId"]), (spec_id, lookup["className"]))
    filled = 0
    for sid, entry in tags.items():
        if (entry.get("desc") and "mentions" in entry) or sid not in owners:
            continue
        spec_id, class_name = owners[sid]
        desc = text.render(int(sid), spec_id)[:DESC_MAX_CHARS]
        entry.pop("refs", None)  # the old text form of mentions
        entry.update(desc=desc, version=talent_version(desc),
                     mentions=referenced_abilities(text, desc, entry["name"], class_name, spec_id))
        filled += 1
    save(tags)
    print(f"talent tags: text and version added to {filled} of {len(tags)} talents")


def main(max_minutes, dry_run, only_spec):
    started = time.monotonic()
    check_model()
    text = SpellText()
    old = commonUtils.load_json(TAGS_PATH) if os.path.exists(TAGS_PATH) else {}
    season = commonUtils.current_season_id()
    dungeon_ids = {int(k) for k in commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "dungeons.json"))}
    spec_lookup = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "specs.json"))

    # a talent shared by several specs is asked once, with the first spec's text
    pending = {}  # spell_id -> (name, description, mentions, version)
    tags = dict(old)  # earlier tags are kept: a talent that drops out of this week's builds can return
    refreshed = 0
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
                desc = text.render(sid, int(spec_id))[:DESC_MAX_CHARS]
                mentions = referenced_abilities(text, desc, name, lookup["className"], int(spec_id))
                version = talent_version(desc)
                cached = tags.get(str(sid))
                if (not cached or cached.get("version") != version
                        or cached.get("prompt_version") != PROMPT_VERSION):
                    pending[sid] = (name, desc, mentions, version)
                    if cached:
                        # the talents page shows current text even if the time box ends first;
                        # no prompt_version keeps it pending for the next run
                        cached.update(desc=desc, mentions=mentions, version=version)
                        cached.pop("prompt_version", None)
                        cached.pop("refs", None)
                elif (cached["desc"], cached.get("mentions")) != (desc, mentions):
                    # same talent, new numbers: keep its tags, show the current text
                    cached.update(desc=desc, mentions=mentions)
                    cached.pop("refs", None)
                    refreshed += 1
    finally:
        conn.close()

    print(f"{len(pending)} talents to tag, {refreshed} with new numbers only")
    if dry_run:
        for sid, (name, desc, mentions, _h) in list(pending.items())[:3]:
            print(f"--- {sid} {name}\n{build_prompt(desc, mentions)}")
        return
    tagged = 0
    for n, (sid, (name, desc, mentions, version)) in enumerate(sorted(pending.items())):
        if time.monotonic() - started > max_minutes * 60:
            print(f"time box of {max_minutes} min reached; {len(pending) - n} talents stay untagged until next run")
            break
        result = tag_talent(sid, desc, mentions)
        if result is None:
            print(f"  untagged {sid} {name}: no usable answer")
            continue
        found, major, reason = result
        tags[str(sid)] = {"tags": found, "impact": "major" if major else "minor", "name": name,
                          "version": version, "prompt_version": PROMPT_VERSION, "desc": desc, "mentions": mentions,
                          "model": MODEL, "tagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
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
    parser.add_argument("--eval", action="store_true", help="score the prompt against localDev/talent_tag_gold*.json")
    parser.add_argument("--backfill", action="store_true",
                        help="add text and version to entries lacking them (no DB, no model)")
    args = parser.parse_args()
    if args.eval:  # scores the prompt only; needs no database
        check_model()
        evaluate(SpellText())
        raise SystemExit(0)
    if args.backfill:
        backfill(SpellText())
        raise SystemExit(0)
    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST"), os.environ.get("DATABASE_USER"),
        os.environ.get("DATABASE_PASSWORD"), os.environ.get("DATABASE_NAME"),
        os.environ.get("DATABASE_PORT"), 1,
    )
    main(args.max_minutes, args.dry_run, args.spec)
