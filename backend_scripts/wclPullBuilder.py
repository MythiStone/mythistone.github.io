"""Pure functions (no I/O) that rebuild a Mythic+ run's pulls from Warcraft Logs events and the
MDT packs of dungeon_mapping.json, plus the per-run deltas.

Coordinates are world yards in the WCL event convention: x = event x / 100 (= -world Y),
y = event y / 100 (= world X). A floor is a UiMap id, the event's mapID.

Pull rules:
- Sighting: an event whose resource actor (resourceActor 1 = source, 2 = target) is an enemy
  instance, with its x/y/mapID/HP. A death is a sighting too.
- Only npcs that have MDT clones count, and only killed mobs make up pulls (credit_kills): in
  engage order each kill takes one unused MDT clone of its npc, the nearest within PACK_RANGE where
  the run's own geometry can place clones, so a copy killed far from every clone of its npc (a
  summon away from MDT's spot) is ignored, as an unresolvable mob would be. Several engaged
  instances can share a clone until one dies (one of many spawned imps). Uncredited engaged mobs
  still count for spell timings.
- Kill: a WCL death, or a player's hit that leaves it at 0 HP (WCL lists no deaths of summons and
  pets), HP at or below the npc's DEFEATED_HP, or the end of a boss window, which credits only the
  encounter's main boss (main_boss). A death without killer of a mob that never fought is a despawn.
- An instance engages when it first loses HP or dies. Every mob a route kills loses HP, while RP,
  event and immune npcs act on players at full HP and never die. Its earliest sighting, often an
  idle cast at its spawn, places it.
- Pulls come from engage and death times alone (assign_pulls): an engage opens a new pull when the
  last pull is completed or its average linear HP is at or below CHAIN_PULL_HP (Pull.avg_hp). A
  pull holding the main boss of an encounter is that boss pull (key b:<encounter>).
- MDT spreads the clones of a pack apart for readability, so only a pack's centre and its npc
  composition are real. A pack is the clones sharing a group g; an ungrouped clone is a pack of its
  own, id "c<npc>.<clone index>". assign_packs covers each pull's killed npcs with packs and fits
  the run's geometry from that; where the geometry is trusted, resolve_clones then gives each mob
  its nearest clone the way keystone.guru does.
"""
import math
from bisect import bisect_left
from collections import Counter, defaultdict

CHAIN_PULL_HP = 30.0
# assign_packs: cost per pack slot a cover leaves unkilled (in MDT-image units; leave-one-dungeon-out
# over 10/30/60/0 picked 10 for four of five dungeons), and search limits per pull.
PACK_LEFT_COST = 10.0
PACK_GEO_MIN_PAIRS = 4
# Run-fit sanity, from the fits of the pack assignment keystone.guru made on four dungeons: good
# floors have 0.70-1.32 yd per MDT unit, an rms pair spread of 91-221 MDT units (packs sit ~30
# apart) and a median residual of 0.09-0.27 of the spread; broken ones had a scale of 0.23, a
# spread of 26, or a residual of 0.73 of the spread.
PACK_GEO_SCALE = (0.5, 2.0)
PACK_GEO_MIN_SPREAD = 50.0
PACK_GEO_MAX_REL_RESIDUAL = 0.4
# Share of a floor's pairs a run fit is refitted on: covers chosen without geometry are wrong for
# about one pack in eight on the dungeons seen (keystone.guru reference), a trimmed fit ignores them.
PACK_GEO_KEEP = 0.6
# keystone.guru's default engagement range: a kill takes only an MDT clone this close (yd).
PACK_RANGE = 150.0
PACK_BRANCHES = 8
PACK_SEARCH_NODES = 30000
# npc id -> HP% at which it counts as defeated though it never dies. Add an entry only from a
# dry-run that shows the npc alive to the end of its pull, and note the run it was observed in.
DEFEATED_HP = {}
LUST_CONTEXT_MS = 10000
# Deaths sort this much later than their time, so a mob killed in the second it engaged engages first.
DEATH_SHIFT_MS = 1000
# A placed mob whose last HP is at or below this, with no death after it, was removed by a script.
VANISHED_HP = 1.0
# A death (or a sign of life) of an instance number this long after its last death is a new unit:
# one unit's killing blow and WCL death come within ~50 ms, a reused number dies again >300 ms later.
REUSED_INSTANCE_MS = 100
# Mob.killed_by values whose time is when the unit's life ended: a death, or a script removing it at
# ~0% HP (a cast that consumes its caster logs no death). The others (encounter_end, run_end,
# defeated_hp) are when the log stopped following it.
LIFE_ENDS = {"death", "killing_blow", "vanished"}
# A cast this soon after its instance number's death is the dead unit's death throes, a later one is
# the next unit's that reuses the number.
DEATH_THROES_MS = 1000
# A player cooldown relates to enemy casts this close on either side.
CD_RELATION_MS = 10000
# The values of player_cooldown_categories.json, as pageGeneration.WCL_COOLDOWN_CATEGORIES.
COOLDOWN_CATEGORIES = ("defensive", "offensive", "utility", "healing", "other")
# Cooldowns that are a spec's interrupt, whatever category their name has.
INTERRUPT_NAMES = frozenset({"Disrupting Shout", "Grimoire: Fel Ravager", "Sigil of Silence", "Silence", "Solar Beam"})
MELEE_SPELL_ID = 1
# The interrupted spell on a WCL interrupt event (abilityGameID is the player's kick).
INTERRUPTED_SPELL_FIELD = "extraAbilityGameID"


# Delta bins: (bin width s, cap s)
FIRST_RECAST_BIN = (1, 120)
FIGHT_BIN = (5, 600)
DEATH_BIN = (1, 30)
LUST_TIME_BIN = (5, 600)
LUST_HP_BIN = 10



def pos(event):
    return event["x"] / 100, event["y"] / 100


def instance_key(actor_id, instance):
    return actor_id, instance or 1


def resource_key(event):
    """(actor id, instance) the event's resources (x, y, HP) belong to, or None."""
    if event.get("resourceActor") == 1:
        return instance_key(event.get("sourceID"), event.get("sourceInstance"))
    if event.get("resourceActor") == 2:
        return instance_key(event.get("targetID"), event.get("targetInstance"))
    return None


def hp_pct(event):
    hp, mx = event.get("hitPoints"), event.get("maxHitPoints")
    return 100.0 * hp / mx if hp is not None and mx else None


def is_friendly(actor_id, actors):
    """A player, or a pet a player owns. Enemy pets (e.g. a boss's summoned demon) are type Pet too."""
    a = actors.get(actor_id)
    if not a:
        return False
    if a["type"] == "Pet":
        owner = actors.get(a.get("petOwner")) or {}
        return owner.get("type") == "Player"
    return a["type"] == "Player"


def combat_sign(event, key, actors, hp):
    """Whether the event shows instance `key` in combat: it dies, it acts on a player, a player
    acts on it, or its HP is below 100%."""
    if event.get("type") == "death" or (hp is not None and hp < 100):
        return True
    src = instance_key(event.get("sourceID"), event.get("sourceInstance"))
    return is_friendly(event.get("targetID") if key == src else event.get("sourceID"), actors)


def first_sightings(events, actors, valid_npcs, summoned=frozenset()):
    """{instance key: (npc, x, y, floor)} of each valid enemy instance's earliest positioned event."""
    out = {}
    for e in sorted(events, key=lambda e: e["timestamp"]):
        key = resource_key(e)
        if key is None or key in out or key in summoned or "x" not in e:
            continue
        actor = actors.get(key[0])
        if actor and not is_friendly(key[0], actors) and actor["gameID"] in valid_npcs:
            out[key] = (actor["gameID"], *pos(e), str(e.get("mapID")))
    return out


class Mob:
    def __init__(self, key, npc):
        self.key, self.npc = key, npc
        self.first = None          # (x, y, floor) of the earliest sighting
        self.hp = 100.0            # latest HP from any event that carries it (incl. players' hits)
        self.max_hp = 0
        self.engage = self.death = None
        self.killed_by = None
        self.eligible = False      # killed in a way that counts (see track_mobs)
        self.credited = False      # an eligible kill that took a MDT clone: it is in a pull
        self.encounter = None      # the boss window whose end credited it as the main boss
        self.pull = None
        self.pack = None
        self.clone = None
        self.distance = None
        self.ignored = False       # an eligible kill that found no MDT clone (none left, or none in range)
        self.combat = None         # first combat sign, the reference of its spell timings
        self.last_seen = None
        self.summoned = False
        self.min_hp = 100.0
        self.co_boss = None        # the main boss whose encounter's win also defeated this boss
        self.uid = key
        self.awarded = False       # credited by its encounter's win without ever fighting (healed to win)


class Pull:
    def __init__(self, index, start):
        self.index, self.start = index, start
        self.encounter_id, self.window = 0, None
        self.end = None
        self.mobs = []             # credited mobs in engage order
        self.in_combat, self.killed = [], []

    @property
    def ref_start(self):
        """Time offsets count from here: the encounter start for a boss pull, else the pull start."""
        return self.window[1] if self.window else self.start

    @property
    def completed(self):
        return bool(self.mobs) and not self.in_combat

    def avg_hp(self, t):
        """Average HP at t over the mobs still in combat plus those killed (at 0), each mob's HP
        taken as linear from 100% at its engage to 0% at its death. Logged HP samples depend on
        what one combat log saw; engage and death times do not."""
        n = len(self.in_combat) + len(self.killed)
        return sum(linear_hp(m, t) for m in self.in_combat) / n if n else 100.0

    def hp_at(self, t):
        """The same average for any time t, from the mobs' engage and death times (for lust)."""
        engaged = [m for m in self.mobs if m.engage <= t]
        return sum(linear_hp(m, t) for m in engaged) / len(engaged) if engaged else 100.0

    def credited(self):
        return self.mobs

    def key(self):
        """The dungeon page's pull signature (databaseConnector.FETCH_DUNGEON_LUST_TIMELINE_SQL
        pull_sig): "npc:count" of the credited npcs, by npc id, comma separated."""
        return ",".join(f"{npc}:{n}" for npc, n in self.npc_counts())

    def family_key(self):
        """The family sp_wcl_family_map gives this pull: its encounter, else its npcs without counts."""
        if self.encounter_id:
            return f"b:{self.encounter_id}"
        return ",".join(str(npc) for npc, _ in self.npc_counts())

    def pack_ids(self):
        """The MDT packs the pull's mobs resolved to (diagnostics only)."""
        ids = {m.pack["id"] for m in self.mobs if m.pack}
        return sorted(ids, key=lambda i: (not i.isdigit(), int(i) if i.isdigit() else 0, i))

    def npc_counts(self):
        return sorted(Counter(m.npc for m in self.mobs).items())


def linear_hp(mob, t):
    if t <= mob.engage or mob.death is None:
        return 100.0
    if t >= mob.death or mob.death == mob.engage:
        return 0.0
    return 100.0 * (mob.death - t) / (mob.death - mob.engage)


def track_mobs(actors, enemy_events, enemy_deaths, enemy_summons, boss_windows, fight_end,
               npc_slots, main_boss_npcs, friendly_casts=()):
    """Per enemy unit: engage (first HP loss or death), death, whether the kill is credited, and its
    casts. WCL reuses an instance number once its unit died, so a death, or an event showing the
    unit alive, more than REUSED_INSTANCE_MS after that number's death is a new unit.
    Returns ({unit id: Mob}, {unit id: [(t, spell, type)]}, [(t, spell, npc)] enemy casts)."""
    valid_npcs = set(npc_slots)
    summoned = {instance_key(e.get("targetID"), e.get("targetInstance")) for e in enemy_summons}
    first = first_sightings(list(enemy_events) + list(enemy_deaths), actors, valid_npcs)
    current, mobs, casts, enemy_casts = {}, {}, defaultdict(list), []

    def window_at(t):
        return next((w for w in boss_windows if w[1] <= t <= w[2]), None)

    def mob_for(key, t, alive=False, dies=False, at=None):
        """The unit behind an instance key at t, a new one if the key's last unit died a while ago."""
        actor = actors.get(key[0])
        if not actor or is_friendly(key[0], actors) or actor["gameID"] not in valid_npcs:
            return None
        mob = current.get(key)
        if mob is not None and mob.death is not None and (alive or dies) and t - mob.death > REUSED_INSTANCE_MS:
            mob = None
        if mob is None:
            mob = Mob(key, actor["gameID"])
            uid = (*key, sum(1 for u in mobs if u[:2] == key))
            mob.uid, current[key] = uid, mob
            mob.summoned = key in summoned
            mobs[uid] = mob
            if uid[2] == 0 and key in first:
                mob.first = first[key][1:]
            elif at:
                mob.first = at
        return mob

    def engage(mob, t):
        mob.engage = t

    def kill(mob, t, why, eligible):
        if mob.death is not None:
            return
        mob.death, mob.killed_by, mob.eligible = t, why, eligible

    retried = {w for w in boss_windows if any(v[0] == w[0] and v[1] > w[2] for v in boss_windows)}
    seen = defaultdict(set)       # boss window -> isBoss units that any event touched in it
    timeline = ([(e["timestamp"], 0, "enemy", e) for e in enemy_events]
                + [(e["timestamp"], 1, "death", e) for e in enemy_deaths]
                + [(e["timestamp"], 2, "fcast", e) for e in friendly_casts]
                + [(w[2], 3, "window_end", w) for w in boss_windows])
    for t, _, kind, e in sorted(timeline, key=lambda r: (r[0], r[1])):
        if kind == "enemy":
            key = resource_key(e)
            src = instance_key(e.get("sourceID"), e.get("sourceInstance"))
            if e.get("type") in ("cast", "begincast") and not is_friendly(e.get("sourceID"), actors):
                enemy_casts.append((t, e.get("abilityGameID"), (actors.get(e.get("sourceID")) or {}).get("gameID")))
                caster = mob_for(src, t)
                if caster:
                    casts[caster.uid].append((t, e.get("abilityGameID"), e["type"], e.get("targetID")))
            if not key:
                continue
            hp = hp_pct(e)
            blow = hp == 0 and key != src
            mob = mob_for(key, t, alive=bool(hp), dies=blow, at=(*pos(e), str(e.get("mapID"))) if "x" in e else None)
            if mob is None or mob.death is not None:
                continue
            mob.last_seen = t
            if hp is not None:
                mob.hp = hp
                mob.min_hp = min(mob.min_hp, hp)
            mob.max_hp = max(mob.max_hp, e.get("maxHitPoints") or 0)
            if mob.combat is None and combat_sign(e, key, actors, mob.hp):
                mob.combat = t
            if mob.engage is None and mob.hp < 100:
                engage(mob, t)
            if mob.engage is None:
                continue
            if blow:
                # a player's hit that leaves it at 0 HP: WCL's Deaths list omits summons and pets
                kill(mob, t, "killing_blow", True)
            elif mob.hp <= DEFEATED_HP.get(mob.npc, -1):
                kill(mob, t, "defeated_hp", True)
        elif kind == "death":
            mob = mob_for(instance_key(e.get("targetID"), e.get("targetInstance")), t, dies=True)
            if mob is None or mob.death is not None:
                continue
            if mob.engage is None and mob.combat is None and not e.get("killerID"):
                continue    # a scripted despawn: no killer and the mob never fought
            mob.hp = mob.min_hp = 0.0
            if mob.engage is None:
                engage(mob, t)
            kill(mob, t, "death", True)
        elif kind == "fcast":
            target = actors.get(e.get("targetID")) or {}
            window = window_at(t)
            if window and target.get("gameID") in main_boss_npcs:
                mob = mob_for(instance_key(e.get("targetID"), e.get("targetInstance")), t)
                if mob:
                    seen[window].add(mob.uid)
        elif kind == "window_end" and e not in retried:
            close_encounter(e, t, [w for w in retried if w[0] == e[0]], mobs, seen[e], main_boss_npcs, kill)
    for mob in mobs.values():
        if mob.engage is None or mob.death is not None:
            continue
        if mob.hp <= VANISHED_HP and mob.key not in summoned:
            # removed at ~0% HP without a death (a scripted end); summoned objects are destroyed so
            kill(mob, mob.last_seen, "vanished", True)
        else:
            kill(mob, fight_end, "run_end", False)
    # An encounter's own adds (more units of an npc than MDT places, not logged as summons) that end
    # inside its window without a WCL death were removed by the fight, not killed: raider.io, whose
    # kills keystone.guru counts, lists none of them.
    units = Counter(m.npc for m in mobs.values() if m.engage is not None)
    logged = defaultdict(list)
    for e in enemy_deaths:
        logged[instance_key(e.get("targetID"), e.get("targetInstance"))].append(e["timestamp"])
    for mob in mobs.values():
        if (mob.eligible and not mob.summoned and mob.npc not in main_boss_npcs
                and units[mob.npc] > npc_slots[mob.npc] and window_at(mob.death)
                and not any(abs(t - mob.death) <= REUSED_INSTANCE_MS for t in logged[mob.key])):
            mob.eligible = False
    return mobs, casts_by_life(mobs, casts), enemy_casts


def casts_by_life(mobs, casts):
    """{unit id: casts} with each cast on the unit of its instance number alive at the time. A cast
    alone does not show which unit made it, so this waits for every unit's death. A cast later than
    DEATH_THROES_MS after the last unit's death belongs to a unit that never fought and is dropped."""
    lives = defaultdict(list)
    for uid in sorted(mobs):
        lives[uid[:2]].append(mobs[uid])
    out = defaultdict(list)
    for uid, rows in casts.items():
        for cast in rows:
            owner = next((m for m in lives[uid[:2]] if m.death is None or cast[0] <= m.death + DEATH_THROES_MS), None)
            if owner:
                out[owner.uid].append(cast)
    return out


def close_encounter(window, t, wiped, mobs, seen, main_boss_npcs, kill):
    """A won encounter (no later attempt) defeats its isBoss npcs engaged in it or in an earlier
    wiped attempt: the main boss (main_boss) whatever its HP, and every other still standing whose
    HP fell to VANISHED_HP in the fight or is at its lowest at the end (bosses that leave or vanish
    with the win, e.g. a council). One that recovered from its lowest HP (an untouchable companion
    healing up) was not defeated. A boss that never loses HP (an encounter won by healing it)
    engages at the encounter start."""
    attempts = [window] + wiped
    fought = [m for m in mobs.values() if m.npc in main_boss_npcs and m.engage is not None
              and any(w[1] <= m.engage <= w[2] for w in attempts) and (m.death is None or m.death >= window[1])]
    main = main_boss(fought, main_boss_npcs)
    if main is None:
        main = main_boss([mobs[u] for u in seen], main_boss_npcs, needs_engage=False)
        if main and main.engage is None:
            main.engage, main.awarded = window[1], True
    for m in fought:
        if main and m is not main and m.death is None and (m.min_hp <= VANISHED_HP or m.hp <= m.min_hp < 100):
            kill(m, t, "encounter_end", True)
            m.co_boss = main
    if main and main.death is None:
        kill(main, t, "encounter_end", True)
    if main and main.eligible:
        main.encounter = window


def credit_kills(mobs, clones, transforms=None, boss_npcs=frozenset(), anchors=None):
    """Decides which eligible kills count, keystone.guru-style: in engage order each takes the nearest
    unused MDT clone of its npc within PACK_RANGE yd, else it does not count (summons and spawned
    adds appear wherever their source is, while MDT places a few clones in one spot). On a floor with
    a trusted run fit (transforms) distances use every trusted fit, taking the closest: a unit's
    mapID and the image region MDT draws its pack in do not always agree at floor edges, and
    keystone.guru ignores floors here too. On a floor without one the unit is judged in the MDT
    image, against anchors[uid] (the pack centres of the pull fighting at its engage): within
    PACK_RANGE MDT units, as MDT draws close to a yard per unit (0.70-1.32 on the dungeons seen).
    With neither, any unused clone counts. Bosses always count, a dungeon cannot be finished
    without them."""
    left = defaultdict(list)
    for c in sorted(clones, key=lambda c: c["clone_index"]):
        left[c["npc_id"]].append(c)
    for m in mobs.values():
        m.credited = m.ignored = False
    for m in sorted((m for m in mobs.values() if m.eligible), key=lambda m: m.engage):
        pool = left[m.npc]
        near = None
        if pool and m.npc not in boss_npcs:
            if transforms and m.first and m.first[2] in transforms:
                near = min((math.hypot(*(lambda q: (q[0] - m.first[0], q[1] - m.first[1]))(apply(M, c["mdt_x"], c["mdt_y"]))), i)
                           for i, c in enumerate(pool) for M in transforms.values())
            elif (anchors or {}).get(m.uid):
                near = min((math.hypot(c["mdt_x"] - ax, c["mdt_y"] - ay), i)
                           for i, c in enumerate(pool) for ax, ay in anchors[m.uid])
        if near:
            take = near[1] if near[0] <= PACK_RANGE else None
        else:
            take = 0 if pool else None
        if take is None:
            m.ignored = True
            continue
        pool.pop(take)
        m.credited = True


def assign_pulls(mobs):
    """Pulls of the credited mobs, from engage and death times only.

    Engages and deaths (a death shifted by DEATH_SHIFT_MS, so a mob killed in the second it engaged
    still engages first) are ordered by whole second, engages first within a second. An engage joins
    the newest open pull unless that pull is completed or its average HP (Pull.avg_hp) at the
    engage is at or below CHAIN_PULL_HP; it then opens a new pull. After each death, completed
    pulls close in order, except that while the oldest open pull is still fighting, a later pull
    that completes first is folded into it: a real chain pull outlives the pull it chained from, so
    one that dies first was a delayed part of the big pull. Pulls are numbered in closing order.
    The other bosses an encounter's win defeats (close_encounter) have no death of their own, so they
    take no part in forming pulls and join their main boss's pull (keystone.guru awards a council
    together, off one kill). A pull of vanished mobs only (no death anchors it) joins the next pull."""
    credited = sorted((m for m in mobs.values() if m.credited and not m.awarded and not m.co_boss),
                      key=lambda m: m.engage)
    events = ([(m.engage // 1000, 0, m) for m in credited]
              + [((m.death + DEATH_SHIFT_MS) // 1000, 1, m) for m in sorted(credited, key=lambda m: m.death)])
    events.sort(key=lambda r: (r[0], r[1]))
    open_pulls, closed = [], []

    def fold(into, pull):
        for m in pull.mobs:
            m.pull = into
        into.mobs += pull.mobs
        into.in_combat += pull.in_combat
        into.killed += pull.killed
        into.start = min(into.start, pull.start)
        into.end = max(into.end or 0, pull.end or 0) or None

    for _, kind, mob in events:
        if kind == 0:
            last = open_pulls[-1] if open_pulls else None
            if last is None or last.completed or last.avg_hp(mob.engage) <= CHAIN_PULL_HP:
                last = Pull(None, mob.engage)
                open_pulls.append(last)
            last.mobs.append(mob)
            last.in_combat.append(mob)
            mob.pull = last
            continue
        pull = mob.pull
        pull.in_combat.remove(mob)
        pull.killed.append(mob)
        pull.end = max(pull.end or 0, mob.death)
        first = open_pulls[0]
        first_done = first.completed
        for p in list(open_pulls):
            if p.completed:
                if first_done:
                    closed.append(p)
                else:
                    fold(first, p)
                open_pulls.remove(p)
    closed += open_pulls
    # A boss credited only by its encounter's win never took part in any pull: it closes the run as a
    # pull of its own, like keystone.guru's kills awarded when the run finishes.
    for p in [p for p in closed if all(m.killed_by == "vanished" for m in p.mobs)]:
        later = [q for q in closed if q.start > p.start and q is not p]
        if later:
            fold(min(later, key=lambda q: q.start), p)
            closed.remove(p)
    for mob in sorted((m for m in mobs.values() if m.credited and m.co_boss), key=lambda m: m.death):
        pull = mob.co_boss.pull
        if pull is None or pull not in closed:
            pull = Pull(None, mob.engage)
            pull.end = mob.death
            closed.insert(sum(1 for p in closed if p.end <= mob.death), pull)
        pull.mobs.append(mob)
        pull.killed.append(mob)
        pull.start, pull.end = min(pull.start, mob.engage), max(pull.end, mob.death)
        mob.pull = pull
    for mob in sorted((m for m in mobs.values() if m.credited and m.awarded), key=lambda m: m.death):
        pull = Pull(None, mob.engage)
        pull.mobs, pull.killed, pull.end = [mob], [mob], mob.death
        mob.pull = pull
        closed.append(pull)
    for i, p in enumerate(closed, 1):
        p.index = i
        p.mobs.sort(key=lambda m: m.engage)
        boss = next((m for m in p.mobs if m.encounter), None)
        if boss:
            p.window, p.encounter_id = boss.encounter, boss.encounter[0]
    return closed


def assign_packs(pulls, packs):
    """Gives every mob of the rebuilt pulls an MDT pack (mob.pack), pull by pull in route order.

    A pull's killed npcs are covered by packs that still have unkilled slots for them, choosing the
    cover that costs least: PACK_LEFT_COST per slot a chosen pack leaves unkilled (routes mostly
    pull whole packs), plus the MDT-image distance of each chosen pack from the cover's centre (a
    pull is one place) and of that centre from the previous pull's (a route moves on gradually).
    The covers then give the run's own geometry, a similarity transform per floor (plain or
    mirrored) fitted from (pack centre, mobs' first positions) pairs, which assign_packs returns
    for resolve_clones. MDT positions are schematic, so this needs no calibration."""
    chosen = _cover_pulls(pulls, packs)
    transforms = _fit_run_geometry(pulls, packs, chosen)
    for pull, cover in zip(pulls, chosen):
        for mob in pull.mobs:
            mob.pack = mob.distance = None
        if not cover:
            continue
        for pid, give in cover.items():
            left = Counter(give)
            for mob in sorted(pull.mobs, key=lambda m: _distance_to_pack(m, packs[pid], transforms)):
                if mob.pack is None and left[mob.npc] > 0:
                    left[mob.npc] -= 1
                    mob.pack = packs[pid]
                    d = _distance_to_pack(mob, packs[pid], transforms)
                    mob.distance = None if d == math.inf else d
    return transforms


def resolve_clones(pulls, packs, clones, transforms):
    """keystone.guru's own resolution, where the run geometry is trusted: in engage order every mob
    on a floor with a trusted fit takes the nearest unused MDT clone of its npc within PACK_RANGE
    yd, looking first among the groups already in combat (the packs of mobs engaged and not yet
    dead) and then among all. The mob gets that clone's pack. Mobs off trusted floors, or with no
    clone in range, keep the pack assign_packs' cover gave them."""
    unused = defaultdict(list)
    for c in clones:
        unused[c["npc_id"]].append(c)
    mobs = sorted((m for p in pulls for m in p.mobs), key=lambda m: m.engage)
    fighting = []
    for mob in mobs:
        fighting = [o for o in fighting if o.death > mob.engage]
        M = transforms.get(mob.first[2]) if mob.first else None
        if not M or not unused[mob.npc]:
            continue
        busy = {o.clone["g"] for o in fighting if o.clone["g"] != -1}
        ranked = sorted((math.hypot(*(lambda q: (q[0] - mob.first[0], q[1] - mob.first[1]))(apply(M, c["mdt_x"], c["mdt_y"]))), i)
                        for i, c in enumerate(unused[mob.npc]))
        ranked = [(d, i) for d, i in ranked if d <= PACK_RANGE]
        pick = next(((d, i) for d, i in ranked if unused[mob.npc][i]["g"] in busy), ranked[0] if ranked else None)
        if pick is None:
            continue
        c = unused[mob.npc].pop(pick[1])
        mob.clone, mob.distance = c, pick[0]
        mob.pack = packs[str(c["g"]) if c["g"] != -1 else f"c{c['npc_id']}.{c['clone_index']}"]
        fighting.append(mob)


def _distance_to_pack(mob, pack, transforms):
    M = transforms.get(mob.first[2]) if mob.first else None
    if not M:
        return math.inf
    x, y = apply(M, pack["mdt_x"], pack["mdt_y"])
    return math.hypot(x - mob.first[0], y - mob.first[1])


def _cover_pulls(pulls, packs):
    """[{pack id: Counter(npc: count)}] per pull, the least costly cover (see assign_packs)."""
    left = {pid: Counter(p["npcs"]) for pid, p in packs.items()}
    prev, out = None, []
    for pull in pulls:
        need = Counter(m.npc for m in pull.mobs)

        def centre(cover):
            n = sum(sum(g.values()) for g in cover.values())
            return (sum(packs[k]["mdt_x"] * sum(g.values()) for k, g in cover.items()) / n,
                    sum(packs[k]["mdt_y"] * sum(g.values()) for k, g in cover.items()) / n)

        def cost(cover):
            cx, cy = centre(cover)
            unkilled = sum(sum(left[k].values()) - sum(g.values()) for k, g in cover.items())
            spread = sum(math.hypot(packs[k]["mdt_x"] - cx, packs[k]["mdt_y"] - cy) for k in cover)
            route = math.hypot(cx - prev[0], cy - prev[1]) if prev else 0.0
            return PACK_LEFT_COST * unkilled + spread + route

        best, budget = [None], [PACK_SEARCH_NODES]

        def search(need, cover):
            budget[0] -= 1
            if budget[0] < 0:
                return
            if not +need:
                c = cost(cover)
                if best[0] is None or c < best[0][0]:
                    best[0] = (c, {k: Counter(g) for k, g in cover.items()})
                return
            # the npc with the fewest packs left to supply it decides the branch
            npc = min((n for n in need if need[n] > 0), key=lambda n: sum(1 for k in left if left[k][n] > 0))
            ref = prev or (0.0, 0.0)
            options = sorted((k for k in left if k not in cover and left[k][npc] > 0),
                             key=lambda k: math.hypot(packs[k]["mdt_x"] - ref[0], packs[k]["mdt_y"] - ref[1]))
            for pid in options[:PACK_BRANCHES]:
                give = Counter({n: min(need[n], left[pid][n]) for n in need if need[n] > 0 and left[pid][n] > 0})
                cover[pid] = give
                search(need - give, cover)
                del cover[pid]

        search(need, {})
        if best[0] is None:
            out.append(None)
            continue
        cover = best[0][1]
        for pid, give in cover.items():
            left[pid] -= give
        prev = centre(cover)
        out.append(cover)
    return out


def _fit_run_geometry(pulls, packs, chosen):
    """{floor: 2x3 matrix} fitted from (pack centre, mean first position of the pull's mobs of the
    pack's npcs on their main floor) pairs. A floor is left unfitted unless it has PACK_GEO_MIN_PAIRS
    pairs spread over PACK_GEO_MIN_SPREAD MDT units (rms about their centre, else the scale is not
    pinned down), its scale lies in PACK_GEO_SCALE yd per MDT unit, and its median residual is at
    most PACK_GEO_MAX_REL_RESIDUAL of that spread in yd (else the pairs do not fit one transform)."""
    pairs = defaultdict(list)
    for pull, cover in zip(pulls, chosen):
        for pid, give in (cover or {}).items():
            pts = [m.first for m in pull.mobs if m.first and m.npc in give]
            if not pts:
                continue
            floor = Counter(p[2] for p in pts).most_common(1)[0][0]
            pts = [p for p in pts if p[2] == floor]
            pairs[floor].append((complex(packs[pid]["mdt_x"], packs[pid]["mdt_y"]),
                                 complex(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))))
    out = {}
    for floor, pr in pairs.items():
        fits = [f for f in (_trimmed_fit(pr, mirrored) for mirrored in (False, True)) if f]
        if not fits:
            continue
        residual, M, kept = min(fits, key=lambda f: f[0])
        centre = sum(m for m, _ in kept) / len(kept)
        spread = math.sqrt(sum(abs(m - centre) ** 2 for m, _ in kept) / len(kept))
        scale = scale_of(M)
        if (len(kept) >= PACK_GEO_MIN_PAIRS and spread >= PACK_GEO_MIN_SPREAD
                and PACK_GEO_SCALE[0] <= scale <= PACK_GEO_SCALE[1]
                and residual <= PACK_GEO_MAX_REL_RESIDUAL * spread * scale):
            out[floor] = M
    return out


def _trimmed_fit(pairs, mirrored):
    """(median residual, matrix, pairs kept): a least-squares similarity refitted on the
    PACK_GEO_KEEP share of pairs it fits best, as covers chosen without geometry are partly wrong."""
    kept = pairs
    M = None
    for _ in range(3):
        M = lsq_similarity([((m.conjugate() if mirrored else m), w) for m, w in kept], mirrored)
        if M is None:
            return None
        ranked = sorted(pairs, key=lambda mw: abs(complex(*apply(M, mw[0].real, mw[0].imag)) - mw[1]))
        kept = ranked[:max(2, math.ceil(PACK_GEO_KEEP * len(pairs)))]
    M = lsq_similarity([((m.conjugate() if mirrored else m), w) for m, w in kept], mirrored)
    if M is None:
        return None
    return median([abs(complex(*apply(M, m.real, m.imag)) - w) for m, w in kept]), M, kept


def build_run(packs, actors, enemy_events, enemy_deaths, enemy_summons, boss_windows,
              fight_start, fight_end, friendly_casts=(), friendly_deaths=(), lust_ids=frozenset(),
              boss_npc_ids=frozenset(), npc_slots=None, main_boss_npcs=None, clones=None, interrupts=(),
              aoe_spells=frozenset()):
    """Rebuilds the pulls of one run and attributes enemy casts, player cooldowns, lust and player
    deaths to them. packs: mdt_packs() of the dungeon, which assign_packs gives the mobs (pull keys);
    empty leaves every mob unresolved (the pulls do not depend on it). npc_slots: {npc: MDT clone count} of the whole dungeon, defaulting to
    the packs' (pass it whenever packs are missing). main_boss_npcs:
    MDT's isBoss npcs, defaulting to boss_npc_ids. clones: the dungeon's MDT clones, which enable
    the range test of credit_kills. enemy_events: enemy casts (cast and begincast) and damage
    events with resources. boss_windows: [(encounter_id, start, end)]. interrupts: the players'
    interrupt events. aoe_spells: the enemy spell ids dungeon_spells.json flags as AoE.

    Kills are first credited by MDT clone count alone; the pulls and packs this gives yield the
    run's geometry, and where it is trusted the kills are credited again with the range test and
    the pulls rebuilt."""
    if npc_slots is None:
        npc_slots = sum((Counter(p["npcs"]) for p in packs.values()), Counter())
    positioned = clones is not None
    if clones is None:
        clones = [{"npc_id": n, "clone_index": i, "mdt_x": 0.0, "mdt_y": 0.0}
                  for n, c in npc_slots.items() for i in range(1, c + 1)]
    bosses = main_boss_npcs or boss_npc_ids
    mobs, casts, enemy_casts = track_mobs(actors, enemy_events, enemy_deaths, enemy_summons, boss_windows,
                                          fight_end, npc_slots, bosses, friendly_casts)
    credit_kills(mobs, clones, boss_npcs=bosses)
    pulls = assign_pulls(mobs)
    transforms = assign_packs(pulls, packs) if packs else {}
    if packs and positioned:
        def fighting(t):
            live = [p for p in pulls if p.start <= t <= p.end]
            return max(live, key=lambda p: p.start) if live else None

        anchors = {}
        for m in mobs.values():
            pull = m.pull or (fighting(m.engage) if m.eligible else None)
            if pull:
                anchors[m.uid] = [(k["mdt_x"], k["mdt_y"]) for k in
                                  {id(o.pack): o.pack for o in pull.mobs if o.pack and not o.summoned}.values()]
        credit_kills(mobs, clones, transforms, bosses, anchors)
        for m in mobs.values():
            m.pull = m.pack = m.distance = m.clone = None
        pulls = assign_pulls(mobs)
        transforms = assign_packs(pulls, packs)
        resolve_clones(pulls, packs, clones, transforms)

    def pull_at(t):
        live = [p for p in pulls if p.start <= t <= p.end]
        return max(live, key=lambda p: p.start) if live else None

    for mob in mobs.values():
        if mob.engage is not None and not mob.credited:
            mob.pull = pull_at(mob.engage)      # for its spell timings only

    def lost_attempt(pull, t):
        """Whether t lies in a boss attempt that was wiped, or on a boss pull before its winning attempt."""
        earlier = [w[1] for w in boss_windows if pull.window and w[0] == pull.window[0] and w[1] < pull.window[1]]
        return (bool(earlier) and min(earlier) <= t < pull.window[1]) or any(
            w[1] <= t <= w[2] and any(v[0] == w[0] and v[1] > w[2] for v in boss_windows) for w in boss_windows)

    relation_casts = defaultdict(list)      # pull -> [(t, spell, npc, target)] by time, a cooldown can relate to
    for uid, rows in casts.items():
        pull = mobs[uid].pull
        if pull is not None:
            relation_casts[pull] += [(t, spell, mobs[uid].npc, target) for spell, timed in timed_cast_targets(rows).items()
                                     if spell and spell != MELEE_SPELL_ID for t, target in timed
                                     if not lost_attempt(pull, t)]
    for rows in relation_casts.values():
        rows.sort(key=lambda r: r[0])
    lusts, player_cds = [], []
    for e in sorted(friendly_casts, key=lambda e: e["timestamp"]):
        t, spell = e["timestamp"], e.get("abilityGameID")
        pull = pull_at(t)
        if spell in lust_ids:
            prev = [c for c in enemy_casts if t - LUST_CONTEXT_MS <= c[0] <= t]
            if pull is None:
                # pressed just before a pull: it belongs to the next one, at a negative offset
                pull = next((p for p in pulls if 0 < p.start - t <= LUST_CONTEXT_MS), None)
                hp = 100.0
            else:
                boss = main_boss(pull.mobs, main_boss_npcs or boss_npc_ids) if pull.window else None
                hp = linear_hp(boss, t) if boss else pull.hp_at(t)
            lusts.append({"pull": pull, "t": t, "spell": spell, "hp": hp if pull else None,
                          "offset_ms": t - pull.ref_start if pull else None,
                          "prev_spell": prev[-1][1] if prev else 0, "prev_npc": (prev[-1][2] or 0) if prev else 0})
        elif pull and not lost_attempt(pull, t):
            player = e.get("sourceID")
            player = (actors.get(player) or {}).get("petOwner") or player
            player_cds.append({"pull": pull, "player": player, "spell": spell, "t": t, "offset_ms": t - pull.ref_start,
                               "relations": cooldown_relations(relation_casts[pull], t, player, actors, aoe_spells, bosses),
                               "target_npc": enemy_npc(e.get("targetID"), actors)})
    player_deaths = [{"pull": pull_at(e["timestamp"]), "player": e.get("targetID"),
                      "spell": e.get("killingAbilityGameID") or 0,
                      "killer_npc": (actors.get(e.get("killerID")) or {}).get("gameID") or 0}
                     for e in friendly_deaths]
    for row in player_cds + lusts + player_deaths:
        row["pull"] = row["pull"].index if row["pull"] else None
    units = defaultdict(list)
    for uid in sorted(mobs):
        units[mobs[uid].key].append(mobs[uid])
    interrupted = []
    for e in interrupts:
        t = e["timestamp"]
        mob = next((m for m in units[instance_key(e.get("targetID"), e.get("targetInstance"))]
                    if m.death is None or t <= m.death + REUSED_INSTANCE_MS), None)
        if mob and mob.engage is not None and mob.pull is not None:
            interrupted.append({"pull": mob.pull.index, "npc": mob.npc, "spell": e[INTERRUPTED_SPELL_FIELD]})
    return {"pulls": pulls, "mobs": mobs, "spell_timings": spell_timings(mobs, casts),
            "player_cds": player_cds, "lusts": lusts, "player_deaths": player_deaths, "interrupts": interrupted,
            "fight_start": fight_start, "fight_end": fight_end}


def cooldown_relations(casts, t, player, actors, aoe_spells, boss_npcs):
    """The enemy casts within CD_RELATION_MS of a cooldown `player` pressed at t, from casts (by time,
    [(t, spell, npc, target)]), with the facts recorded_relations needs once the spec is known.
    offset_ms: from the enemy cast to the press, negative when the press came first."""
    near = casts[bisect_left(casts, (t - CD_RELATION_MS,)):bisect_left(casts, (t + CD_RELATION_MS + 1,))]
    return [{"spell": spell, "npc": npc, "offset_ms": t - c, "aoe": spell in aoe_spells, "at_presser": target == player,
             "at_group": (actors.get(target) or {}).get("type") == "Player", "by_boss": npc in boss_npcs}
            for c, spell, npc, target in near]


def cooldown_category(name, spec_id, categories):
    """A cooldown's category for one spec, None when unlisted. Same rule as
    pageGeneration.wcl_cooldown_category, which the collector image does not ship."""
    value = categories.get(name)
    if isinstance(value, dict):
        value = value.get(str(spec_id), value.get("default"))
    return value if value in COOLDOWN_CATEGORIES else None


def relation_applies(candidate, category, boss_pull):
    """Whether a cooldown of this category answers the enemy cast of a cooldown_relations candidate."""
    if category == "defensive":
        return candidate["aoe"] or candidate["at_presser"]
    if category in ("healing", "utility"):
        return candidate["aoe"] or candidate["at_group"]
    if category == "offensive":
        return boss_pull and candidate["by_boss"]
    return False


def recorded_relations(candidates, category, boss_pull):
    """The nearest applying candidate of each (enemy spell, npc), the earlier cast on a tie."""
    nearest = {}
    for c in candidates:
        if relation_applies(c, category, boss_pull):
            best = nearest.get((c["spell"], c["npc"]))
            if best is None or (abs(c["offset_ms"]), -c["offset_ms"]) < (abs(best["offset_ms"]), -best["offset_ms"]):
                nearest[(c["spell"], c["npc"])] = c
    return list(nearest.values())


def enemy_npc(actor_id, actors):
    """The npc id of an enemy actor, None for a player, a player's pet or no actor at all."""
    actor = actors.get(actor_id)
    return actor.get("gameID") or None if actor and not is_friendly(actor_id, actors) else None


def wcl_pull_id(pull, dungeon_pulls, fight_end):
    """The id of the WCL dungeon pull that shows this pull: a boss pull's winning attempt, else the one
    overlapping it longest. None when none does."""
    if pull.window:
        attempt = next((p for p in dungeon_pulls if p.get("encounterID") == pull.window[0]
                        and p["startTime"] == pull.window[1]), None)
        if attempt:
            return attempt["id"]

    def overlap(p):
        return min(pull.end or fight_end, p["endTime"]) - max(pull.start, p["startTime"])

    best = max(dungeon_pulls, key=overlap, default=None)
    return best["id"] if best and overlap(best) > 0 else None


def main_boss(mobs, main_boss_npcs, needs_engage=True):
    """The one mob an encounter end credits: of MDT's isBoss npcs among the mobs, the one with the
    largest health pool, the first engaged on a tie. MDT's isBoss excludes adds and RP units (an
    immune Infernal has ten times the boss's health), and two isBoss npcs of one encounter (a boss
    and its pet) are told apart by health."""
    bosses = [m for m in mobs if m.npc in main_boss_npcs and (m.engage is not None or not needs_engage)]
    return min(bosses, key=lambda m: (-m.max_hp, m.engage or 0), default=None)


def timed_cast_targets(rows):
    """{spell: [(time, target)]} of one unit's casts (in log order): begincasts when the spell has any
    on that unit, else casts. A begincast often lacks the final target, so the cast completing it
    gives the target. One that never completed keeps its own."""
    begun, completed, open_casts = defaultdict(list), defaultdict(list), {}
    for t, spell, kind, target in rows:
        if kind == "begincast":
            open_casts[spell] = [t, target]
            begun[spell].append(open_casts[spell])
        else:
            completed[spell].append((t, target))
            if spell in open_casts:
                open_casts.pop(spell)[1] = target
    return {spell: [tuple(c) for c in begun[spell]] if spell in begun else completed[spell]
            for spell in begun.keys() | completed.keys()}


def timed_casts(rows):
    """{spell: [times]} of one unit's casts, as timed_cast_targets picks them."""
    return {spell: [t for t, _ in timed] for spell, timed in timed_cast_targets(rows).items()}


def spell_timings(mobs, casts):
    """Per engaged mob and spell, over timed_casts from its first combat sign on (an opening cast at a
    player comes before the mob loses HP). Kind death is the time from each of those casts to the end
    of the unit's life (LIFE_ENDS), 0 for a cast after it, and also counts casts outside that window,
    as a spell can fire only as its caster dies. Kind after_death stands for a spell the unit cast only
    after that end: it has no time of its own, just its number of casts.
    Returns [{pull, npc, spell, kind (first|recast|fight|death), seconds}, {.. kind after_death, casts}]."""
    out = []
    for key, rows in casts.items():
        mob = mobs[key]
        if mob.engage is None or mob.pull is None:
            continue
        for spell, used in timed_casts(rows).items():
            base = {"pull": mob.pull.index, "npc": mob.npc, "spell": spell}
            if mob.killed_by in LIFE_ENDS:
                out += [{**base, "kind": "death", "seconds": max(mob.death - t, 0) / 1000} for t in used]
            start = min(mob.combat or mob.engage, mob.engage)
            times = sorted(t for t in used if t >= start and (mob.death is None or t <= mob.death))
            if not times:
                late = sum(1 for t in used if mob.death is not None and t > mob.death)
                if late and mob.killed_by in LIFE_ENDS:
                    out.append({**base, "kind": "after_death", "casts": late})
                continue
            out.append({**base, "kind": "first", "seconds": (times[0] - start) / 1000})
            out += [{**base, "kind": "recast", "seconds": (b - a) / 1000} for a, b in zip(times, times[1:])]
            out += [{**base, "kind": "fight", "seconds": (t - mob.pull.ref_start) / 1000} for t in times]
    return out


def bin_of(seconds, width_cap, low=0):
    width, cap = width_cap
    return int(min(max(seconds, low), cap) // width * width)


def run_deltas(run, player_specs, cooldowns, categories):
    """The additive aggregates one run contributes, keyed like the wcl_* tables (minus day and
    dungeon), with the readable family key where those hold family_id. player_specs: {player actor
    id: spec id}. cooldowns: player_cooldowns.json. categories: player_cooldown_categories.json."""
    pulls = {p.index: p for p in run["pulls"]}
    d = defaultdict(Counter)
    for p in run["pulls"]:
        key = p.key()
        d["pull"][(key, p.encounter_id)] += 1
        d["pull_duration_ms"][key] += (p.end or run["fight_end"]) - p.start
        d["family"][p.family_key()] += 1
        for spec in set(player_specs.values()):
            d["spec_pull"][(spec, p.family_key())] += sum(1 for s in player_specs.values() if s == spec)
    for m in run["mobs"].values():
        if m.engage is not None:
            d["npc_engaged"][m.npc] += 1
            d["npc_alive_ms"][m.npc] += m.death - m.engage
    for s in run["spell_timings"]:
        enc = pulls[s["pull"]].encounter_id
        if s["kind"] == "after_death":
            d["enemy_spell_casts"][(enc, s["npc"], s["spell"])] += s["casts"]
            d["enemy_spell_mobs"][(enc, s["npc"], s["spell"])] += 1
            continue
        width = {"fight": FIGHT_BIN, "death": DEATH_BIN}.get(s["kind"], FIRST_RECAST_BIN)
        # Negative: cast before the encounter start of a boss pull that trash or a mini-boss opened.
        d["enemy_spell_timing"][(enc, s["npc"], s["spell"], s["kind"], bin_of(s["seconds"], width, -width[1]))] += 1
        if s["kind"] == "fight":
            d["enemy_spell_casts"][(enc, s["npc"], s["spell"])] += 1
        if s["kind"] == "first":
            d["enemy_spell_mobs"][(enc, s["npc"], s["spell"])] += 1
    for i in run["interrupts"]:
        d["enemy_spell_interrupts"][(pulls[i["pull"]].encounter_id, i["npc"], i["spell"])] += 1
    offsets = defaultdict(list)             # (pull, player, spell) -> offsets of the player's casts
    for c in run["player_cds"]:
        spec = player_specs.get(c["player"])
        if spec is None:
            continue
        pull = pulls[c["pull"]]
        key = (spec, pull.family_key(), c["spell"])
        d["player_cd_casts"][key] += 1
        offsets[(c["pull"], c["player"], c["spell"])].append(c["offset_ms"])
        name = cooldowns[str(c["spell"])]["name"]
        category = None if name in INTERRUPT_NAMES else cooldown_category(name, spec, categories)
        for r in recorded_relations(c["relations"], category, bool(pull.encounter_id)):
            relation = (*key, r["spell"], r["npc"])
            offset_s = round(r["offset_ms"] / 1000)
            d["player_cd_relation"][relation] += 1
            d["player_cd_relation_offset_s"][relation] += offset_s
            d["player_cd_relation_abs_offset_s"][relation] += abs(offset_s)
        if c["target_npc"]:
            d["player_cd_target"][(*key, c["target_npc"])] += 1
    for (index, player, spell), times in offsets.items():
        p = pulls[index]
        key = (player_specs[player], p.family_key(), spell)
        duration_s = max((p.end or run["fight_end"]) - p.ref_start, 0) / 1000
        # Per pull, like player_pulls, as a family spans several pulls of one run.
        d["player_cd_players"][key] += 1
        d["player_cd_usage_players"][key] += 1
        d["player_cd_usage_casts"][key] += len(times)
        d["player_cd_usage_possible"][key] += 1 + int(duration_s // cooldowns[str(spell)]["cooldown_s"])
        d["player_cd_usage_first_s"][key] += round(max(min(times), 0) / 1000)
    for lust in run["lusts"]:
        if lust["pull"] is None:
            continue
        hp_bin = int(min(lust["hp"], 100) // LUST_HP_BIN * LUST_HP_BIN)
        d["lust"][(pulls[lust["pull"]].key(), bin_of(lust["offset_ms"] / 1000, LUST_TIME_BIN, -LUST_CONTEXT_MS / 1000), hp_bin,
                   lust["prev_spell"], lust["prev_npc"])] += 1
    death_pulls = set()
    for death in run["player_deaths"]:
        if death["pull"] is None:
            continue
        key = pulls[death["pull"]].key()
        d["player_death"][(key, death["spell"], death["killer_npc"])] += 1
        death_pulls.add(death["pull"])
    for index in death_pulls:
        d["pulls_with_death"][pulls[index].key()] += 1
    return d


# Geometry helpers.

def median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def apply(M, x, y):
    return M[0][0] * x + M[0][1] * y + M[0][2], M[1][0] * x + M[1][1] * y + M[1][2]


def similarity_matrix(a, b, mirrored):
    """world = a * m + b, or a * conj(m) + b when mirrored, as a 2x3 matrix."""
    s = -1 if mirrored else 1
    return [[a.real, -s * a.imag, b.real], [a.imag, s * a.real, b.imag]]


def lsq_similarity(pairs, mirrored):
    """Least squares a, b of world ~ a * m + b over [(m, world)] (m already conjugated if mirrored)."""
    mm = sum(m for m, _ in pairs) / len(pairs)
    wm = sum(w for _, w in pairs) / len(pairs)
    den = sum(abs(m - mm) ** 2 for m, _ in pairs)
    if not den:
        return None
    a = sum((w - wm) * (m - mm).conjugate() for m, w in pairs) / den
    return similarity_matrix(a, wm - a * mm, mirrored)


def scale_of(M):
    return math.sqrt(abs(M[0][0] * M[1][1] - M[0][1] * M[1][0]))


def mdt_packs(clones):
    """{pack id: {id, g, npcs, mdt_x, mdt_y, radius}}: a pack's centre is the mean of its clones and
    its radius the farthest clone from it, in MDT units."""
    members = defaultdict(list)
    for c in clones:
        members[str(c["g"]) if c["g"] != -1 else f"c{c['npc_id']}.{c['clone_index']}"].append(c)
    out = {}
    for pid, cl in members.items():
        x, y = sum(c["mdt_x"] for c in cl) / len(cl), sum(c["mdt_y"] for c in cl) / len(cl)
        out[pid] = {"id": pid, "g": cl[0]["g"], "npcs": Counter(c["npc_id"] for c in cl), "mdt_x": x, "mdt_y": y,
                    "radius": max(math.hypot(c["mdt_x"] - x, c["mdt_y"] - y) for c in cl)}
    return out
