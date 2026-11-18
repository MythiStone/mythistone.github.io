"""Every retail player spell with a base cooldown of 30 s to 1 h, with its class and the specs that
have it, from the game client's DB2 tables as exported by wago.tools. Retail port of
Jods-GH/AbilityTimeline .github/Scripts/cooldownFetcher.py.

Spells come from spec spells, the class skill line and the Dragonflight+ talent trees. A spell with
charges counts its recharge time. One spell is kept per (class, name, specs): skill lines hold
variants of a spell, and a spec or talent spell wins over a skill-line one, then the lowest id.

Racials are the abilities that a race mask (the ability's, else its skill line's) limits to one race
and its variants (at most MAX_RACIAL_RACES playable races), stored as {"racial": true,
"races": [ChrRaces ids], "class": null, "specs": []}. Every distinct racial spell id is kept: one
name can have a cast id per class (Arcane Torrent, Gift of the Naaru, Blood Fury).
"""
import json
import os
from collections import defaultdict

from fetchDungeonSpells import WAGO_CSV, csv_rows, download_icon, icon_names, live_build

OUT_PATH = os.path.join("data", "static", "player_cooldowns.json")

MIN_COOLDOWN, MAX_COOLDOWN = 30000, 3600000
MIN_SPELLS = 300
MIN_RACIALS = 8
PASSIVE_ATTRIBUTE = 0x40
CLASS_SKILL_CATEGORY = "7"
# A race and its variants: Dwarf + Dark Iron, the three Pandaren, two Earthen or Dracthyr.
MAX_RACIAL_RACES = 3
SPEC_SET_CONDITION = "1"
SPEC_PRIORITY, SKILL_LINE_PRIORITY = 2, 1

TABLES = ["ChrClasses", "ChrRaces", "ChrSpecialization", "SpecializationSpells", "SkillLine", "SkillLineAbility",
          "SkillRaceClassInfo", "TraitTreeLoadout", "SpecSetMember", "TraitCond", "TraitNodeGroupXTraitCond",
          "TraitNodeGroupXTraitNode", "TraitNode", "TraitNodeXTraitNodeEntry", "TraitNodeEntry", "TraitDefinition",
          "SpellCooldowns", "SpellCategories", "SpellCategory", "SpellMisc", "SpellName"]


def number(value):
    return int(float(value or 0))


def load_tables(build):
    tables = {}
    for name in TABLES:
        tables[name] = list(csv_rows(WAGO_CSV.format(table=name, build=build)))
        if not tables[name]:
            raise RuntimeError(f"wago.tools table {name} of build {build} is empty")
    return tables


def class_spells(t):
    """spell id -> {class file name, spec ids that have it, priority}"""
    classes = {row["ID"]: row for row in t["ChrClasses"]}
    class_by_bit = {1 << (number(class_id) - 1): class_id for class_id in classes if number(class_id) > 0}
    specs_of_class = defaultdict(set)
    spec_class = {}
    for row in t["ChrSpecialization"]:
        # the "Initial" spec of characters below level 10 is no spec players plan for
        if row["ClassID"] in classes and row["ClassID"] != "0" and row["Name_lang"] != "Initial":
            specs_of_class[row["ClassID"]].add(int(row["ID"]))
            spec_class[row["ID"]] = row["ClassID"]
    spells = {}

    def add(spell_id, class_id, specs, priority):
        if not spell_id or class_id not in classes:
            return
        entry = spells.setdefault(spell_id, {"class": classes[class_id]["Filename"], "specs": set(), "priority": 0})
        entry["specs"] |= specs
        entry["priority"] = max(entry["priority"], priority)

    for row in t["SpecializationSpells"]:
        if row["SpecID"] in spec_class:
            add(number(row["SpellID"]), spec_class[row["SpecID"]], {int(row["SpecID"])}, SPEC_PRIORITY)

    # the class comes from the ability's class mask, else the line's (SkillRaceClassInfo), else its name
    class_by_name = {row["Name_lang"]: row["ID"] for row in t["ChrClasses"]}
    class_lines = {row["ID"]: row for row in t["SkillLine"] if row["CategoryID"] == CLASS_SKILL_CATEGORY}
    line_class = {}
    for row in t["SkillRaceClassInfo"]:
        class_id = class_by_bit.get(number(row["ClassMask"]))
        if row["SkillID"] in class_lines and class_id:
            line_class[row["SkillID"]] = class_id
    for row in t["SkillLineAbility"]:
        line = class_lines.get(row["SkillLine"])
        if not line:
            continue
        class_id = (class_by_bit.get(number(row["ClassMask"])) or line_class.get(row["SkillLine"])
                    or class_by_name.get(line["DisplayName_lang"]))
        if class_id:
            add(number(row["Spell"]), class_id, specs_of_class[class_id], SKILL_LINE_PRIORITY)

    # talent trees: the specs of the tree's loadouts, a node limited to a spec set only for those specs
    tree_specs = defaultdict(set)
    for row in t["TraitTreeLoadout"]:
        if row["ChrSpecializationID"] in spec_class:
            tree_specs[row["TraitTreeID"]].add(int(row["ChrSpecializationID"]))
    spec_sets = defaultdict(set)
    for row in t["SpecSetMember"]:
        spec_sets[row["SpecSet"]].add(int(row["ChrSpecializationID"]))
    cond_specs = {row["ID"]: spec_sets[row["SpecSetID"]] for row in t["TraitCond"]
                  if row["CondType"] == SPEC_SET_CONDITION and row["SpecSetID"] in spec_sets}
    group_specs = defaultdict(set)
    for row in t["TraitNodeGroupXTraitCond"]:
        if row["TraitCondID"] in cond_specs:
            group_specs[row["TraitNodeGroupID"]] |= cond_specs[row["TraitCondID"]]
    node_specs = defaultdict(set)
    for row in t["TraitNodeGroupXTraitNode"]:
        if row["TraitNodeGroupID"] in group_specs:
            node_specs[row["TraitNodeID"]] |= group_specs[row["TraitNodeGroupID"]]
    nodes = {row["ID"]: row for row in t["TraitNode"]}
    entry_nodes = defaultdict(list)
    for row in t["TraitNodeXTraitNodeEntry"]:
        entry_nodes[row["TraitNodeEntryID"]].append(row["TraitNodeID"])
    definition_spells = {row["ID"]: number(row["SpellID"]) for row in t["TraitDefinition"]}
    for row in t["TraitNodeEntry"]:
        spell_id = definition_spells.get(row["TraitDefinitionID"])
        for node_id in entry_nodes.get(row["ID"], []):
            node = nodes.get(node_id)
            if not node or not spell_id:
                continue
            specs = tree_specs.get(node["TraitTreeID"], set())
            if node_specs.get(node_id):
                specs = specs & node_specs[node_id]
            if specs:
                add(spell_id, spec_class[str(next(iter(specs)))], specs, SPEC_PRIORITY)
    return spells


def cooldowns(t):
    """spell id -> cooldown in ms, the recharge time for spells with charges"""
    result = {}
    for row in t["SpellCooldowns"]:
        if row["DifficultyID"] == "0":
            spell_id = number(row["SpellID"])
            result[spell_id] = max(result.get(spell_id, 0), number(row["RecoveryTime"]),
                                   number(row["CategoryRecoveryTime"]))
    charge_times = {row["ID"]: number(row["ChargeRecoveryTime"]) for row in t["SpellCategory"]}
    for row in t["SpellCategories"]:
        if row["DifficultyID"] == "0" and row["ChargeCategory"] in charge_times:
            spell_id = number(row["SpellID"])
            result[spell_id] = max(result.get(spell_id, 0), charge_times[row["ChargeCategory"]])
    return result


def racial_spells(t):
    """spell id -> sorted ChrRaces ids of the race-limited abilities"""
    race_by_bit = {number(row["PlayableRaceBit"]): int(row["ID"]) for row in t["ChrRaces"]
                   if number(row["PlayableRaceBit"]) >= 0}

    def races_of(row):
        mask = (number(row["RaceMasks_0"]) & (2 ** 64 - 1)) | (number(row["RaceMasks_1"]) & (2 ** 64 - 1)) << 64
        return {race for bit, race in race_by_bit.items() if mask >> bit & 1}

    line_races = defaultdict(set)
    for row in t["SkillRaceClassInfo"]:
        line_races[row["SkillID"]] |= races_of(row)
    racials = defaultdict(set)
    for row in t["SkillLineAbility"]:
        races = races_of(row) or line_races.get(row["SkillLine"], set())
        if 0 < len(races) <= MAX_RACIAL_RACES:
            racials[number(row["Spell"])] |= races
    return {spell_id: sorted(races) for spell_id, races in racials.items()}


def player_cooldowns(t):
    spells = class_spells(t)
    cooldown_of = cooldowns(t)
    passive = {number(row["SpellID"]) for row in t["SpellMisc"]
               if row["DifficultyID"] == "0" and number(row["Attributes_0"]) & PASSIVE_ATTRIBUTE}
    names = {number(row["ID"]): row["Name_lang"] for row in t["SpellName"]}
    racials = {}
    for spell_id, races in racial_spells(t).items():
        cooldown = cooldown_of.get(spell_id, 0)
        if spell_id not in passive and MIN_COOLDOWN <= cooldown <= MAX_COOLDOWN and spell_id in names:
            racials[str(spell_id)] = {"name": names[spell_id], "class": None, "cooldown_s": cooldown // 1000,
                                      "specs": [], "racial": True, "races": races}
    best = {}
    for spell_id, entry in spells.items():
        cooldown = cooldown_of.get(spell_id, 0)
        if (spell_id in passive or not MIN_COOLDOWN <= cooldown <= MAX_COOLDOWN
                or spell_id not in names or not entry["specs"]):
            continue
        key = (entry["class"], names[spell_id], tuple(sorted(entry["specs"])))
        rank = (-entry["priority"], spell_id)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, spell_id, {"name": names[spell_id], "class": entry["class"],
                                          "cooldown_s": cooldown // 1000, "specs": sorted(entry["specs"])})
    out = {str(spell_id): row for _, spell_id, row in best.values()}
    if len({row["name"] for row in racials.values()}) < MIN_RACIALS:
        raise RuntimeError(f"Only {len(racials)} racial cooldowns, the racial skill lines may have changed")
    return with_icons({**racials, **out}, t)


def with_icons(entries, t):
    """Adds each spell's icon name and downloads missing icon files, raising when one has none."""
    file_ids = {number(row["SpellID"]): row["SpellIconFileDataID"] for row in t["SpellMisc"]
                if row["DifficultyID"] == "0" and str(number(row["SpellID"])) in entries}
    icons = icon_names(file_ids)
    missing = sorted(int(spell_id) for spell_id in entries if not icons.get(int(spell_id)))
    if missing:
        raise RuntimeError(f"{len(missing)} player cooldowns have no icon: {missing}")
    failed = sorted(icon for icon in set(icons[int(spell_id)] for spell_id in entries) if not download_icon(icon))
    if failed:
        raise RuntimeError(f"{len(failed)} player cooldown icons could not be downloaded: {failed}")
    return {spell_id: {**row, "icon": icons[int(spell_id)]} for spell_id, row in entries.items()}


def main():
    build = live_build()
    print(f"Building player cooldowns from wago.tools build {build}")
    out = player_cooldowns(load_tables(build))
    if len(out) < MIN_SPELLS:
        raise RuntimeError(f"Only {len(out)} player cooldowns in build {build}, the tables may have changed")
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote {len(out)} player cooldowns to {OUT_PATH}")


if __name__ == "__main__":
    main()
