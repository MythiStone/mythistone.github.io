"""Daily snapshot of per-spec and per-dungeon standings, used to detect the
rare week-over-week moves worth a "weekly mover" post.

Late in a season popularity barely moves, so dungeons are compared on their
highest timed key and tier, specs on tier and a large share swing. The file
lives next to socials.json on the social-images branch (--snapshot-file)."""

import json
import os
from datetime import date, timedelta

from image_generation.tierlist_card import TIER_LETTERS

KEEP_DAYS = 21
# The baseline is the newest snapshot at least this old, but not older than MAX.
BASELINE_MIN_DAYS = 7
BASELINE_MAX_DAYS = 10
# A spec share move counts at >= 1.5 points, or >= 25% relative when it is also >= 0.5 points.
SPEC_SHARE_MIN_POINTS = 1.5
SPEC_SHARE_MIN_RELATIVE = 0.25
SPEC_SHARE_RELATIVE_FLOOR = 0.5


def load_snapshots(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("snapshots", [])


def save_snapshots(path, snapshots):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"snapshots": snapshots}, f, indent=1)


def snapshot_from_context(ctx, season, today):
    return {
        "date": today.isoformat(),
        "season": int(season),
        "specs": {
            sid: {"tier": s["tier"], "share": round(s["share"], 2)} for sid, s in ctx["specs"].items()
        },
        "dungeons": {
            did: {"tier": d["tier"], "max_timed": d["max_timed"]} for did, d in ctx["dungeons"].items()
        },
    }


def record_snapshot(snapshots, snap, today):
    """Replace today's snapshot and drop ones older than KEEP_DAYS (in place)."""
    cutoff = today - timedelta(days=KEEP_DAYS)
    snapshots[:] = [
        s for s in snapshots
        if s["date"] != snap["date"] and date.fromisoformat(s["date"]) >= cutoff
    ] + [snap]
    snapshots.sort(key=lambda s: s["date"])
    return snapshots


def find_baseline(snapshots, season, today):
    candidates = [
        s for s in snapshots
        if s.get("season") == int(season)
        and BASELINE_MIN_DAYS <= (today - date.fromisoformat(s["date"])).days <= BASELINE_MAX_DAYS
    ]
    return max(candidates, key=lambda s: s["date"]) if candidates else None


def _tier_steps(old, new):
    """Positive when the tier improved (F -> S), 0 when unknown or unchanged."""
    if old not in TIER_LETTERS or new not in TIER_LETTERS:
        return 0
    return TIER_LETTERS.index(old) - TIER_LETTERS.index(new)


def find_movers(baseline, ctx):
    """Moves big enough to post about, best first. Each mover:
    {"kind", "id", "name", "score", "direction", "changes": [{"label", "old", "new"}]}."""
    movers = []
    for did, now in ctx["dungeons"].items():
        was = baseline.get("dungeons", {}).get(did)
        if not was:
            continue
        changes, score, direction = [], 0, 0
        if now["max_timed"] > was["max_timed"] > 0:
            changes.append({"label": "Highest timed key", "old": f"+{was['max_timed']}", "new": f"+{now['max_timed']}"})
            score += 10 * (now["max_timed"] - was["max_timed"])
            direction = 1
        steps = _tier_steps(was["tier"], now["tier"])
        if steps:
            changes.append({"label": "Tier", "old": was["tier"], "new": now["tier"]})
            score += 8 * abs(steps)
            direction = direction or (1 if steps > 0 else -1)
        if changes:
            movers.append({"kind": "dungeon", "id": did, "name": now["name"], "score": score,
                           "direction": "up" if direction > 0 else "down", "changes": changes})

    for sid, now in ctx["specs"].items():
        was = baseline.get("specs", {}).get(sid)
        if not was:
            continue
        changes, score, direction = [], 0, 0
        steps = _tier_steps(was["tier"], now["tier"])
        if steps:
            changes.append({"label": "Tier", "old": was["tier"], "new": now["tier"]})
            score += 8 * abs(steps)
            direction = 1 if steps > 0 else -1
        delta = now["share"] - was["share"]
        relative = abs(delta) / was["share"] if was["share"] else 0
        if abs(delta) >= SPEC_SHARE_MIN_POINTS or (
            relative >= SPEC_SHARE_MIN_RELATIVE and abs(delta) >= SPEC_SHARE_RELATIVE_FLOOR
        ):
            changes.append({"label": "Share of groups", "old": f"{was['share']:.1f}%", "new": f"{now['share']:.1f}%"})
            score += 4 * abs(delta) + 10 * relative
            direction = direction or (1 if delta > 0 else -1)
        if changes:
            movers.append({"kind": "spec", "id": sid, "name": now["name"], "score": score,
                           "direction": "up" if direction > 0 else "down", "changes": changes})

    return sorted(movers, key=lambda m: m["score"], reverse=True)


def mover_hooks(mover):
    hooks = []
    for c in mover["changes"]:
        if c["label"] == "Highest timed key":
            hooks.append(f"The highest timed {mover['name']} key climbed from {c['old']} to {c['new']} in the last week")
        elif c["label"] == "Tier":
            list_name = "dungeon" if mover["kind"] == "dungeon" else "spec"
            hooks.append(f"{mover['name']} moved from {c['old']} tier to {c['new']} tier on the {list_name} tier list in a week")
        else:
            hooks.append(f"{mover['name']} went from {c['old']} to {c['new']} of groups in a week")
    return hooks
