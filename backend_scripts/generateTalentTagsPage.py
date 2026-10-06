"""Generate the "Talent tags" page: every talent the spec pages name builds from,
with the tags tagTalents.py's model gave it (or the reviewed override), where
players suggest better tags and send them as JSON (GitHub issue or Discord).

The page is static. Its data goes to /assets/json/talent_tags_index.json, built
from data/static/talent_tags.json, talent_tag_overrides.json and the per-spec
talent lookups, no DB needed. localDev/buildTalentTagAdmin.py renders the same
template in admin mode to review those suggestions and the gold labels.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import talentBuilds
import tagTalents
from commonUtils import LOOKUP_DIR, load_json
from pageGeneration import generateDungeonNav, generateSpecNav, load_notifications, make_jinja_env

INDEX_PATH = os.path.join("assets", "json", "talent_tags_index.json")
OVERRIDES_PATH = os.path.join(LOOKUP_DIR, "talent_tag_overrides.json")
MENTION_SPELLS_PATH = os.path.join(LOOKUP_DIR, "talent_mention_spells.json")
GITHUB_ISSUES = "https://github.com/MythiStone/mythistone.github.io/issues/new"
DISCORD_INVITE = "https://discord.com/invite/v3gYmYamGJ"


def spec_talents():
    """{spec_id: [(spellId, name, icon), ...]} in tree order, one entry per spell."""
    out = {}
    talent_dir = os.path.join(LOOKUP_DIR, "talents")
    for fname in sorted(os.listdir(talent_dir)):
        doc = load_json(os.path.join(talent_dir, fname))
        nodes, seen, rows = doc["nodes"], set(), []
        # fullNodeOrder spans the whole class; nodes holds only this spec's
        for node in (nodes[str(n)] for n in doc["fullNodeOrder"] if str(n) in nodes):
            for e in node.get("entries") or []:
                sid = e.get("spellId")
                if sid and sid not in seen:
                    seen.add(sid)
                    rows.append((str(sid), e.get("name") or node.get("name"), e.get("icon") or "inv_misc_questionmark"))
        out[int(fname.split(".")[0])] = rows
    return out


def spec_groups(spec_ids):
    """[{id, name, specs: [{id, name}]}] by class name, for the page's spec picker."""
    spec_lookup = load_json(os.path.join(LOOKUP_DIR, "specs.json"))
    class_lookup = load_json(os.path.join(LOOKUP_DIR, "classes.json"))
    classes = {}
    for sid in spec_ids:
        spec = spec_lookup[str(sid)]
        cls = class_lookup[str(spec["classID"])]
        group = classes.setdefault(spec["classID"], {"id": int(spec["classID"]), "name": cls["name"], "specs": []})
        group["specs"].append({"id": sid, "name": spec["name"]})
    for group in classes.values():
        group["specs"].sort(key=lambda s: s["name"])
    return sorted(classes.values(), key=lambda c: c["name"])


def tag_info():
    return {t: {"label": label, "help": tagTalents.TAG_HELP[t]} for t, label in talentBuilds.BUILD_TAGS.items()}


def mention_icons(all_spec_talents):
    """{spellId: icon path} for mentioned abilities: a talent's own icon, else the one
    fetchSpellInfo.py downloaded."""
    icons = {sid: f"/data/icons/{icon}.png" for rows in all_spec_talents.values() for sid, _name, icon in rows}
    if os.path.exists(MENTION_SPELLS_PATH):
        for sid, e in load_json(MENTION_SPELLS_PATH).items():
            icons.setdefault(sid, f"/data/icons/{e['icon']}")
    return icons


def mention_view(mentions, icons):
    return [{**m, "icon": icons.get(str(m["id"]))} for m in mentions or []]


def build_index(tags_path):
    """The page data: talents the model tagged, grouped per spec."""
    model = load_json(tags_path)
    overrides = load_json(OVERRIDES_PATH) if os.path.exists(OVERRIDES_PATH) else {}
    all_talents = spec_talents()
    icons = mention_icons(all_talents)
    talents, specs = {}, {}
    for spec_id, rows in all_talents.items():
        ids = []
        for sid, name, icon in rows:
            m = model.get(sid)
            if m is None:
                continue
            ids.append(sid)
            if sid in talents:
                continue
            o = overrides.get(sid)
            valid = o is not None and m.get("version") and o["version"] == m["version"]
            talents[sid] = {
                "name": name, "icon": icon, "desc": m.get("desc", ""),
                "mentions": mention_view(m.get("mentions"), icons),
                "version": m.get("version"),
                "model": {"tags": m["tags"], "impact": m.get("impact", "major")},
                "override": {"tags": o["tags"], "impact": o["impact"]} if valid else None,
            }
        if ids:
            specs[spec_id] = ids
    return {
        "tags": tag_info(),
        "classes": spec_groups(specs),
        "specs": {str(k): v for k, v in specs.items()},
        "talents": talents,
        "github": GITHUB_ISSUES,
        "discord": DISCORD_INVITE,
    }


def render_page(template_path, out_path, data_url, admin=False, breadcrumbs=None):
    spec_lookup = load_json(os.path.join(LOOKUP_DIR, "specs.json"))
    class_lookup = load_json(os.path.join(LOOKUP_DIR, "classes.json"))
    env = make_jinja_env(os.path.dirname(template_path) or "templates")
    html = env.get_template(os.path.basename(template_path)).render(
        generated_at=datetime.now(timezone.utc).timestamp(),
        spec_nav=generateSpecNav(spec_lookup, class_lookup),
        dungeon_nav=generateDungeonNav(load_json(os.path.join(LOOKUP_DIR, "dungeons.json"))),
        notifications=load_notifications(LOOKUP_DIR),
        active_page="talent-tags",
        breadcrumbs=breadcrumbs or [{"title": "Pages", "href": "/pages"}, {"title": "Talent Tags"}],
        data_url=data_url,
        admin=admin,
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {out_path}")


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def main(template_path, output_dir, tags_path):
    index = build_index(tags_path)
    write_json(INDEX_PATH, index)
    print(f"{len(index['talents'])} talents in {INDEX_PATH}")
    stamp = int(datetime.now(timezone.utc).timestamp())
    render_page(template_path, os.path.join(output_dir, "talent-tags.html"),
                f"/{INDEX_PATH.replace(os.sep, '/')}?v={stamp}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", default=os.path.join("templates", "talent_tags.html"))
    parser.add_argument("--output_dir", default="pages")
    parser.add_argument("--tags", default=os.path.join(LOOKUP_DIR, "talent_tags.json"),
                        help="talent tags file (local tests point this at a scratch copy)")
    args = parser.parse_args()
    main(args.template, args.output_dir, args.tags)
