"""Suggests a category for player cooldowns that have none, for a person to review in a pull request.

data/static/player_cooldown_categories.json is reviewed by hand and is what the pages read. This
script only ever adds names that are missing from it, and never changes an existing value. A value
is a category or {"default": category, "<spec id>": category}.

data/static/player_cooldown_category_signals.json remembers the game data each name was last
looked at with. A reviewed spell is raised only when that game data really changed (labels, Cooldown
Viewer groups, or the tooltip apart from its numbers) and the new suggestion differs from the
reviewed value. A better rule therefore raises nothing by itself.

The rule is a logistic regression trained on the reviewed file at run time, over the tooltip's
words, Blizzard's spell labels, the Cooldown Viewer group, the spec's role and, weakly, the spell's
effects. `--evaluate` reports its accuracy on names held out of training.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
from collections import Counter, defaultdict

from fetchDungeonSpells import WAGO_CSV, csv_rows, live_build

STATIC_DIR = os.path.join("data", "static")
COOLDOWNS_FILE = "player_cooldowns.json"
CATEGORIES_FILE = "player_cooldown_categories.json"
SIGNALS_FILE = "player_cooldown_category_signals.json"

CATEGORIES = ("defensive", "offensive", "utility", "healing", "other")
LABELS = {"1284", "930", "690"}
ROLES = {"0": "tank", "1": "healer", "2": "damage"}
RACIAL_SPEC = "racial"
SHORT_COOLDOWN = 45

VOCABULARY_SIZE = 200
MIN_DOCUMENT_FREQUENCY = 3
L2 = 0.003
LEARNING_RATE = 0.4
EPOCHS = 25
EFFECT_WEIGHT = 0.5
HIGH_CONFIDENCE = 0.7
SEED = 7
# Other splits than the ones the feature set was tuned on, so the report stays held out.
EVALUATION_SEED = 101

GROUP_WIDE_PROTECTION = {"Rallying Cry", "Anti-Magic Zone", "Darkness", "Zephyr", "Spirit Link Totem", "Aura Mastery",
                         "Power Word: Barrier", "Earthen Wall Totem", "Stoneskin Totem",
                         "Ancestral Protection Totem"}

STOP_WORDS = set("a an and are as at be by for from in into is it its of on or that the their them they this to "
                 "up with you your".split())
csv.field_size_limit(10 ** 8)


def table_rows(table, build, tables_dir):
    if tables_dir:
        with open(os.path.join(tables_dir, f"{table}.csv"), encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)
    else:
        yield from csv_rows(WAGO_CSV.format(table=table, build=build))


def load_game_data(spell_ids, tables_dir):
    build = None if tables_dir else live_build()
    wanted = {str(spell_id) for spell_id in spell_ids}
    data = {"labels": defaultdict(set), "viewer": defaultdict(lambda: defaultdict(set)),
            "effects": defaultdict(set), "descriptions": {}, "roles": {}}
    for row in table_rows("SpellLabel", build, tables_dir):
        if row["SpellID"] in wanted and row["LabelID"] in LABELS:
            data["labels"][row["SpellID"]].add(row["LabelID"])
    set_spec = {row["ID"]: row["ChrSpecialization"] for row in table_rows("CooldownSet", build, tables_dir)}
    for row in table_rows("CooldownSetSpell", build, tables_dir):
        if row["SpellID"] in wanted and row["CooldownSetID"] in set_spec:
            data["viewer"][row["SpellID"]][set_spec[row["CooldownSetID"]]].add(row["Category"])
    for row in table_rows("SpellEffect", build, tables_dir):
        if row["SpellID"] in wanted:
            data["effects"][row["SpellID"]].add(f"{row['Effect']}/{row['EffectAura']}")
    texts = {row["ID"]: row["Description_lang"] for row in table_rows("Spell", build, tables_dir)}
    for spell_id in wanted:
        data["descriptions"][spell_id] = re.sub(r"\$@spelldesc(\d+)", lambda m: texts.get(m.group(1), ""),
                                                texts.get(spell_id, ""))
    data["roles"] = {row["ID"]: ROLES.get(row["Role"]) for row in table_rows("ChrSpecialization", build, tables_dir)}
    return data


def stable_description(text):
    """The tooltip without its numbers, so a retuned value is not a change to the spell."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", text)).strip()


def words(text):
    text = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", " ", text)
    text = re.sub(r"\$\{[^}]*\}|\$<[^>]*>|\$\?[^\[\s]*|\$@?[a-zA-Z]*\d*[a-zA-Z]*\d*", " ", text)
    return re.findall(r"[a-z][a-z']*", text.lower())


def phrases(text):
    tokens = words(text)
    found = set()
    for size in (1, 2, 3):
        for start in range(len(tokens) - size + 1):
            gram = tokens[start:start + size]
            if gram[0] not in STOP_WORDS and gram[-1] not in STOP_WORDS:
                found.add(" ".join(gram))
    return found


def spells_by_name(cooldowns):
    named = defaultdict(list)
    for spell_id, entry in cooldowns.items():
        named[entry["name"]].append(spell_id)
    return {name: sorted(ids, key=int) for name, ids in named.items()}


def specs_of(ids, cooldowns):
    specs = sorted({str(spec) for spell_id in ids for spec in cooldowns[spell_id]["specs"]}, key=int)
    return specs or [RACIAL_SPEC]


def signature(ids, data):
    labels = sorted({label for spell_id in ids for label in data["labels"].get(spell_id, ())})
    viewer = defaultdict(set)
    for spell_id in ids:
        for spec, groups in data["viewer"].get(spell_id, {}).items():
            viewer[spec] |= groups
    text = "\n".join(sorted({stable_description(data["descriptions"].get(spell_id, "")) for spell_id in ids}))
    return {"labels": labels, "viewer": {spec: sorted(viewer[spec]) for spec in sorted(viewer, key=int)},
            "description": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]}


def features(spec, ids, cooldowns, data):
    """{feature: value} of one (name, spec)."""
    own = [i for i in ids if spec == RACIAL_SPEC or int(spec) in cooldowns[i]["specs"]] or ids
    result = {}
    for spell_id in own:
        for label in data["labels"].get(spell_id, ()):
            result[f"label:{label}"] = 1.0
        for group in data["viewer"].get(spell_id, {}).get(spec, ()):
            result[f"viewer:{group}"] = 1.0
        for effect in data["effects"].get(spell_id, ()):
            result[f"effect:{effect}"] = EFFECT_WEIGHT
        for phrase in phrases(data["descriptions"].get(spell_id, "")):
            result[f"word:{phrase}"] = 1.0
    role = data["roles"].get(spec) or "none"
    # The same label or viewer group means different things on a healer and on a tank.
    for feature in [f for f in result if f.startswith(("label:", "viewer:"))]:
        result[f"cross:{role}|{feature}"] = 1.0
    result[f"role:{role}"] = 1.0
    cooldown = min(cooldowns[i]["cooldown_s"] for i in own)
    result["cooldown:short" if cooldown < SHORT_COOLDOWN else "cooldown:long"] = 1.0
    return result


def value_for(value, spec):
    return value if isinstance(value, str) else value.get(spec, value["default"])


def validate_categories(categories):
    for name, value in categories.items():
        if isinstance(value, str):
            valid = value in CATEGORIES
        else:
            valid = (isinstance(value, dict) and "default" in value and all(v in CATEGORIES for v in value.values())
                     and all(k == "default" or k.isdigit() for k in value))
        if not valid:
            raise RuntimeError(f"Invalid category value for {name}: {value!r}")


class Rule:
    """Multinomial logistic regression, trained with AdaGrad on a vocabulary picked from its own samples."""

    def __init__(self, samples, vocabulary_size=VOCABULARY_SIZE, l2=L2):
        self.classes = sorted({s["label"] for s in samples})
        self.vocabulary = self.pick_vocabulary(samples, vocabulary_size)
        self.weights = {c: defaultdict(float) for c in self.classes}
        self.bias = dict.fromkeys(self.classes, 0.0)
        totals = Counter(s["label"] for s in samples)
        squared = {c: defaultdict(lambda: 1e-8) for c in self.classes}
        order = list(range(len(samples)))
        rng = random.Random(SEED)
        for _ in range(EPOCHS):
            rng.shuffle(order)
            for index in order:
                sample = samples[index]
                active = self.active(sample["features"])
                weight = sample["weight"] * len(samples) / (len(self.classes) * totals[sample["label"]])
                probabilities = self.probabilities(active)
                for c in self.classes:
                    error = (probabilities[c] - (c == sample["label"])) * weight
                    self.bias[c] -= LEARNING_RATE * 0.1 * error
                    for feature, value in active.items():
                        gradient = error * value + l2 * self.weights[c][feature]
                        squared[c][feature] += gradient * gradient
                        self.weights[c][feature] -= LEARNING_RATE * gradient / math.sqrt(squared[c][feature])

    @staticmethod
    def pick_vocabulary(samples, size):
        """Every structured feature, plus the words that best separate the categories (chi squared)."""
        per_feature = defaultdict(Counter)
        totals = Counter(s["label"] for s in samples)
        for sample in samples:
            for feature in sample["features"]:
                per_feature[feature][sample["label"]] += 1
        scored = []
        for feature, counts in per_feature.items():
            seen = sum(counts.values())
            if feature.startswith("word:") and seen >= MIN_DOCUMENT_FREQUENCY:
                score = sum((counts[c] - seen * totals[c] / len(samples)) ** 2 / (seen * totals[c] / len(samples))
                            for c in totals)
                scored.append((-score, feature))
        return {feature for _, feature in sorted(scored)[:size]} | {f for f in per_feature if not f.startswith("word:")}

    def active(self, feature_values):
        return {f: v for f, v in feature_values.items() if f in self.vocabulary}

    def probabilities(self, active):
        scores = {c: self.bias[c] + sum(self.weights[c].get(f, 0.0) * v for f, v in active.items())
                  for c in self.classes}
        top = max(scores.values())
        exponentials = {c: math.exp(score - top) for c, score in scores.items()}
        total = sum(exponentials.values())
        return {c: value / total for c, value in exponentials.items()}

    def predict(self, feature_values):
        active = self.active(feature_values)
        probabilities = self.probabilities(active)
        category = max(sorted(probabilities), key=probabilities.get)
        drivers = sorted(((self.weights[category].get(f, 0.0) * v, f) for f, v in active.items()
                          if not f.startswith(("effect:", "cooldown:"))), key=lambda d: (-d[0], d[1]))
        return {"category": category, "probability": probabilities[category],
                "confidence": "high" if probabilities[category] >= HIGH_CONFIDENCE else "low",
                "reason": ", ".join(describe_feature(f) for weight, f in drivers[:3] if weight > 0)
                or "no strong signal"}


def describe_feature(feature):
    kind, _, value = feature.partition(":")
    if kind == "cross":
        role, _, inner = value.partition("|")
        return f"{describe_feature(inner)} on a {role} spec"
    return {"word": f'tooltip says "{value}"', "label": f"game label {value}", "viewer": f"Cooldown Viewer group {value}",
            "role": f"{value} spec"}[kind]


def training_samples(categories, named, cooldowns, data, skip=()):
    samples = []
    for name, value in sorted(categories.items()):
        if name in named and name not in skip:
            specs = specs_of(named[name], cooldowns)
            samples += [{"name": name, "spec": spec, "label": value_for(value, spec), "weight": 1 / len(specs),
                         "features": features(spec, named[name], cooldowns, data)} for spec in specs]
    return samples


def suggest(name, rule, named, cooldowns, data):
    """{"value": file value, "specs": {spec: prediction}} of one name."""
    specs = specs_of(named[name], cooldowns)
    predictions = {spec: rule.predict(features(spec, named[name], cooldowns, data)) for spec in specs}
    counts = Counter(p["category"] for p in predictions.values())
    default = sorted(counts, key=lambda c: (-counts[c], c))[0]
    overrides = {spec: p["category"] for spec, p in predictions.items()
                 if p["category"] != default and p["confidence"] == "high" and spec != RACIAL_SPEC}
    return {"value": {"default": default, **overrides} if overrides else default, "specs": predictions}


def differs(reviewed, suggested, specs):
    return any(value_for(reviewed, spec) != value_for(suggested, spec) for spec in specs)


def dump_entries(entries):
    """One sorted entry per line, so a pull request shows exactly which spell changed."""
    lines = [f"{json.dumps(name, ensure_ascii=False)}:"
             f"{json.dumps(entries[name], sort_keys=True, separators=(',', ':'), ensure_ascii=False)}"
             for name in sorted(entries)]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def shown_value(value):
    if isinstance(value, str):
        return value
    return value["default"] + "".join(f", spec {spec}: {c}" for spec, c in sorted(value.items()) if spec != "default")


def pr_body(new, flagged):
    if not new and not flagged:
        return "No new or changed player cooldowns."
    out = ["Suggested player cooldown categories, for review. Nothing here is applied until this pull request is merged.",
           "", "To change a value, edit `data/static/player_cooldown_categories.json` in this pull request.", ""]
    if new:
        out += [f"## New spells ({len(new)})", "",
                "| Spell | Class | Specs | Cooldown | Suggested category | Confidence | Reason |",
                "|---|---|---|---|---|---|---|"]
        for row in sorted(new, key=lambda r: (r["confidence"] != "low", r["name"])):
            out.append(f"| {row['name']} | {row['class']} | {row['specs']} | {row['cooldown']} s | "
                       f"{shown_value(row['value'])} | {row['confidence']} | {row['reason']} |")
        out.append("")
    if flagged:
        out += [f"## Reviewed spells whose game data changed ({len(flagged)})", "",
                "The reviewed value stays as it is. Only change it here if you agree with the suggestion.", "",
                "| Spell | Reviewed value | Suggestion | Confidence | What changed | Reason |",
                "|---|---|---|---|---|---|"]
        for row in sorted(flagged, key=lambda r: r["name"]):
            out.append(f"| {row['name']} | {shown_value(row['reviewed'])} | {shown_value(row['value'])} | "
                       f"{row['confidence']} | {row['changed']} | {row['reason']} |")
        out.append("")
    return "\n".join(out)


def name_row(name, suggestion, named, cooldowns):
    ids = named[name]
    weakest = min(suggestion["specs"].values(), key=lambda p: p["probability"])
    classes = sorted({cooldowns[i]["class"] or "Racial" for i in ids})
    cooldown = "/".join(str(c) for c in sorted({cooldowns[i]["cooldown_s"] for i in ids}))
    return {"name": name, "class": ", ".join(classes), "specs": ", ".join(specs_of(ids, cooldowns)),
            "cooldown": cooldown, "value": suggestion["value"], "confidence": weakest["confidence"],
            "reason": weakest["reason"]}


def run(static_dir, tables_dir, dry_run, pr_body_path, baseline, suggestions_path=None):
    with open(os.path.join(static_dir, COOLDOWNS_FILE), encoding="utf-8") as f:
        cooldowns = json.load(f)
    categories_path = os.path.join(static_dir, CATEGORIES_FILE)
    signals_path = os.path.join(static_dir, SIGNALS_FILE)
    with open(categories_path, encoding="utf-8") as f:
        categories = json.load(f)
    validate_categories(categories)
    signals = {}
    if os.path.exists(signals_path):
        with open(signals_path, encoding="utf-8") as f:
            signals = json.load(f)

    named = spells_by_name(cooldowns)
    data = load_game_data(cooldowns, tables_dir)
    current = {name: signature(ids, data) for name, ids in named.items()}
    stale = {name for name in named if name in categories and name in signals
             and {k: signals[name].get(k) for k in current[name]} != current[name]}
    # A changed spell must not be judged by a rule trained on its own reviewed value.
    rule = Rule(training_samples(categories, named, cooldowns, data, skip=stale))

    new, flagged, updates = [], [], {}
    for name in sorted(named):
        if (name in categories and name in signals and name not in stale) or (baseline and name not in categories):
            continue
        suggestion = suggest(name, rule, named, cooldowns, data)
        updates[name] = {**current[name], "suggestion": suggestion["value"]}
        if name not in categories:
            new.append(name_row(name, suggestion, named, cooldowns))
        elif name in stale and differs(categories[name], suggestion["value"], specs_of(named[name], cooldowns)):
            changed = [part for part in current[name] if signals[name].get(part) != current[name][part]]
            flagged.append({**name_row(name, suggestion, named, cooldowns), "reviewed": categories[name],
                            "changed": ", ".join(changed)})

    if suggestions_path:
        every = {name: suggest(name, rule, named, cooldowns, data)["specs"] for name in sorted(named)}
        with open(suggestions_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(every, f, indent=1, sort_keys=True, ensure_ascii=False)

    body = pr_body(new, flagged)
    if pr_body_path:
        with open(pr_body_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body + "\n")
    print(f"{len(new)} new names, {len(flagged)} reviewed spells flagged")
    if dry_run:
        print(body)
        return new, flagged
    if new or flagged or baseline:
        for row in new:
            categories[row["name"]] = row["value"]
        signals.update(updates)
        for path, entries in ((categories_path, categories), (signals_path, signals)):
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(dump_entries(entries))
    return new, flagged


def folds(names, labels, count, seed):
    """Name -> fold, stratified by category. Every spec of a name stays in one fold."""
    rng = random.Random(seed)
    assignment = {}
    by_label = defaultdict(list)
    for name in sorted(names):
        by_label[labels[name]].append(name)
    offset = 0
    for label in sorted(by_label):
        members = by_label[label]
        rng.shuffle(members)
        for index, name in enumerate(members):
            assignment[name] = (index + offset) % count
        offset += len(members)
    return assignment


def choose_settings(samples, seed):
    """Vocabulary size and L2 picked by cross-validation inside the training folds only."""
    labels = {s["name"]: s["label"] for s in samples}
    inner = folds(sorted(labels), labels, 3, seed)
    best = None
    for size in (200, 600, 1500):
        for l2 in (0.0003, 0.003):
            correct = total = 0.0
            for fold in range(3):
                rule = Rule([s for s in samples if inner[s["name"]] != fold], size, l2)
                for sample in samples:
                    if inner[sample["name"]] == fold:
                        total += sample["weight"]
                        correct += sample["weight"] * (rule.predict(sample["features"])["category"] == sample["label"])
            if best is None or correct / total > best[0]:
                best = (correct / total, size, l2)
    return best[1], best[2]


def evaluate(static_dir, tables_dir, casts_path, outer_folds=5, repeats=2):
    with open(os.path.join(static_dir, COOLDOWNS_FILE), encoding="utf-8") as f:
        cooldowns = json.load(f)
    with open(os.path.join(static_dir, CATEGORIES_FILE), encoding="utf-8") as f:
        categories = json.load(f)
    casts = {}
    with open(casts_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                spell_id, count = line.split()
                casts[spell_id] = int(count)
    named = spells_by_name(cooldowns)
    data = load_game_data(cooldowns, tables_dir)
    samples = training_samples(categories, named, cooldowns, data)
    for sample in samples:
        own = [i for i in named[sample["name"]] if sample["spec"] == RACIAL_SPEC
               or int(sample["spec"]) in cooldowns[i]["specs"]]
        sample["casts"] = sum(casts.get(i, 0) / max(1, len(cooldowns[i]["specs"])) for i in own)
    labels = {s["name"]: s["label"] for s in samples}

    tally = Counter()
    per_class = defaultdict(Counter)
    settings = Counter()
    for repeat in range(repeats):
        outer = folds(sorted(labels), labels, outer_folds, EVALUATION_SEED + repeat)
        for fold in range(outer_folds):
            train = [s for s in samples if outer[s["name"]] != fold]
            size, l2 = choose_settings(train, SEED + repeat + fold)
            settings[(size, l2)] += 1
            rule = Rule(train, size, l2)
            for sample in samples:
                if outer[sample["name"]] != fold:
                    continue
                guess = rule.predict(sample["features"])
                hit = guess["category"] == sample["label"]
                tally["pairs"] += 1
                tally["hits"] += hit
                tally["names"] += sample["weight"]
                tally["name_hits"] += sample["weight"] * hit
                tally["casts"] += sample["casts"]
                tally["cast_hits"] += sample["casts"] * hit
                tally[guess["confidence"]] += 1
                tally[guess["confidence"] + "_hits"] += hit
                per_class[sample["label"]]["actual"] += 1
                per_class[sample["label"]]["hits"] += hit
                per_class[guess["category"]]["predicted"] += 1
    report = {"held_out_pairs": tally["pairs"] / repeats,
              "accuracy_per_spec_pair": tally["hits"] / tally["pairs"],
              "accuracy_per_name": tally["name_hits"] / tally["names"],
              "accuracy_cast_weighted": tally["cast_hits"] / tally["casts"],
              "high_confidence": {"share": tally["high"] / tally["pairs"],
                                  "accuracy": tally["high_hits"] / max(1, tally["high"])},
              "low_confidence": {"share": tally["low"] / tally["pairs"],
                                 "accuracy": tally["low_hits"] / max(1, tally["low"])},
              "per_category": {c: {"recall": v["hits"] / max(1, v["actual"]),
                                   "precision": v["hits"] / max(1, v["predicted"]),
                                   "pairs": v["actual"] / repeats} for c, v in sorted(per_class.items())},
              "settings_chosen": {f"vocabulary {k[0]}, l2 {k[1]}": n for k, n in settings.most_common()},
              "group_wide_protection": evaluate_group_wide(categories, named, data, outer_folds, repeats)}
    print(json.dumps(report, indent=2))
    return report


def evaluate_group_wide(categories, named, data, outer_folds, repeats):
    """Held-out detection of group-wide protection from the tooltip's words alone, per name."""
    names = sorted((set(categories) | GROUP_WIDE_PROTECTION) & set(named))
    samples = []
    for name in names:
        found = set()
        for spell_id in named[name]:
            found |= phrases(data["descriptions"].get(spell_id, ""))
        samples.append({"name": name, "label": "group" if name in GROUP_WIDE_PROTECTION else "single", "weight": 1.0,
                        "features": {f"word:{p}": 1.0 for p in found}})
    labels = {s["name"]: s["label"] for s in samples}
    tp = fp = fn = 0
    missed, wrong = Counter(), Counter()
    for repeat in range(repeats):
        outer = folds(names, labels, outer_folds, EVALUATION_SEED + repeat)
        for fold in range(outer_folds):
            rule = Rule([s for s in samples if outer[s["name"]] != fold], 200, 0.003)
            for sample in samples:
                if outer[sample["name"]] != fold:
                    continue
                guess = rule.predict(sample["features"])["category"]
                if guess == "group" and sample["label"] == "group":
                    tp += 1
                elif guess == "group":
                    fp += 1
                    wrong[sample["name"]] += 1
                elif sample["label"] == "group":
                    fn += 1
                    missed[sample["name"]] += 1
    return {"positives": sum(1 for s in samples if s["label"] == "group"), "names": len(samples),
            "precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn),
            "missed": sorted(missed), "false_alarms": sorted(wrong)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--static-dir", default=STATIC_DIR)
    parser.add_argument("--tables-dir", help="Read the wago tables from <table>.csv files here")
    parser.add_argument("--dry-run", action="store_true", help="Print the pull request body and write nothing")
    parser.add_argument("--pr-body", help="Write the pull request body to this file")
    parser.add_argument("--baseline", action="store_true", help="Record the game data of the reviewed spells")
    parser.add_argument("--suggestions", help="Write category, confidence and reason per (name, spec) to this file")
    parser.add_argument("--evaluate", metavar="CASTS_FILE", help="Report held-out accuracy, weighted by these casts")
    args = parser.parse_args()
    if args.evaluate:
        evaluate(args.static_dir, args.tables_dir, args.evaluate)
    else:
        run(args.static_dir, args.tables_dir, args.dry_run, args.pr_body, args.baseline, args.suggestions)


if __name__ == "__main__":
    main()
