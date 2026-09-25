"""Turn a generator's raw post_data into what the caption model actually sees:
a few human-labelled facts plus 1-3 precomputed "story" hooks.

Every comparison (ranks, gaps to an average, timer ratios) is computed here so
the numbers are right; the model only phrases them. Pure: no DB, no network,
the season context (social_posts.context) is passed in."""

import re

from commonUtils import get_dungeon_lookup
from social_posts.context import find_dungeon_by_name, find_spec_by_name

# Gap (percentage points) to a role/dungeon average worth calling out.
MIN_AVG_GAP = 2.0
# A hero tree at or above this share makes the runner-up "basically unplayed".
DOMINANT_TREE_SHARE = 95.0
# Minority hero tree must be below this share to count as an underdog build.
MINORITY_TREE_SHARE = 10.0
MINORITY_TREE_MIN_RUNS = 200


def pct(value):
    return f"{value:.0f}%"


def _gap(a, b):
    """Point gap between two percentages as the reader sees them (both rounded first)."""
    return round(a) - round(b)


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _duration_ms(text):
    """'28:43.821' or '03:09:45.053' -> milliseconds; None when unparseable."""
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+)(?:\.(\d+))?", (text or "").strip())
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return ((int(h or 0) * 60 + int(mi)) * 60 + int(s)) * 1000 + int((frac or "0").ljust(3, "0")[:3])


def _timer_ms(dungeon_name):
    for meta in get_dungeon_lookup().values():
        name = meta.get("name", {})
        name = name.get("en_US") if isinstance(name, dict) else name
        if name == dungeon_name:
            return (meta.get("keystone_upgrades", {}).get("1") or {}).get("qualifying_duration")
    return None


def _short_duration(ms):
    """Human duration for hooks: '3 hours 9 minutes', '21 minutes'."""
    minutes = int(ms // 60000)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} hour{'s' if h != 1 else ''} {m} minute{'s' if m != 1 else ''}"
    if h:
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{m} minute{'s' if m != 1 else ''}"


def _rank_phrase(rank, count, what, verb="played"):
    if rank == 1:
        return f"the most-{verb} {what}"
    if rank == count:
        return f"the least-{verb} {what}"
    return f"the {ordinal(rank)} most-{verb} {what} out of {count}"


# ---------------------------------------------------------------- spec hooks


def spec_hooks(spec):
    """Hooks for one spec context entry, most surprising first (build_facts keeps 3)."""
    hooks = []
    role = spec["role_name"]
    trees = spec.get("hero_trees") or []
    if len(trees) >= 2:
        top, runner = trees[0], trees[1]
        minority = [
            t for t in trees[1:]
            if t["share"] < MINORITY_TREE_SHARE and t["runs"] >= MINORITY_TREE_MIN_RUNS
            and t["timed_pct"] - top["timed_pct"] >= 1
        ]
        if minority:
            m = minority[0]
            hooks.append(
                f"The rare {m['name']} build ({pct(m['share'])} of runs) times {pct(m['timed_pct'])} of keys, "
                f"beating {top['name']} at {pct(top['timed_pct'])}"
            )
        if top["share"] >= DOMINANT_TREE_SHARE:
            hooks.append(f"{top['name']} is on {pct(top['share'])} of builds and {runner['name']} is basically unplayed")
        elif top["share"] <= 65:
            hooks.append(f"Close hero tree race: {top['name']} {pct(top['share'])} vs {runner['name']} {pct(runner['share'])}")

    gap = _gap(spec["timed_pct"], spec["role_avg_timed_pct"])
    if abs(gap) >= MIN_AVG_GAP:
        side = "above" if gap > 0 else "below"
        hooks.append(
            f"{spec['name']} times {pct(spec['timed_pct'])} of its keys, {abs(gap)} points {side} "
            f"the {pct(spec['role_avg_timed_pct'])} average for {role} specs"
        )
    hooks.append(f"{spec['name']} is {_rank_phrase(spec['role_rank'], spec['role_count'], role + ' spec')}")
    if spec.get("tier"):
        hooks.append(f"{spec['name']} sits in {spec['tier']} tier on the MythiStone spec tier list")
    return hooks


def _spec_overview(data, ctx):
    spec = find_spec_by_name(ctx, data.get("spec"))
    facts = {"Spec": (data.get("spec") or "").strip(), "Runs tracked": data.get("amount_data_source_runs")}
    if data.get("highest_run"):
        facts["Best key"] = data["highest_run"]
    if data.get("top_hero_tree_name") and data.get("top_hero_tree_pct"):
        facts["Most-played hero tree"] = f"{data['top_hero_tree_name']} ({data['top_hero_tree_pct']} of builds)"
    if data.get("timed_pct"):
        facts["Keys timed"] = data["timed_pct"]
    return facts, (spec_hooks(spec) if spec else [])


# ------------------------------------------------------------- dungeon hooks


def dungeon_hooks(d):
    hooks = []
    gap = _gap(d["timed_pct"], d["avg_timed_pct"])
    if abs(gap) >= MIN_AVG_GAP:
        side = "above" if gap > 0 else "below"
        hooks.append(
            f"Groups time {pct(d['timed_pct'])} of {d['name']} keys, {abs(gap)} points {side} "
            f"the {pct(d['avg_timed_pct'])} dungeon average"
        )
    if d.get("tier"):
        hooks.append(f"{d['name']} sits in {d['tier']} tier on the dungeon tier list")
    hooks.append(f"{d['name']} is {_rank_phrase(d['runs_rank'], d['count'], 'dungeon', verb='run')} this season")
    return hooks


def _dungeon_overview(data, ctx):
    d = find_dungeon_by_name(ctx, data.get("dungeon"))
    facts = {"Dungeon": (data.get("dungeon") or "").strip(), "Runs tracked": data.get("amount_data_source_runs")}
    if data.get("highest_key"):
        facts["Highest key"] = f"+{str(data['highest_key']).lstrip('+')}"
    if data.get("timed_pct"):
        facts["Keys timed"] = data["timed_pct"]
    if data.get("top_comp"):
        facts["Most-run group"] = data["top_comp"]
    return facts, (dungeon_hooks(d) if d else [])


# ---------------------------------------------------------------- run hooks


def _run(post_type, data, ctx):
    facts = {
        "Dungeon": data.get("dungeon"),
        "Key level": f"+{data.get('level')}",
        "Duration": data.get("duration"),
        "Region": data.get("region"),
        "Group": data.get("comp"),
        "When": data.get("run_happened"),
    }
    record = {"highest_run": "highest key", "longest_run": "longest run", "shortest_run": "fastest clear"}[post_type]
    hooks = [f"This is the {record} MythiStone has tracked this season"]
    dur, timer = _duration_ms(data.get("duration")), _timer_ms(data.get("dungeon"))
    if dur and timer:
        timer_txt = f"{int(timer // 60000)}-minute timer"
        if dur > timer * 1.5:
            hooks.append(f"The run took {dur / timer:.0f} times as long as the {timer_txt}")
        elif dur <= timer:
            hooks.append(f"It beat the {timer_txt} with {_short_duration(timer - dur)} to spare")
    return facts, hooks


# ------------------------------------------------------------ overview hooks


def _comp_overview(data, ctx):
    facts = {"Most-run group": data.get("top_comp"), "Runs tracked": data.get("amount_data_source_runs")}
    if data.get("runner_up_comp"):
        facts["Second most-run group"] = data["runner_up_comp"]
    if data.get("meta_comp") and data.get("meta_comp") != data.get("top_comp"):
        facts["Best-performing meta group"] = data["meta_comp"]
    if data.get("meta_comp_timed_pct"):
        facts["Meta group keys timed"] = data["meta_comp_timed_pct"]
    if data.get("meta_comp_max_key"):
        facts["Meta group highest key"] = data["meta_comp_max_key"]
    hooks = []
    if data.get("meta_comp") == data.get("top_comp") and data.get("meta_comp_timed_pct"):
        hooks.append(
            f"The most-run group is also the meta pick and times {data['meta_comp_timed_pct']} of its keys"
        )
    top = [s.strip() for s in (data.get("top_comp") or "").split(",") if s.strip()]
    runner = [s.strip() for s in (data.get("runner_up_comp") or "").split(",") if s.strip()]
    if top and runner:
        only_top = [s for s in top if s not in runner]
        only_runner = [s for s in runner if s not in top]
        if len(only_top) == 1 and len(only_runner) == 1:
            hooks.append(
                f"The top two groups differ by exactly one spec: {only_top[0]} in the most-run group, "
                f"{only_runner[0]} in the runner-up"
            )
    return facts, hooks


def _dungeon_tierlist(data, ctx):
    facts = {"Top dungeon": data.get("best_dungeon"), "Bottom dungeon": data.get("worst_dungeon"),
             "Runs tracked": data.get("total_runs")}
    hooks = []
    best = find_dungeon_by_name(ctx, data.get("best_dungeon"))
    worst = find_dungeon_by_name(ctx, data.get("worst_dungeon"))
    if best and worst:
        if best["max_timed"] > worst["max_timed"]:
            hooks.append(
                f"The highest timed {best['name']} is a +{best['max_timed']}, "
                f"{worst['name']} tops out at +{worst['max_timed']}"
            )
        gap = _gap(best["timed_pct"], worst["timed_pct"])
        if gap >= MIN_AVG_GAP:
            hooks.append(
                f"{best['name']} gets timed {pct(best['timed_pct'])} of the time, {worst['name']} only {pct(worst['timed_pct'])}"
            )
    return facts, hooks


def _spec_pair_hooks(ctx, best_name, worst_name, best_label, worst_label):
    hooks = []
    for name, label in ((best_name, best_label), (worst_name, worst_label)):
        spec = find_spec_by_name(ctx, name)
        if spec:
            hooks.append(
                f"{label} {spec['name']} is {_rank_phrase(spec['role_rank'], spec['role_count'], spec['role_name'] + ' spec')}"
            )
    return hooks


def _spec_tierlist(data, ctx):
    facts = {"Top spec": data.get("best_spec"), "Bottom spec": data.get("worst_spec"),
             "Runs tracked": data.get("total_runs")}
    return facts, _spec_pair_hooks(ctx, data.get("best_spec"), data.get("worst_spec"),
                                   "Tier list leader", "Tier list anchor")


def _spec_pop_vs_perf(data, ctx):
    over, under = data.get("most_overperforming_spec"), data.get("most_underperforming_spec")
    facts = {"Biggest overperformer for its popularity": over,
             "Most overplayed for its results": under}
    return facts, _spec_pair_hooks(ctx, over, under, "Overperformer", "Overplayed")


def _spec_by_level(data, ctx):
    specs = data.get("highest_specs") or []
    facts = {"Highest key level with data": f"+{data.get('highest_keylevel')}",
             "Most common specs at that level": ", ".join(s.replace(" - ", " ") for s in specs)}
    return facts, []


def _dungeon_by_level(data, ctx):
    facts = {"Most-run dungeon": data.get("top_dungeon"), "Least-run dungeon": data.get("bottom_dungeon")}
    hooks = []
    if data.get("weekly_share_riser"):
        facts["Biggest weekly riser (share of timed runs)"] = data["weekly_share_riser"]
    if data.get("weekly_share_faller"):
        facts["Biggest weekly faller (share of timed runs)"] = data["weekly_share_faller"]
    top = find_dungeon_by_name(ctx, data.get("top_dungeon"))
    bottom = find_dungeon_by_name(ctx, data.get("bottom_dungeon"))
    if top and bottom and bottom["runs"]:
        ratio = top["runs"] / bottom["runs"]
        if ratio >= 1.5:
            hooks.append(f"{top['name']} gets run {ratio:.1f} times as often as {bottom['name']}")
    return facts, hooks


_BUILDERS = {
    "spec_overview": _spec_overview,
    "dungeon_overview": _dungeon_overview,
    "comp_overview": _comp_overview,
    "dungeon_tierlist": _dungeon_tierlist,
    "spec_popularity_tierlist": _spec_tierlist,
    "spec_popularity_vs_performance": _spec_pop_vs_perf,
    "spec_distribution_by_level": _spec_by_level,
    "dungeon_popularity_by_level": _dungeon_by_level,
}


def build_facts(post_type, data, ctx=None):
    """Return {"facts": {label: value}, "hooks": [sentence, ...]} for the model.

    Types that already build labelled facts themselves (weekly mover, underdog)
    pass them through as {"facts": ..., "hooks": ...}."""
    if isinstance(data, dict) and "facts" in data and "hooks" in data:
        return {"facts": data["facts"], "hooks": list(data["hooks"])}
    if post_type in ("highest_run", "longest_run", "shortest_run"):
        facts, hooks = _run(post_type, data, ctx)
    elif post_type in _BUILDERS:
        facts, hooks = _BUILDERS[post_type](data, ctx)
    else:
        facts, hooks = dict(data), []
    facts = {k: v for k, v in facts.items() if v not in (None, "", [], "+None")}
    return {"facts": facts, "hooks": hooks[:3]}
