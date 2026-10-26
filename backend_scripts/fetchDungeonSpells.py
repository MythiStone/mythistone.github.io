"""Name, icon, damage and description of every spell the dungeon page's detail modals show (the
MDT enemy spells and journal abilities in dungeon_details.json), built from the game client's DB2
tables as exported by wago.tools. The Blizzard spell API serves no creature spells.

Damage follows the client's creature formula for the current M+ season, so the numbers match the
in-game tooltip at Mythic 0: effect base points times the max-level ExpectedStat
CreatureSpellDamage, times the CreatureSpellDamageMod of every ContentTuningXExpected row of the
M+ content tuning that is valid in that season. Absorbs scale with PlayerHealth instead.

Description placeholders ($s1, $o1, $t1, $d, $a1, $@spellname..., $?diff8[...][...], ${...}) are
resolved for M+. A description that still holds one the data cannot answer (a runtime value such
as $@auracaster, or an effect the spell does not have) is dropped rather than shown half-filled.
"""
import ast
import csv
import io
import json
import math
import os
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import requests

STATIC_DIR = os.path.join("data", "static")
ICON_DIR = os.path.join("data", "icons")
DETAILS_PATH = os.path.join(STATIC_DIR, "dungeon_details.json")
SEASON_INFO_PATH = os.path.join(STATIC_DIR, "seasonInfo.json")
OUT_PATH = os.path.join(STATIC_DIR, "dungeon_spells.json")

BUILDS_URL = "https://wago.tools/api/builds"
WAGO_CSV = "https://wago.tools/db2/{table}/csv?build={build}"
LISTFILE_URL = "https://github.com/wowdev/wow-listfile/releases/latest/download/community-listfile.csv"
ICON_URL = "https://www.raidbots.com/static/images/icons/56/{icon}.png"
HEADERS = {"User-Agent": "MythiStone static data (https://mythistone.com)"}

# The content tuning M+ creature stats scale with in every dungeon.
MPLUS_CONTENT_TUNING_ID = 1279
MPLUS_DIFFICULTY = 8
# Rows to prefer when a spell has several: Mythic Keystone, Mythic, Heroic, Normal, any.
DIFFICULTY_ORDER = (MPLUS_DIFFICULTY, 23, 2, 1, 0)
SCHOOL_DAMAGE = 2
PERIODIC_DAMAGE_AURAS = {3, 53}
SCHOOL_ABSORB_AURA = 69
TICK_ON_APPLY = 0x200
AREA_EFFECT = 0x8000
SCHOOLS = ((1, "Physical"), (2, "Holy"), (4, "Fire"), (8, "Nature"), (16, "Frost"), (32, "Shadow"),
           (64, "Arcane"))

REF = re.compile(r"\$@[a-z]+(\d+)|\$(\d+)[a-zA-Z]")
VAR = re.compile(r"\$(\d*)([a-zA-Z])(\d?)")


class Unresolved(Exception):
    pass


def stream_lines(url):
    with requests.get(url, headers=HEADERS, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        resp.raw.decode_content = True
        # Else urllib3 closes the stream at its Content-Length and the wrapper's EOF read fails.
        resp.raw.auto_close = False
        yield from io.TextIOWrapper(resp.raw, encoding="utf-8-sig", newline="")


def csv_rows(url):
    yield from csv.DictReader(stream_lines(url))


def live_build():
    builds = requests.get(BUILDS_URL, headers=HEADERS, timeout=60)
    builds.raise_for_status()
    return max(builds.json()["wow"], key=lambda b: b["created_at"])["version"]


def by_difficulty(rows):
    by = {int(r["DifficultyID"]): r for r in rows}
    return next((by[d] for d in DIFFICULTY_ORDER if d in by), None)


def dungeon_spell_ids(details):
    ids = set()

    def walk(sections):
        for s in sections:
            if s["spell_id"]:
                ids.add(int(s["spell_id"]))
            walk(s["sections"])

    for d in details.values():
        for enemy in d["enemies"].values():
            ids.update(int(sid) for sid in enemy["spells"])
        for enc in d["journal"].values():
            walk(enc["sections"])
    return ids


def number(x, places=None):
    """Half-up like the client, 1 decimal at most unless the placeholder asks for more."""
    q = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-(places if places is not None else 1)),
                                        ROUND_HALF_UP)
    text = f"{q:,}"
    return text.rstrip("0").rstrip(".") if places is None and "." in text else text


def safe_eval(expr):
    """Arithmetic and comparisons only; the expressions come from game data."""
    funcs = {"abs": abs, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil}
    ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.Div: lambda a, b: a / b if b else 0, ast.USub: lambda a: -a, ast.UAdd: lambda a: a,
           ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b, ast.Lt: lambda a, b: a < b,
           ast.LtE: lambda a, b: a <= b, ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in ops:
            return ops[type(n.ops[0])](ev(n.left), ev(n.comparators[0]))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs:
            return funcs[n.func.id](*map(ev, n.args))
        raise Unresolved(ast.dump(n)[:40])

    try:
        return ev(ast.parse(expr, mode="eval"))
    except SyntaxError:
        raise Unresolved(expr)


class SpellData:
    def __init__(self, build, ids, level, expansion):
        names, descs = {}, {}
        for r in csv_rows(WAGO_CSV.format(table="spellname", build=build)):
            names[int(r["ID"])] = r["Name_lang"]
        for r in csv_rows(WAGO_CSV.format(table="spell", build=build)):
            descs[int(r["ID"])] = r["Description_lang"]
        missing = ids - names.keys()
        if len(missing) > len(ids) // 10:
            raise RuntimeError(f"{len(missing)} of {len(ids)} dungeon spells are not in build {build}")
        self.names, self.descs = names, descs

        # The spells the descriptions reference ($123s1, $@spelldesc123) need their effects too.
        need, todo = set(), ids & names.keys()
        while todo:
            sid = todo.pop()
            need.add(sid)
            todo |= {int(a or b) for a, b in REF.findall(descs.get(sid, ""))} - need

        def per_spell(table):
            rows = defaultdict(list)
            for r in csv_rows(WAGO_CSV.format(table=table, build=build)):
                if int(r["SpellID"]) in need:
                    rows[int(r["SpellID"])].append(r)
            return rows

        effects = defaultdict(lambda: defaultdict(list))
        for sid, rows in per_spell("spelleffect").items():
            for r in rows:
                effects[sid][int(r["EffectIndex"])].append(r)
        self.effects = {sid: {i: by_difficulty(rows) for i, rows in idx.items()}
                        for sid, idx in effects.items()}
        self.misc = {sid: by_difficulty(rows) for sid, rows in per_spell("spellmisc").items()}
        self.aura_options = {sid: by_difficulty(rows)
                             for sid, rows in per_spell("spellauraoptions").items()}
        self.durations = {r["ID"]: int(r["Duration"])
                          for r in csv_rows(WAGO_CSV.format(table="spellduration", build=build))}
        self.radii = {r["ID"]: r for r in csv_rows(WAGO_CSV.format(table="spellradius", build=build))}
        self.damage_mult = self.season_multiplier(build, level, expansion, "CreatureSpellDamage")
        self.absorb_mult = self.season_multiplier(build, level, expansion, "PlayerHealth")
        self.cited = None

    @staticmethod
    def season_multiplier(build, level, expansion, stat):
        """ExpectedStat <stat> at the max level times its mods for the current M+ season, per point."""
        rewards = csv_rows(WAGO_CSV.format(table="MythicPlusSeasonRewardLevels", build=build))
        season = int(max(rewards, key=lambda r: int(r["ID"]))["MythicPlusSeasonID"])
        seasons = {int(r["ID"]): r for r in csv_rows(WAGO_CSV.format(table="MythicPlusSeason", build=build))}
        if int(seasons[season]["ExpansionLevel"]) != expansion:
            raise RuntimeError(f"Newest M+ season {season} in build {build} is not of expansion {expansion}")
        stats = [r for r in csv_rows(WAGO_CSV.format(table="expectedstat", build=build))
                 if int(r["Lvl"]) == level and int(r["ExpansionID"]) in (expansion, -2)]
        if not stats:
            raise RuntimeError(f"No ExpectedStat row for level {level} in build {build}")
        value = float(max(stats, key=lambda r: int(r["ExpansionID"]))[stat])
        mods = {r["ID"]: float(r[f"{stat}Mod"])
                for r in csv_rows(WAGO_CSV.format(table="expectedstatmod", build=build))}
        rows = [r for r in csv_rows(WAGO_CSV.format(table="contenttuningxexpected", build=build))
                if int(r["ContentTuningID"]) == MPLUS_CONTENT_TUNING_ID
                and int(r["MinMythicPlusSeasonID"]) <= season
                and (int(r["MaxMythicPlusSeasonID"]) == 0 or season < int(r["MaxMythicPlusSeasonID"]))]
        if not rows:
            raise RuntimeError(f"No ContentTuningXExpected row for content tuning "
                               f"{MPLUS_CONTENT_TUNING_ID} in M+ season {season}")
        return value * math.prod(mods[r["ExpectedStatModID"]] for r in rows) / 100

    def effect(self, sid, index):
        return (self.effects.get(sid) or {}).get(index - 1)

    def duration_ms(self, sid):
        m = self.misc.get(sid)
        return self.durations.get(m["DurationIndex"], 0) if m else 0

    def ticks(self, sid, e):
        period, duration = int(e["EffectAuraPeriod"]), self.duration_ms(sid)
        if period <= 0 or duration <= 0:
            return 0
        m = self.misc.get(sid)
        return duration // period + (1 if m and int(m["Attributes_5"]) & TICK_ON_APPLY else 0)

    @staticmethod
    def is_damage(e):
        return int(e["Effect"]) == SCHOOL_DAMAGE or int(e["EffectAura"]) in PERIODIC_DAMAGE_AURAS

    def points(self, e, times=1):
        base = float(e["EffectBasePointsF"]) * times
        if self.is_damage(e):
            return round(base * self.damage_mult)
        if int(e["EffectAura"]) == SCHOOL_ABSORB_AURA:
            return round(base * self.absorb_mult)
        return base

    def value(self, sid, var, index):
        index = int(index) if index else 1
        if var in "dD":
            return self.duration_ms(sid) / 1000
        if var in "uUnNhH":
            a = self.aura_options.get(sid)
            if a:
                return int(a[{"u": "CumulativeAura", "n": "ProcCharges", "h": "ProcChance"}[var.lower()]])
            raise Unresolved(f"${var}")
        e = self.effect(sid, index)
        if e is None:
            raise Unresolved(f"${sid}{var}{index}")
        if var in "smMwWoO" and self.cited is not None and self.is_damage(e):
            self.cited.append(self.hit(sid, e))
        if var in "smMwW":
            return self.points(e)
        if var in "oO":
            return self.points(e, self.ticks(sid, e))
        if var in "tT":
            return int(e["EffectAuraPeriod"]) / 1000
        if var in "aA":
            r = self.radii.get(e["EffectRadiusIndex_0"]) or self.radii.get(e["EffectRadiusIndex_1"])
            if r:
                return float(r["RadiusMax" if var == "A" else "Radius"])
        if var in "xX":
            return int(e["EffectChainTargets"])
        raise Unresolved(f"${var}{index}")

    def expression(self, sid, expr):
        expr = re.sub(r"\$(abs|min|max|floor|ceil)\b", r"\1", expr)
        return safe_eval(VAR.sub(lambda m: repr(self.value(int(m.group(1) or sid), m.group(2), m.group(3))), expr))

    def condition(self, sid, cond):
        def term(t):
            t = t.strip().lstrip("?")
            negate, t = t.startswith("!"), t.lstrip("!").strip()
            diff = re.fullmatch(r"diff(\d+)", t, re.I)
            if diff:
                hit = int(diff.group(1)) == MPLUS_DIFFICULTY
            elif not t or re.fullmatch(r"[a-z]\d+", t, re.I):
                # Auras, known spells, classes: nothing a dungeon tooltip can know.
                hit = False
            else:
                hit = bool(self.expression(sid, re.sub(r"(?<![<>!=])=(?!=)", "==", t)))
            return hit != negate
        return any(all(term(a) for a in alt.split("&")) for alt in cond.split("|"))

    def render(self, sid, text, depth=0):
        out, i = [], 0
        while i < len(text):
            if text[i] != "$":
                out.append(text[i])
                i += 1
                continue
            rest = text[i + 1:]
            if rest.startswith("{"):
                end = text.index("}", i)
                places = re.match(r"\.(\d)", text[end + 1:])
                out.append(number(abs(self.expression(sid, text[i + 2:end])),
                                  int(places.group(1)) if places else 0))
                i = end + 1 + (places.end() if places else 0)
            elif rest.startswith("?"):
                # $?cond[yes]?cond2[yes2][else], every part after the first optional
                chosen, i = None, i + 1
                while i < len(text) and text[i] == "?":
                    open_at = text.index("[", i)
                    close_at = closing_bracket(text, open_at)
                    if chosen is None and self.condition(sid, text[i + 1:open_at]):
                        chosen = text[open_at + 1:close_at]
                    i = close_at + 1
                if i < len(text) and text[i] == "[":
                    close_at = closing_bracket(text, i)
                    chosen = text[i + 1:close_at] if chosen is None else chosen
                    i = close_at + 1
                out.append(self.render(sid, chosen or "", depth + 1))
            elif m := re.match(r"@(spellname|spelldesc)(\d*)", rest):
                ref = int(m.group(2) or sid)
                if m.group(1) == "spellname":
                    out.append(self.names.get(ref, ""))
                elif depth < 4:
                    out.append(self.render(ref, self.descs.get(ref, ""), depth + 1))
                i += 1 + m.end()
            elif m := re.match(r"([lg])([^:;]*):([^;]*);", rest, re.I):
                prev = re.findall(r"[\d,.]+", "".join(out))
                singular = m.group(1) in "gG" or (prev and prev[-1].replace(",", "") == "1")
                out.append(m.group(2) if singular else m.group(3))
                i += 1 + m.end()
            elif (m := VAR.match(text, i)) and m.group(2) in "dD" and not m.group(3):
                out.append(duration_text(self.duration_ms(int(m.group(1) or sid))))
                i = m.end()
            elif m:
                out.append(number(abs(self.value(int(m.group(1) or sid), m.group(2), m.group(3)))))
                i = m.end()
            else:
                raise Unresolved(rest[:20])
        return "".join(out)

    def hit(self, sid, e):
        """(direct, periodic total, tick, aoe, school mask) of one damage effect. A periodic effect
        without a duration (a channel, a ground effect) only has its tick."""
        misc = self.misc.get(sid)
        aoe = (int(e["EffectRadiusIndex_0"]) > 0 or int(e["EffectRadiusIndex_1"]) > 0
               or bool(misc and int(misc["Attributes_5"]) & AREA_EFFECT))
        mask = int(misc["SchoolMask"]) if misc else 0
        if int(e["Effect"]) == SCHOOL_DAMAGE:
            return self.points(e), 0, 0, aoe, mask
        ticks = self.ticks(sid, e)
        return 0, self.points(e, ticks) if ticks else 0, 0 if ticks else self.points(e), aoe, mask

    def describe(self, sid):
        """The resolved description (None when a placeholder cannot be filled) and the damage hits
        it cites. Most damage sits in the spells a description references, so a spell's own
        effects only count when the description names none."""
        self.cited = []
        try:
            text = re.sub(r"\s+", " ", self.render(sid, self.descs.get(sid, ""))).strip() or None
        except (Unresolved, ValueError):
            text, self.cited = None, []
        hits = self.cited or [self.hit(sid, e) for e in (self.effects.get(sid) or {}).values()
                              if e and self.is_damage(e)]
        self.cited = None
        return text, hits


def closing_bracket(text, open_at):
    depth = 0
    for j in range(open_at, len(text)):
        depth += {"[": 1, "]": -1}.get(text[j], 0)
        if depth == 0:
            return j
    raise Unresolved("unbalanced [")


def duration_text(ms):
    if ms < 0:
        return "until cancelled"
    if ms >= 60000 and ms % 60000 == 0:
        return f"{ms // 60000} min"
    return f"{number(ms / 1000)} sec"


def icon_names(build, spells):
    """Icon file name (as data/icons and Raidbots name them) per spell, via the community listfile."""
    file_ids = {}
    for sid in spells.names.keys() & spells.misc.keys():
        if spells.misc[sid]:
            file_ids[sid] = spells.misc[sid]["SpellIconFileDataID"]
    wanted, names = set(file_ids.values()), {}
    for line in stream_lines(LISTFILE_URL):
        file_id, _, path = line.rstrip("\r\n").partition(";")
        if file_id in wanted:
            names[file_id] = os.path.splitext(os.path.basename(path))[0].lower()
    return {sid: names.get(fid) for sid, fid in file_ids.items()}


def download_icon(icon):
    path = os.path.join(ICON_DIR, f"{icon}.png")
    if os.path.exists(path):
        return True
    resp = requests.get(ICON_URL.format(icon=icon), headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        print(f"  no Raidbots icon {icon}: HTTP {resp.status_code}")
        return False
    with open(path, "wb") as f:
        f.write(resp.content)
    return True


def main():
    with open(DETAILS_PATH, encoding="utf-8") as f:
        ids = dungeon_spell_ids(json.load(f))
    with open(SEASON_INFO_PATH, encoding="utf-8") as f:
        season_info = json.load(f)
    build = live_build()
    print(f"Building {len(ids)} dungeon spells from wago.tools build {build}")
    spells = SpellData(build, ids, int(season_info["max_character_level"]), int(season_info["expansion_id"]))
    print(f"  damage per point {spells.damage_mult:.2f}, absorb per point {spells.absorb_mult:.2f}")
    icons = icon_names(build, spells)

    os.makedirs(ICON_DIR, exist_ok=True)
    out, dropped = {}, []
    for sid in sorted(ids & spells.names.keys()):
        description, hits = spells.describe(sid)
        if description is None and spells.descs.get(sid):
            dropped.append(sid)
        mask = 0
        for h in hits:
            mask |= h[4]
        icon = icons.get(sid)
        out[str(sid)] = {
            "name": spells.names[sid],
            "icon": icon if icon and download_icon(icon) else None,
            "description": description,
            "damage": max((h[0] for h in hits), default=0) or None,
            "periodic_damage": max((h[1] for h in hits), default=0) or None,
            "tick_damage": max((h[2] for h in hits), default=0) or None,
            "aoe": any(h[3] for h in hits),
            "schools": [name for bit, name in SCHOOLS if mask & bit],
        }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(out)} spells to {OUT_PATH}; {len(dropped)} descriptions dropped for "
          f"placeholders the game data cannot fill: {dropped}")


if __name__ == "__main__":
    main()
