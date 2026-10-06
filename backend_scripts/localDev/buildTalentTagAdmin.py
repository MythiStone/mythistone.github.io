"""Local admin build of the talent tags page: review player suggestions, re-check
overrides, and keep the gold labels tagTalents.py --eval scores against.

Renders templates/talent_tags.html in admin mode to pages/admin/talent-tags.html
(gitignored, never deployed) with every talent of every spec. Descriptions come
from the weekly tags file when it has them (the text and version the spec pages
use), else from wago.tools (live build) via tagTalents.SpellText, per spec where
a description differs between specs. The page exports talent_tag_overrides.json
and the gold file as text to paste: nothing is written back.

    python backend_scripts/localDev/buildTalentTagAdmin.py
    python -m http.server 8099 --bind 127.0.0.1
    open http://127.0.0.1:8099/pages/admin/talent-tags.html
"""
import argparse
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

import commonUtils  # noqa: E402
import generateTalentTagsPage as page  # noqa: E402
import tagTalents  # noqa: E402

OUT_DIR = os.path.join("pages", "admin")
GOLD_ABOUT = ("Hand-labelled tags for tagTalents.py --eval ({spec}, spec {id}), built with "
              "localDev/buildTalentTagAdmin.py. Scores the prompt, not used for pages. "
              "Never use these talents as prompt examples.")


def rel(path):
    return os.path.relpath(path, REPO_ROOT).replace("\\", "/")


def build_data(tags_path):
    model = commonUtils.load_json(tags_path)
    overrides = commonUtils.load_json(page.OVERRIDES_PATH) if os.path.exists(page.OVERRIDES_PATH) else {}
    class_names = {}
    for fname in os.listdir(os.path.join(commonUtils.LOOKUP_DIR, "talents")):
        doc = commonUtils.load_json(os.path.join(commonUtils.LOOKUP_DIR, "talents", fname))
        class_names[int(fname.split(".")[0])] = doc["className"]
    text = tagTalents.SpellText()
    all_talents = page.spec_talents()
    icons = page.mention_icons(all_talents)
    spec_rows = {s: rows for s, rows in all_talents.items() if s in text.spec_index}

    talents, specs, spec_desc = {}, {}, {}
    for spec_id in sorted(spec_rows):
        specs[str(spec_id)] = [sid for sid, _name, _icon in spec_rows[spec_id]]
        for sid, name, icon in spec_rows[spec_id]:
            desc = text.render(int(sid), spec_id)[:tagTalents.DESC_MAX_CHARS]
            if sid not in talents:
                m = model.get(sid)
                tagged = m is not None and m.get("version") and "mentions" in m
                mentions = m["mentions"] if tagged else tagTalents.referenced_abilities(
                    text, desc, name, class_names[spec_id], spec_id)
                talents[sid] = {
                    "name": name, "icon": icon,
                    # the weekly tagger's text and version are what the spec pages compare overrides to
                    "desc": m["desc"] if tagged else desc,
                    "mentions": page.mention_view(mentions, icons),
                    "version": m["version"] if tagged else tagTalents.talent_version(desc),
                    "versionSource": "tagger" if tagged else "computed",
                    "model": {"tags": m["tags"], "impact": m.get("impact", "major")} if m else None,
                    "override": None,
                }
            if desc != talents[sid]["desc"]:
                spec_desc.setdefault(str(spec_id), {})[sid] = desc

    review = {}
    for sid, o in overrides.items():
        t = talents.get(sid)
        status = "orphan" if t is None else "valid" if o["version"] == t["version"] else "stale"
        review[sid] = {**o, "status": status}
        if status == "valid":
            t["override"] = {"tags": o["tags"], "impact": o["impact"]}

    gold_files = []
    for path, docs, is_list in tagTalents.gold_files():
        gold_files.append({"path": rel(path), "isList": is_list, "specs": [
            {"_about": d["_about"], "spec": d["spec"], "tags": list(d["tags"].items())} for d in docs]})

    return {
        "tags": page.tag_info(),
        "classes": page.spec_groups(spec_rows),
        "specs": specs,
        "specDesc": spec_desc,
        "talents": talents,
        "overrides": review,
        "overridesPath": rel(os.path.abspath(page.OVERRIDES_PATH)),
        "gold": {"files": gold_files, "about": GOLD_ABOUT,
                 "newPath": rel(os.path.join(SCRIPT_DIR, "talent_tag_gold_{id}.json"))},
        "github": page.GITHUB_ISSUES,
        "discord": page.DISCORD_INVITE,
    }


def main(tags_path):
    data = build_data(tags_path)
    data_path = os.path.join(OUT_DIR, "talent_tags_admin.json")
    page.write_json(data_path, data)
    stale = sum(o["status"] == "stale" for o in data["overrides"].values())
    print(f"{len(data['talents'])} talents, {len(data['overrides'])} overrides ({stale} to re-check) in {data_path}")
    stamp = int(datetime.now(timezone.utc).timestamp())
    page.render_page(os.path.join("templates", "talent_tags.html"), os.path.join(OUT_DIR, "talent-tags.html"),
                     f"/{data_path.replace(os.sep, '/')}?v={stamp}", admin=True,
                     breadcrumbs=[{"title": "Admin"}, {"title": "Talent Tags"}])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tags", default=None, help="talent tags file (default data/static/talent_tags.json)")
    args = parser.parse_args()
    os.chdir(REPO_ROOT)  # commonUtils.LOOKUP_DIR and the output paths are relative to the repo root
    main(args.tags or tagTalents.TAGS_PATH)
