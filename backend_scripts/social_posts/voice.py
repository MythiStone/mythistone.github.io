"""Caption personas and the recent-post history the prompt uses to avoid
sounding the same every day.

A persona is picked per post, weighted by post type, never the same one twice
in a row (the last one is read back from the newest socials.json record)."""

import random

PERSONAS = {
    "snarky_analyst": {
        "name": "The Snarky Analyst",
        "brief": (
            "Dry, a little smug, treats the data like a courtroom exhibit. Deadpan one-liners "
            "that roast the meta, never the players."
        ),
        "examples": [
            "Fel-Scarred is on nearly every Havoc build. Aldrachi Reaver has been reported missing, last seen in the talent calculator.",
            "Ruby Life Pools anchors the dungeon tier list again. At this point the drakes are just renting the place.",
        ],
    },
    "hype_caster": {
        "name": "The Hype Caster",
        "brief": (
            "Esports caster energy calling a big moment live. Short punchy sentences, genuine "
            "excitement, no fake drama."
        ),
        "examples": [
            "Plus twenty-two Den of Nalorakk, TIMED. Somebody check on the bear, he did not see that coming.",
            "A new name at the top of the DPS charts and it is not the one anybody had on their bingo card.",
        ],
    },
    "deadpan_raid_leader": {
        "name": "The Deadpan Raid Leader",
        "brief": (
            "A tired raid leader reading notes to the group before pull. Flat delivery, practical, "
            "the joke hides in the understatement."
        ),
        "examples": [
            "Notes for tonight: Brewmaster is basically all Master of Harmony. The rest of you know what you did.",
            "Reminder that the meta group times more keys than yours. No pressure. Pull in ten.",
        ],
    },
    "lore_nerd": {
        "name": "The Lore Nerd",
        "brief": (
            "Reads the stats as if they were events in Azeroth. Playful in-universe references to "
            "the class fantasy, the dungeon, or its bosses, grounded in the numbers."
        ),
        "examples": [
            "The Light has made its choice and it is Herald of the Sun. Lightsmith is still at the forge, hammering quietly.",
            "Even the Loa of Kings' Rest would be impressed by how often this crypt gets looted.",
        ],
    },
    "pug_veteran": {
        "name": "The Group Finder Veteran",
        "brief": (
            "Has seen a thousand pugs. Relatable, a little weary, speaks to the reader's own key "
            "experience and the shared pain of the group finder."
        ),
        "examples": [
            "You already knew this one from the group finder: the listing goes up and suddenly everyone is busy.",
            "Next time your tank says the spec is fine, show them this.",
        ],
    },
}

# Relative persona weights per post type; unlisted personas get weight 0 for that type.
PERSONA_WEIGHTS = {
    "highest_run": {"hype_caster": 4, "pug_veteran": 2, "snarky_analyst": 1, "deadpan_raid_leader": 1, "lore_nerd": 1},
    "longest_run": {"hype_caster": 2, "pug_veteran": 3, "snarky_analyst": 2, "deadpan_raid_leader": 2, "lore_nerd": 1},
    "shortest_run": {"hype_caster": 4, "pug_veteran": 2, "snarky_analyst": 1, "deadpan_raid_leader": 1, "lore_nerd": 1},
    "spec_overview": {"lore_nerd": 3, "pug_veteran": 3, "snarky_analyst": 2, "deadpan_raid_leader": 2, "hype_caster": 1},
    "dungeon_overview": {"pug_veteran": 3, "lore_nerd": 2, "snarky_analyst": 2, "deadpan_raid_leader": 2, "hype_caster": 1},
    "comp_overview": {"deadpan_raid_leader": 3, "snarky_analyst": 3, "pug_veteran": 2, "hype_caster": 1},
    "weekly_mover": {"hype_caster": 3, "snarky_analyst": 2, "deadpan_raid_leader": 2, "pug_veteran": 1},
    "underdog_spotlight": {"pug_veteran": 3, "lore_nerd": 2, "hype_caster": 2, "snarky_analyst": 1},
}
_META_WEIGHTS = {"snarky_analyst": 4, "deadpan_raid_leader": 2, "pug_veteran": 2, "hype_caster": 1, "lore_nerd": 1}
for _t in ("dungeon_tierlist", "spec_popularity_tierlist", "spec_popularity_vs_performance",
           "spec_distribution_by_level", "dungeon_popularity_by_level"):
    PERSONA_WEIGHTS[_t] = _META_WEIGHTS


def recent_records(donesocials, limit=8):
    """Newest-first socials.json records that carry a timestamp."""
    records = [r for r in (donesocials or {}).values() if isinstance(r, dict) and r.get("timestamp")]
    records.sort(key=lambda r: r["timestamp"], reverse=True)
    return records[:limit]


def last_persona(donesocials):
    for r in recent_records(donesocials, limit=len(donesocials or {})):
        if r.get("persona"):
            return r["persona"]
    return None


def pick_persona(post_type, donesocials=None, rng=random):
    """Persona key for this post: weighted by post type, never the last one used."""
    weights = dict(PERSONA_WEIGHTS.get(post_type) or {k: 1 for k in PERSONAS})
    previous = last_persona(donesocials)
    if previous in weights and len(weights) > 1:
        del weights[previous]
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def opening(text, words=5):
    return " ".join((text or "").split()[:words])


def recent_openings(donesocials, limit=8):
    """Opening words of the latest captions, fed to the prompt as "do not start like these"."""
    out = []
    for r in recent_records(donesocials, limit=limit):
        o = opening(r.get("social") or r.get("post"))
        if o:
            out.append(o)
    return out
