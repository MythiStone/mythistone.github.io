"""Weekly playstyle names for the spec page's talent builds.

Runs in getStaticData.yml with a local Ollama model. For every spec it computes
the same builds as generateSpecPages (talentBuilds on the same DB inputs), asks
the model for a 2-4 word label per alternate build (vs Build 1) and class tree
variant (vs Variant 1), and writes data/static/build_names.json keyed by
talentBuilds.build_signature. The page build only reads that file; a build
without a name falls back to "Build N" / "Variant N".

Talent effects come from wago.tools' Spell table, downloaded every run because
descriptions change between game builds. A cached name is kept while the
descriptions of its talents are unchanged (``desc_hash``).

NAMER_FAKE=1 swaps the model for deterministic labels (local tests have no model);
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

NAMES_PATH = os.path.join(commonUtils.LOOKUP_DIR, "build_names.json")
WAGO_SPELL_CSV = "https://wago.tools/db2/Spell/csv"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("NAMER_MODEL", "qwen2.5:7b-instruct")
DESC_MAX_CHARS = 220  # per talent in the prompt; keeps CPU prompt evaluation affordable
NAME_MAX_CHARS = 32
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z ,'&-]*[A-Za-z]$")
FAKE_WORDS = ["Cleave", "Burst", "Sustain", "Mobility", "Utility", "Control", "Defense", "Priority", "Tempo"]

PROMPT = """You label World of Warcraft Mythic+ talent builds for {spec}, hero talents {hero}.
The reference is {reference}. Each alternative below lists the talents it adds and drops compared to the reference.

TALENTS (what each one does):
{glossary}

ALTERNATIVES:
{items}

Give each alternative a short playstyle label of 2 to 4 words in Title Case that says what the change does for the player, for example "AoE Cleave", "Single Target Burst", "More Mobility", "Extra Defensives", "Party Utility".
Rules: describe the effect, never use a talent name; every label must be different and must not be one of: {taken}; no numbers, no emojis, no dashes between words.
Respond with JSON only: {{"names": {{"<id>": "<label>", ...}}}}
"""


def clean_description(text, raw=None):
    """Blizzard spell text without its templating ($s1, ${..}, $?s123[a][b], |cff..|r).
    ``$@spelldescN`` is replaced by spell N's own text (one level, from ``raw``),
    since a talent that grants an ability often only links its description."""
    text = text or ""
    if raw is not None:
        text = re.sub(r"\$@spelldesc(\d+)", lambda m: " " + clean_description(raw.get(int(m.group(1)), "")), text)
    text = re.sub(r"\$@spell\w*?\d+", "", text)                  # $@spellicon / name / desc left over
    text = re.sub(r"\|c[0-9A-Fa-f]{8}|\|r", "", text)
    text = re.sub(r"\$l([^:;]+):([^;]+);", r"\2", text)          # $lpoint:points;
    text = re.sub(r"\$\?[^\[]*\[", "", text)                     # conditional heads
    text = re.sub(r"\]\s*\[[^\]]*\]", "", text).replace("]", "")  # keep the first branch
    text = re.sub(r"\$\{[^}]*\}|\$<[^>]*>|\$\d*[A-Za-z]+\d*", "X", text)
    return re.sub(r"\s+", " ", text).strip()


def load_descriptions():
    """{spell_id: cleaned description} from the live wago.tools Spell table."""
    resp = requests.get(WAGO_SPELL_CSV, timeout=300)
    resp.raise_for_status()
    raw = {
        int(row["ID"]): row["Description_lang"]
        for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8")))
        if row.get("Description_lang")
    }
    if not raw:
        raise RuntimeError("wago.tools Spell table came back empty")
    return {sid: clean_description(text, raw) for sid, text in raw.items()}


def talent(nodes, nid, entry):
    node = nodes[str(nid)]
    entries = node.get("entries") or [{}]
    e = entries[entry] if entry < len(entries) else entries[0]
    return e.get("name") or node.get("name"), e.get("spellId")


def collect_parents(spec_id, spec_name, sub_trees, tree, nodes):
    """One naming batch per parent: the alternates of a hero tree's builds, and
    the alternate class variants of each build."""
    hero = (sub_trees.get(str(tree["hero_id"])) or {}).get("name", "")
    cores = tree["cores"] + ([tree["top50_extra"]] if tree["top50_extra"] else [])
    parents = [{
        "spec": spec_name, "hero": hero, "reference": "the most played build",
        "kind": "core", "share": 100.0,
        "items": [(c, talentBuilds.build_signature(spec_id, tree["hero_id"], c["diff"])) for c in cores[1:]],
    }]
    for c in cores:
        if len(c["variants"]) > 1:
            parents.append({
                "spec": spec_name, "hero": hero, "reference": "the most played class tree of this build",
                "kind": "class", "share": c["share"],
                "items": [(v, talentBuilds.build_signature(spec_id, "class", v["diff"])) for v in c["variants"][1:]],
            })
    for p in parents:
        p["items"] = [(b, sig) for b, sig in p["items"] if sig]
    return [p for p in parents if p["items"]]


def build_prompt(parent, pending, nodes, descriptions, taken):
    glossary, lines = {}, []
    for b, _sig, _h in pending:
        adds, drops = [], []
        for sign, nid, entry, rank in b["diff"]:
            name, spell = talent(nodes, nid, entry)
            glossary[name] = (descriptions.get(spell) or "")[:DESC_MAX_CHARS]
            (drops if sign == "-" else adds).append(name)
        lines.append(f'- {b["id"]}: adds {", ".join(adds) or "nothing"}; drops {", ".join(drops) or "nothing"}')
    return PROMPT.format(
        spec=parent["spec"], hero=parent["hero"], reference=parent["reference"],
        glossary="\n".join(f"- {k}: {v or 'no description'}" for k, v in sorted(glossary.items())),
        items="\n".join(lines),
        taken=", ".join(f'"{t}"' for t in sorted(taken)) or "none",
    )


def desc_hash(build, nodes, descriptions):
    parts = []
    for _sign, nid, entry, _rank in sorted(build["diff"]):
        _name, spell = talent(nodes, nid, entry)
        parts.append(f"{spell}:{descriptions.get(spell, '')}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def valid_name(name, build, nodes, taken):
    name = (name or "").strip()
    words = name.split()
    if not (2 <= len(words) <= 4 and len(name) <= NAME_MAX_CHARS and NAME_RE.match(name)):
        return None
    if name.lower() in {t.lower() for t in taken} or name.lower().startswith("standard"):
        return None
    for _sign, nid, entry, _rank in build["diff"]:
        # whole words, so "Hexed Pack" is fine next to a talent called "Hex"
        if re.search(r"\b" + re.escape(talent(nodes, nid, entry)[0]) + r"\b", name, re.IGNORECASE):
            return None
    return name


def ask_model(prompt, pending):
    if os.environ.get("NAMER_FAKE") == "1":
        return {b["id"]: f"Test {FAKE_WORDS[int(sig, 16) % len(FAKE_WORDS)]} {FAKE_WORDS[int(sig, 16) // 7 % len(FAKE_WORDS)]}"
                for b, sig, _h in pending}
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": MODEL, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }, timeout=1800)
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    # 7B models often drop the {"names": ...} wrapper or change the id's case
    if isinstance(data, dict) and isinstance(data.get("names"), dict):
        data = data["names"]
    wanted = {b["id"].lower(): b["id"] for b, _sig, _h in pending}
    answer = {}
    if isinstance(data, dict):
        for key, value in data.items():
            build_id = wanted.get(str(key).strip().lower())
            if build_id and isinstance(value, str):
                answer[build_id] = value
    if not answer:
        print(f"  no usable names in model reply: {raw[:300]!r}")
    return answer


def check_model():
    if os.environ.get("NAMER_FAKE") == "1":
        return
    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=30)
    tags.raise_for_status()
    if not any(m.get("name", "").startswith(MODEL) for m in tags.json().get("models", [])):
        raise RuntimeError(f"Ollama at {OLLAMA_URL} does not have {MODEL}; run `ollama pull {MODEL}`")


def spec_trees(conn, cursor, spec_id, season, dungeon_ids):
    lookup = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "talents", f"{spec_id}.json"))
    rows = databaseConnector.fetch_loadout_key_levels(conn, cursor, spec_id, season)
    top = databaseConnector.fetch_top50_loadouts(conn, cursor, spec_id, season, limit=50)
    trees, _drops = talentBuilds.build_hero_tree_builds(
        rows, spec_id, lookup["fullNodeOrder"], lookup["nodes"],
        top50=talentBuilds.top50_inputs(top, dungeon_ids),
    )
    return lookup, trees


def main(max_minutes, dry_run, only_spec):
    started = time.monotonic()
    check_model()
    descriptions = load_descriptions()
    old = {}
    if os.path.exists(NAMES_PATH):
        old = commonUtils.load_json(NAMES_PATH)
    season = commonUtils.current_season_id()
    dungeon_ids = {int(k) for k in commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "dungeons.json"))}
    spec_lookup = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "specs.json"))

    # a single-spec run (testing) keeps every other spec's names
    names = {s: e for s, e in old.items() if only_spec and e.get("spec") != only_spec}
    work = []
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
            for hero_id, tree in trees.items():
                tree["hero_id"] = hero_id
                for parent in collect_parents(int(spec_id), spec_name, lookup.get("subTrees", {}), tree, lookup["nodes"]):
                    pending = []
                    for b, sig in parent["items"]:
                        h = desc_hash(b, lookup["nodes"], descriptions)
                        cached = old.get(sig)
                        if cached and cached.get("desc_hash") == h:
                            names[sig] = cached
                        else:
                            pending.append((b, sig, h))
                    if pending:
                        work.append((parent, pending, lookup["nodes"], int(spec_id)))
    finally:
        conn.close()

    # core builds first, then class variants of the most played builds
    work.sort(key=lambda w: (w[0]["kind"] != "core", -w[0]["share"]))
    named = 0
    for i, (parent, pending, nodes, spec_id) in enumerate(work):
        if time.monotonic() - started > max_minutes * 60:
            left = sum(len(w[1]) for w in work[i:])
            print(f"time box of {max_minutes} min reached; {left} builds keep their fallback until next run")
            break
        taken = {names[s]["name"] for _b, s in parent["items"] if s in names}
        prompt = build_prompt(parent, pending, nodes, descriptions, taken)
        if dry_run:
            print(prompt)
            continue
        answer = ask_model(prompt, pending)
        missing = [p for p in pending if p[0]["id"] not in answer]
        if missing:
            # one retry with only the ids the model skipped
            answer.update(ask_model(build_prompt(parent, missing, nodes, descriptions, taken), missing))
        for b, sig, h in pending:
            name = valid_name(answer.get(b["id"]), b, nodes, taken)
            if not name:
                print(f"  rejected {parent['spec']} {b['id']}: {answer.get(b['id'])!r}")
                continue
            taken.add(name)
            names[sig] = {"name": name, "spec": spec_id, "desc_hash": h, "model": MODEL,
                          "named_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
            named += 1
        print(f"  {parent['spec']} / {parent['hero']} ({parent['kind']}): named {named} so far, "
              f"{time.monotonic() - started:.0f}s")
    if dry_run:
        return
    with open(NAMES_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(names.items())), f, indent=1, ensure_ascii=False)
    print(f"build names: {len(names)} kept or new ({named} new), written to {NAMES_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-minutes", type=float, default=300)
    parser.add_argument("--dry-run", action="store_true", help="print the prompts, write nothing")
    parser.add_argument("--spec", type=int, help="only this spec id (testing)")
    args = parser.parse_args()
    databaseConnector.init_connection_pool(
        os.environ.get("DATABASE_HOST"), os.environ.get("DATABASE_USER"),
        os.environ.get("DATABASE_PASSWORD"), os.environ.get("DATABASE_NAME"),
        os.environ.get("DATABASE_PORT"), 1,
    )
    main(args.max_minutes, args.dry_run, args.spec)
