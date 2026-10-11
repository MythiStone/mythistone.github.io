#!/usr/bin/env python3
"""mythi-kb: a live, code-derived map of the MythiStone repo plus the curated gotchas.

Agents query this instead of reading the 40-60k-token source files to find a table, a query,
a page's wiring or the gotchas for a file. The map is parsed from the code on demand (stdlib
only: ast + regex), so it cannot go stale. Gotchas are the curated markdown files under
.claude/skills/*/ref/ (plus any SKILL.md) whose frontmatter declares `files:` globs.

CLI (works without MCP, e.g. from Codex/Cline):
    python .claude/kb/kb.py overview
    python .claude/kb/kb.py table runs
    python .claude/kb/kb.py symbol fetch_top_loadout
    python .claude/kb/kb.py page spec
    python .claude/kb/kb.py bot "spec gear"
    python .claude/kb/kb.py file templates/spec_page.html
    python .claude/kb/kb.py gotcha pooled-connection-gotchas
    python .claude/kb/kb.py search "RENAME contention"
    python .claude/kb/kb.py lint
    python .claude/kb/kb.py --write      # emit .claude/kb/map/*.md (gitignored)
    python .claude/kb/kb.py --index      # regenerate the gotcha table in each domain SKILL.md
"""
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / ".claude" / "skills"
MAP_DIR = ROOT / ".claude" / "kb" / "map"

# First matching glob wins, so specific files come before the broad globs that would swallow them.
DOMAINS = {
    "database": {
        "agent": "database",
        "skills": ["database", "local-test-render"],
        "verify": "database ref verify-database-sql (ephemeral MySQL 8); seeder classify_all must pass",
    },
    "discord-bot": {
        "agent": "discord-bot",
        "skills": ["discord-bot", "local-test-render"],
        "verify": "python -m discord_bot.db_smoke_test against the seeded DB; run the bot locally",
    },
    "collector-infra": {
        "agent": "collector-infra",
        "skills": ["collector-simc", "season-ops", "social"],
        "verify": "collector-simc ref collector-smoke-test; docker build + run; social ref social-image-mock-harness",
    },
    "pages": {
        "agent": "pages",
        "skills": ["pages", "frontend", "local-test-render"],
        "verify": "local-test-render: seed, run the generate*.py, serve on 8099, inspect",
    },
}
DOMAIN_GLOBS = [
    ("backend_scripts/database.sql", "database"),
    ("backend_scripts/databaseConnector.py", "database"),
    ("backend_scripts/localDev/*", "database"),
    ("backend_scripts/aggPipelineHealth.py", "database"),
    ("discord_bot/*", "discord-bot"),
    ("Dockerfile.bot", "discord-bot"),
    ("entrypoint_bot.sh", "discord-bot"),
    (".github/workflows/buildBotImage.yml", "discord-bot"),
    ("backend_scripts/discordHandler.py", "discord-bot"),
    ("backend_scripts/broadcastDiscordNews.py", "discord-bot"),
    ("backend_scripts/generateSocialsPost.py", "collector-infra"),
    ("backend_scripts/generateSimcProfiles.py", "collector-infra"),
    ("backend_scripts/social_posts/*", "collector-infra"),
    ("backend_scripts/image_generation/*", "collector-infra"),
    ("backend_scripts/renderAllSocialImages.py", "collector-infra"),
    ("backend_scripts/generate*.py", "pages"),
    ("backend_scripts/pageGeneration.py", "pages"),
    ("backend_scripts/aggregateData.py", "pages"),
    ("backend_scripts/commonUtils.py", "pages"),
    ("backend_scripts/compArchetypes.py", "pages"),
    ("backend_scripts/chartData.py", "pages"),
    ("backend_scripts/minifyAssets.py", "pages"),
    ("templates/*", "pages"),
    ("assets/*", "pages"),
    ("backend_scripts/*", "collector-infra"),
    (".github/workflows/*", "collector-infra"),
    ("Dockerfile*", "collector-infra"),
    ("entrypoint.sh", "collector-infra"),
    ("docker-compose.yml", "collector-infra"),
    ("data/*", "collector-infra"),
]

SQL_KEYWORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|REPLACE|CALL|CREATE|TRUNCATE)\b")
# A write to the `<t>_new` shadow table (then RENAMEd over <t>) counts as a write to <t>.
WRITE_RE = r"(?:INSERT\s+(?:IGNORE\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE\s+(?:TABLE\s+)?|\bTO)\s+(?:`?\w+`?\.)?`?{t}(?:_new|_tmp|_stage)?`?\b"
SHARED_MODULES = ("databaseConnector", "commonUtils", "pageGeneration", "aggregateData")


def _rel(p):
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def _match(path, pattern):
    """Glob match where * spans directories (fnmatch semantics) and a bare dir matches below it."""
    path = path.replace("\\", "/")
    return fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("/") + "/")


def domain_of(path):
    for pattern, dom in DOMAIN_GLOBS:
        if _match(path, pattern):
            return dom
    return None


def _frontmatter(text):
    """Tiny YAML-subset reader for skill frontmatter: scalars, inline [a, b] and '- item' lists."""
    m = re.match(r"---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    meta, key = {}, None
    for line in m.group(1).splitlines():
        item = re.match(r"\s+-\s+(.*)", line)
        if item and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(item.group(1).strip().strip("'\""))
            continue
        kv = re.match(r"([A-Za-z_-]+):\s*(.*)", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val.startswith('"') and val.endswith('"') and len(val) > 1:
                meta[key] = json.loads(val)
            elif val:
                meta[key] = val.strip("'")
            else:
                meta[key] = []
    return meta, text[m.end():]


def _fstring_text(node):
    """f-string source as plain text with each {expr} kept as a placeholder."""
    return "".join(
        v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
        for v in node.values
    )


def _template_locals(t):
    """Names a template binds itself (for targets, set, macro params, imports), so they are not render() context."""
    names = {"loop", "true", "false", "none", "range", "caller", "self", "varargs", "kwargs"}
    for grp in re.findall(r"{%-?\s*for\s+([\w, ]+?)\s+in\b", t):
        names |= {n.strip() for n in grp.split(",")}
    names |= set(re.findall(r"{%-?\s*set\s+(\w+)", t))
    names |= set(re.findall(r"{%-?\s*macro\s+(\w+)", t))
    for params in re.findall(r"{%-?\s*macro\s+\w+\(([^)]*)\)", t):
        names |= {p.split("=")[0].strip() for p in params.split(",") if p.strip()}
    names |= set(re.findall(r"{%-?\s*import\s+[\"'][^\"']+[\"']\s+as\s+(\w+)", t))
    for grp in re.findall(r"{%-?\s*from\s+[\"'][^\"']+[\"']\s+import\s+([\w, ]+)", t):
        names |= {n.strip() for n in grp.split(",")}
    return names


class KB:
    def __init__(self):
        self._stamp = None
        self._build()

    # ---------------------------------------------------------------- build

    def _tracked_files(self):
        try:
            out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
            files = [f for f in out.splitlines() if f]
        except Exception:
            files = [_rel(os.path.join(d, f)) for d, _, fs in os.walk(ROOT) if "/.git" not in d for f in fs]
        # Untracked-but-present source (new files in the working tree) still belongs in the map.
        extra = []
        for sub in ("backend_scripts", "templates", "assets/js", "assets/css", "discord_bot", ".claude", ".github/workflows"):
            for d, _, fs in os.walk(ROOT / sub):
                if "__pycache__" not in d and "/kb/map" not in d.replace("\\", "/"):
                    extra += [_rel(os.path.join(d, f)) for f in fs]
        return sorted(set(files) | set(extra))

    def _source_stamp(self):
        latest = 0.0
        for sub in ("backend_scripts", "templates", "assets/js", "discord_bot", ".claude/skills", ".github/workflows"):
            for d, _, fs in os.walk(ROOT / sub):
                for f in fs:
                    try:
                        latest = max(latest, os.path.getmtime(os.path.join(d, f)))
                    except OSError:
                        pass
        return latest

    def refresh(self):
        if self._source_stamp() != self._stamp:
            self._build()

    def _build(self):
        self._stamp = self._source_stamp()
        self.files = self._tracked_files()
        self._parse_sql()
        self._parse_python()
        self._parse_templates()
        self._parse_workflows()
        self._parse_bot()
        self._parse_gotchas()

    def _read(self, rel):
        try:
            return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def _parse_sql(self):
        sql = self._read("backend_scripts/database.sql")
        self.sql_text = sql
        self.tables, self.routines = {}, {}
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?\w+`?\.)?`?(\w+)`?\s*\(", sql, re.I):
            name = m.group(1).lower()
            if name in self.tables or re.search(r"_(new|old|tmp)$", name):
                continue
            depth, i = 1, m.end()
            while i < len(sql) and depth:
                depth += {"(": 1, ")": -1}.get(sql[i], 0)
                i += 1
            body = sql[m.end():i - 1]
            tail = sql[i:sql.find(";", i)] if sql.find(";", i) != -1 else ""
            cols, keys = [], []
            for part in re.split(r",\s*\n", body):
                part = " ".join(part.split())
                if not part:
                    continue
                if re.match(r"(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN|FULLTEXT)\b", part, re.I):
                    keys.append(part)
                else:
                    cm = re.match(r"`?(\w+)`?\s+(\w+(?:\([^)]*\))?)", part)
                    if cm:
                        cols.append((cm.group(1), cm.group(2)))
            storage = " ".join(re.findall(r"(TABLESPACE\s+\S+|DATA\s+DIRECTORY\s*=\s*'[^']+')", tail, re.I))
            self.tables[name] = {
                "cols": cols,
                "keys": keys,
                "storage": storage,
                "line": sql.count("\n", 0, m.start()) + 1,
            }
        starts = [
            (m.start(), m.group(1).upper(), m.group(2))
            for m in re.finditer(r"CREATE\s+(?:DEFINER\s*=\s*\S+\s+)?(PROCEDURE|EVENT|FUNCTION|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?\w+`?\.)?`?(\w+)`?", sql, re.I)
        ]
        bounds = [s for s, _, _ in starts] + [len(sql)]
        for idx, (pos, kind, name) in enumerate(starts):
            body = sql[pos:bounds[idx + 1]]
            cut = re.search(r"^\s*DELIMITER\b", body, re.M)
            body = body[:cut.start()] if cut else body
            self.routines[name] = {
                "kind": kind.lower(),
                "body": body,
                "line": sql.count("\n", 0, pos) + 1,
                "calls": sorted(set(re.findall(r"\bCALL\s+(?:`?\w+`?\.)?`?(\w+)`?", body, re.I))
                               | {"sp_agg_" + s for s in re.findall(r"sp_run_agg_step\s*\(\s*'(\w+)'", body)}),
            }
        self._table_re = {t: re.compile(r"\b" + re.escape(t) + r"\b", re.I) for t in self.tables}

    def tables_in(self, text):
        reads, writes = set(), set()
        for t, rx in self._table_re.items():
            if rx.search(text):
                if re.search(WRITE_RE.format(t=re.escape(t)), text, re.I) or re.search(
                    r"sp_swap_public_table\s*\(\s*'" + re.escape(t), text, re.I
                ):
                    writes.add(t)
                else:
                    reads.add(t)
        return reads, writes

    def _parse_python(self):
        self.defs = defaultdict(list)      # name -> [{file, line, kind, sig, doc, refs, sql, owner}]
        self.refs_to = defaultdict(set)    # name -> {"file::function"}
        self.render_kwargs = defaultdict(set)  # file -> template context keys passed to render()
        self.py_strings = defaultdict(set)     # file -> interesting string literals (paths)
        self.template_refs = defaultdict(set)  # file -> template names it loads in code
        for rel in self.files:
            if not rel.endswith(".py") or not rel.startswith(("backend_scripts/", "discord_bot/")):
                continue
            src = self._read(rel)
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if re.match(r"^(assets|templates|data|classes|dungeons|items|pages)/[\w./{}-]+$", node.value):
                        self.py_strings[rel].add(node.value)
                # template names: get_template("x.html") args and {"template": "x.html"} entries
                if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "get_template" and node.args \
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    self.template_refs[rel].add(node.args[0].value)
                if isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if isinstance(k, ast.Constant) and k.value == "template" and isinstance(v, ast.Constant) and isinstance(v.value, str):
                            self.template_refs[rel].add(v.value)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "render":
                    self.render_kwargs[rel].update(k.arg for k in node.keywords if k.arg)
            for node in tree.body:
                self._index_node(rel, node, owner=None)
            # references: which names each function (or module scope) touches
            scopes = [(n.name, n) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for fname, fnode in scopes:
                for sub in ast.walk(fnode):
                    name = sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else None
                    if name and name != fname:
                        self.refs_to[name].add(f"{rel}::{fname}")
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for sub in ast.walk(node):
                        name = sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else None
                        if name:
                            self.refs_to[name].add(f"{rel}::<module>")

    def _index_node(self, rel, node, owner):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            names = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
                elif isinstance(sub, ast.Attribute):
                    names.add(sub.attr)
            doc = (ast.get_docstring(node) or "").strip().split("\n\n")[0].replace("\n", " ")
            self.defs[node.name].append({
                "file": rel, "line": node.lineno, "kind": "method" if owner else "function",
                "sig": f"{node.name}({', '.join(args)})", "doc": doc[:240], "refs": names, "owner": owner,
            })
        elif isinstance(node, ast.ClassDef):
            self.defs[node.name].append({"file": rel, "line": node.lineno, "kind": "class", "sig": node.name, "doc": "", "refs": set(), "owner": owner})
            for sub in node.body:
                self._index_node(rel, sub, owner=node.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if not name.isupper():
                return
            try:
                val = ast.literal_eval(node.value)
            except Exception:
                val = _fstring_text(node.value) if isinstance(node.value, ast.JoinedStr) else None
            if isinstance(val, str) and SQL_KEYWORDS.search(val):
                self.defs[name].append({"file": rel, "line": node.lineno, "kind": "sql", "sig": name, "doc": "", "refs": set(), "sql": val, "owner": None})

    def _parse_templates(self):
        self.templates = {}
        for rel in self.files:
            if not (rel.startswith("templates/") and rel.endswith(".html")):
                continue
            t = self._read(rel)
            self.templates[rel] = {
                "includes": sorted(set(re.findall(r"{%-?\s*(?:include|import|from)\s+[\"']([^\"']+)[\"']", t))),
                "macros": sorted(set(re.findall(r"{%-?\s*macro\s+(\w+)", t))),
                "assets": sorted(set(re.findall(r"[\"'](/?assets/(?:js|css)/[\w./-]+?\.(?:js|css))", t))),
                "vars": sorted(
                    (set(re.findall(r"{{-?\s*([a-z_]\w*)", t)) | set(re.findall(r"{%-?\s*(?:if|elif|for\s+[\w, ]+\s+in)\s+(?:not\s+)?([a-z_]\w*)", t)))
                    - _template_locals(t)
                ),
            }

    def _parse_workflows(self):
        self.invocations = defaultdict(list)  # script rel -> [{workflow, args}]
        for rel in self.files:
            if not (rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml"))):
                continue
            text = self._read(rel).replace("\\\n", " ")
            for m in re.finditer(r"python3?\s+(?:-u\s+)?(backend_scripts/[\w/]+\.py|-m\s+[\w.]+)([^\n]*)", text):
                script = m.group(1)
                if script.startswith("-m"):
                    script = script.split()[-1].replace(".", "/") + ".py"
                self.invocations[script].append({"workflow": rel, "args": " ".join(m.group(2).split())[:200]})

    def _parse_bot(self):
        self.bot_commands = {}
        for rel in self.files:
            if not (rel.startswith("discord_bot/cogs/") and rel.endswith(".py")):
                continue
            src = self._read(rel)
            groups = dict(re.findall(r"(\w+)\s*=\s*app_commands\.Group\(\s*name=\"([\w-]+)\"", src))
            for m in re.finditer(r"@(\w+(?:\.\w+)?)\.command\(\s*name=\"([\w-]+)\"(?:(?!\.command\().)*?async def (\w+)", src, re.S):
                deco, cmd, fn = m.groups()
                prefix = groups.get(deco.split(".")[-1]) if deco != "app_commands" else None
                full = f"{prefix} {cmd}" if prefix else cmd
                self.bot_commands[full] = {"file": rel, "function": fn, "line": src.count("\n", 0, m.start()) + 1}

    def _parse_gotchas(self):
        self.gotchas = {}
        for path in sorted(SKILLS_DIR.glob("*/SKILL.md")) + sorted(SKILLS_DIR.glob("*/ref/*.md")):
            meta, body = _frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
            is_ref = path.parent.name == "ref"
            gid = meta.get("name") or (path.stem if is_ref else path.parent.name)
            files = meta.get("files") or []
            self.gotchas[gid] = {
                "path": _rel(path),
                "skill": path.parent.parent.name if is_ref else path.parent.name,
                "is_ref": is_ref,
                "rule": meta.get("description", ""),
                "files": files if isinstance(files, list) else [files],
                "body": body,
            }

    # ------------------------------------------------------------ helpers

    def _sql_tables(self, d):
        return self.tables_in(d.get("sql", "")) if d["kind"] == "sql" else (set(), set())

    def fn_tables(self, d):
        """Tables a function touches through the *_SQL constants it references."""
        reads, writes = set(), set()
        for ref in d.get("refs", ()):
            for c in self.defs.get(ref, []):
                if c["kind"] == "sql":
                    r, w = self.tables_in(c["sql"])
                    reads |= r
                    writes |= w
        return reads, writes

    def gotchas_for(self, path):
        return [gid for gid, g in self.gotchas.items() if any(_match(path, pat) for pat in g["files"])]

    def callers(self, name, limit=30):
        out = sorted(self.refs_to.get(name, ()))
        own = {f"{d['file']}::{name}" for d in self.defs.get(name, [])}
        out = [c for c in out if c not in own]
        return out[:limit], len(out)

    # -------------------------------------------------------------- tools

    def overview(self):
        lines = ["# MythiStone knowledge map", "", "| domain | agent | preloaded skills | verify |", "|---|---|---|---|"]
        for dom, d in DOMAINS.items():
            lines.append(f"| {dom} | {d['agent']} | {', '.join(d['skills'])} | {d['verify']} |")
        lines += ["", "Domain by path (first match wins):"]
        lines += [f"- `{p}` -> {d}" for p, d in DOMAIN_GLOBS]
        n_sql = sum(1 for v in self.defs.values() for d in v if d["kind"] == "sql")
        lines += [
            "",
            f"Index: {len(self.tables)} tables, {len(self.routines)} routines, {n_sql} SQL constants, "
            f"{sum(1 for v in self.defs.values() for d in v if d['kind'] != 'sql')} python defs, {len(self.templates)} templates, "
            f"{len(self.bot_commands)} bot commands, {len(self.gotchas)} gotchas.",
            "",
            "Tools: kb_table, kb_symbol, kb_page, kb_bot_command, kb_file, kb_gotcha, kb_search, kb_lint.",
        ]
        return "\n".join(lines)

    def table(self, name):
        key = name.lower().strip("`")
        t = self.tables.get(key)
        if not t:
            near = [n for n in self.tables if key in n][:15]
            return f"No table `{name}`." + (f" Did you mean: {', '.join(near)}" if near else "")
        out = [f"# table `{key}`  (backend_scripts/database.sql:{t['line']})"]
        if t["storage"]:
            out.append(f"storage: {t['storage']}")
        out.append("columns: " + ", ".join(f"{c} {ty}" for c, ty in t["cols"]))
        if t["keys"]:
            out.append("keys: " + "; ".join(t["keys"]))
        rx = self._table_re[key]
        w_rx = re.compile(WRITE_RE.format(t=re.escape(key)), re.I)
        rw = [(n, "writes" if w_rx.search(r["body"]) or re.search(r"sp_swap_public_table\s*\(\s*'" + re.escape(key), r["body"]) else "reads")
              for n, r in self.routines.items() if rx.search(r["body"])]
        if rw:
            out.append("routines: " + ", ".join(f"{n} ({m})" for n, m in rw))
        consts = []
        for name_, ds in self.defs.items():
            for d in ds:
                if d["kind"] == "sql" and rx.search(d["sql"]):
                    consts.append((name_, d))
        if consts:
            out.append("SQL constants -> wrapper fns:")
            for cname, d in consts:
                users = sorted({c.split("::")[1] for c in self.refs_to.get(cname, ()) if c.split("::")[1] != "<module>"})
                mode = "W" if w_rx.search(d["sql"]) else "R"
                out.append(f"- {cname} [{mode}] ({d['file']}:{d['line']}) -> {', '.join(users) or '-'}")
        g = [gid for gid, gg in self.gotchas.items() if re.search(r"\b" + re.escape(key) + r"\b", gg["body"])]
        if g:
            out.append("gotchas mentioning it: " + ", ".join(g))
        return "\n".join(out)

    def symbol(self, name):
        name = name.strip().rstrip("()")
        ds = self.defs.get(name)
        if not ds and name in self.routines:
            r = self.routines[name]
            reads, writes = self.tables_in(r["body"])
            callers = [n for n, rr in self.routines.items() if name in rr["calls"]]
            py = [c for c in self.refs_to.get(name, ())]
            body = r["body"].strip().splitlines()
            return "\n".join([
                f"# {r['kind']} `{name}`  (backend_scripts/database.sql:{r['line']}, {len(body)} lines)",
                f"reads: {', '.join(sorted(reads)) or '-'}",
                f"writes: {', '.join(sorted(writes)) or '-'}",
                f"calls: {', '.join(r['calls']) or '-'}",
                f"called by routines: {', '.join(callers) or '-'}",
                f"referenced from python: {', '.join(sorted(py)) or '-'}",
                "(read the body at the line above if you need it)",
            ])
        if not ds:
            near = sorted({n for n in list(self.defs) + list(self.routines) if name.lower() in n.lower()})[:20]
            return f"No symbol `{name}`." + (f" Candidates: {', '.join(near)}" if near else "")
        out = []
        for d in ds:
            where = f"{d['file']}:{d['line']}"
            out.append(f"# {d['kind']} `{(d['owner'] + '.') if d['owner'] else ''}{d['sig']}`  ({where})")
            if d["doc"]:
                out.append(f"doc: {d['doc']}")
            if d["kind"] == "sql":
                r, w = self.tables_in(d["sql"])
                out.append(f"tables read: {', '.join(sorted(r)) or '-'}; written: {', '.join(sorted(w)) or '-'}")
                sql_lines = d["sql"].strip().splitlines()
                out.append("```sql\n" + "\n".join(sql_lines[:40]) + ("\n-- ... truncated" if len(sql_lines) > 40 else "") + "\n```")
            else:
                r, w = self.fn_tables(d)
                if r or w:
                    out.append(f"tables via SQL consts: read {', '.join(sorted(r)) or '-'}; write {', '.join(sorted(w)) or '-'}")
                consts = sorted(x for x in d["refs"] if any(c["kind"] == "sql" for c in self.defs.get(x, [])))
                if consts:
                    out.append("uses SQL: " + ", ".join(consts))
                callees = sorted(x for x in d["refs"] if x != name and any(c["kind"] in ("function", "method") for c in self.defs.get(x, [])))
                if callees:
                    out.append("calls (in-repo): " + ", ".join(callees[:30]))
        callers, total = self.callers(name)
        out.append(f"referenced by ({total}): " + (", ".join(callers) if callers else "-"))
        return "\n".join(out)

    def templates_of(self, gen):
        """Templates a generator renders: its workflow --template args plus .html literals in its code."""
        found = {t for inv in self.invocations.get(gen, []) for t in re.findall(r"--template\s+(\S+)", inv["args"])}
        for lit in self.template_refs.get(gen, ()):
            found |= {t for t in self.templates if t.split("/")[-1] == lit.split("/")[-1]}
        return sorted(t for t in found if t in self.templates)

    def _page_candidates(self, name):
        n = name.lower().replace("generate", "").replace(".py", "").replace(".html", "").replace("templates/", "").strip("_- ")
        gens = [f for f in self.files if re.match(r"backend_scripts/generate\w+\.py$", f) and n in f.lower()]
        tpls = [t for t in self.templates if n in t.lower()]
        for g in gens:
            tpls += [t for t in self.templates_of(g) if t not in tpls]
        for g in self.files:
            if re.match(r"backend_scripts/generate\w+\.py$", g) and g not in gens and set(self.templates_of(g)) & set(tpls):
                gens.append(g)
        return gens, tpls

    def page(self, name):
        gens, tpls = self._page_candidates(name)
        if not gens and not tpls:
            return f"No page matching `{name}`. Generators: " + ", ".join(
                f[len("backend_scripts/"):] for f in self.files if re.match(r"backend_scripts/generate\w+\.py$", f))
        out = [f"# page `{name}`"]
        touched = set(gens) | set(tpls)
        for g in gens:
            out.append(f"## generator {g}")
            for inv in self.invocations.get(g, []):
                out.append(f"- run by {inv['workflow']}: {inv['args'] or '(no args)'}")
            kw = sorted(self.render_kwargs.get(g, ()))
            if kw:
                out.append("render() context keys: " + ", ".join(kw))
            fns = set()
            for ds in self.defs.values():
                for d in ds:
                    if d["file"] == g:
                        fns |= {x for x in d["refs"] if any(c["file"] == "backend_scripts/databaseConnector.py" and c["kind"] == "function" for c in self.defs.get(x, []))}
            if fns:
                out.append("databaseConnector fns: " + ", ".join(sorted(fns)))
            paths = sorted(p for p in self.py_strings.get(g, ()) if p.startswith(("assets/", "data/")))
            if paths:
                out.append("paths referenced: " + ", ".join(paths[:30]))
        for t in tpls:
            info = self.templates[t]
            out.append(f"## template {t}")
            out.append("includes/imports: " + (", ".join(info["includes"]) or "-"))
            if info["macros"]:
                out.append("defines macros: " + ", ".join(info["macros"]))
            out.append("assets: " + (", ".join(a.lstrip("/") for a in info["assets"]) or "-"))
            out.append("top-level vars used: " + ", ".join(info["vars"][:60]))
            touched |= {a.lstrip("/") for a in info["assets"]}
        g = sorted({gid for p in touched for gid in self.gotchas_for(p)})
        if g:
            out.append("gotchas: " + ", ".join(g))
        return "\n".join(out)

    def bot_command(self, name):
        key = " ".join(name.strip().lstrip("/").split())
        hits = {k: v for k, v in self.bot_commands.items() if k == key} or {k: v for k, v in self.bot_commands.items() if key in k}
        if not hits:
            return "No bot command matching. Commands: " + ", ".join(sorted("/" + k for k in self.bot_commands))
        out = []
        for full, c in sorted(hits.items())[:8]:
            out.append(f"# /{full}  ({c['file']}:{c['line']}, handler {c['function']})")
            d = next((d for d in self.defs.get(c["function"], []) if d["file"] == c["file"]), None)
            if not d:
                continue
            seen, frontier, fns, other = set(), [d], set(), set()
            while frontier:  # follow same-file helpers one hop at a time to reach the DB calls
                cur = frontier.pop()
                for ref in cur["refs"]:
                    for cand in self.defs.get(ref, []):
                        if cand["file"] == "backend_scripts/databaseConnector.py" and cand["kind"] == "function":
                            fns.add(ref)
                        elif cand["file"] == c["file"] and ref not in seen and cand["kind"] in ("function", "method"):
                            seen.add(ref)
                            frontier.append(cand)
                        elif cand["file"].startswith("discord_bot/") and cand["file"] != c["file"] and cand["kind"] in ("function", "method"):
                            other.add(f"{cand['file'].split('/')[-1][:-3]}.{ref}")
            out.append("helpers: " + (", ".join(sorted(seen)) or "-"))
            out.append("databaseConnector fns: " + (", ".join(sorted(fns)) or "-"))
            out.append("other bot modules (site_data = site JSON, not DB): " + (", ".join(sorted(other)) or "-"))
        g = sorted({gid for v in hits.values() for gid in self.gotchas_for(v["file"])})
        if g:
            out.append("gotchas: " + ", ".join(g))
        return "\n".join(out)

    def file(self, path):
        rel = path.replace("\\", "/")
        if os.path.isabs(rel):
            try:
                rel = _rel(rel)
            except ValueError:
                pass
        dom = domain_of(rel)
        out = [f"# {rel}", f"domain: {dom or '-'}" + (f" (agent `{DOMAINS[dom]['agent']}`, skills {', '.join(DOMAINS[dom]['skills'])})" if dom else "")]
        if dom:
            out.append(f"verify: {DOMAINS[dom]['verify']}")
        gs = self.gotchas_for(rel)
        out.append("gotchas: " + ("; ".join(f"{g} ({self.gotchas[g]['path']}): {self.gotchas[g]['rule']}" for g in gs) if gs else "-"))
        if rel in self.invocations:
            out.append("run by: " + "; ".join(f"{i['workflow']} {i['args']}" for i in self.invocations[rel]))
        if rel in self.templates:
            users = [f for f in self.templates if any(rel.endswith(i) for i in self.templates[f]["includes"])]
            gens = [g for g in self.files if re.match(r"backend_scripts/generate\w+\.py$", g) and rel in self.templates_of(g)]
            out.append("included by: " + (", ".join(users) or "-"))
            out.append("rendered by: " + (", ".join(gens) or "-"))
        if rel.startswith("assets/"):
            users = [t for t, info in self.templates.items() if any(a.lstrip("/") == rel for a in info["assets"])]
            out.append("loaded by templates: " + (", ".join(users) or "-"))
        if rel.endswith(".py"):
            mine = sorted(f"{n} :{d['line']}" for n, ds in self.defs.items() for d in ds if d["file"] == rel and d["kind"] != "method")
            out.append(f"top-level defs ({len(mine)}): " + ", ".join(mine[:80]) + (" ..." if len(mine) > 80 else ""))
        return "\n".join(out)

    def gotcha(self, gid):
        g = self.gotchas.get(gid)
        if not g:
            near = [k for k in self.gotchas if gid.lower() in k.lower()]
            return f"No gotcha `{gid}`." + (f" Candidates: {', '.join(near)}" if near else f" Known: {', '.join(sorted(self.gotchas))}")
        return f"# {gid}  ({g['path']})\nfiles: {', '.join(g['files']) or '-'}\n\n{g['body'].strip()}"

    def search(self, query, limit=30):
        q = query.lower()
        out = []
        for gid, g in self.gotchas.items():
            if q in gid.lower() or q in g["rule"].lower():
                out.append(f"gotcha {gid}: {g['rule'][:200]}")
            else:
                for line in g["body"].splitlines():
                    if q in line.lower():
                        out.append(f"gotcha {gid}: ...{line.strip()[:200]}")
                        break
        out += [f"table {t}" for t in self.tables if q in t]
        out += [f"routine {r}" for r in self.routines if q in r.lower()]
        out += [f"{d['kind']} {n} ({d['file']}:{d['line']})" for n, ds in self.defs.items() if q in n.lower() for d in ds]
        out += [f"bot /{c}" for c in self.bot_commands if q in c]
        return "\n".join(out[:limit]) + (f"\n... {len(out) - limit} more" if len(out) > limit else "") if out else f"No match for `{query}`."

    def lint(self):
        """Stale references in curated knowledge: cited paths/symbols that no longer exist."""
        corpus_files = set(self.files)
        known = set(self.defs) | set(self.routines) | set(self.tables)
        problems = []
        generated = ("assets/json/", "data/bot_cache/", "data/state/", "sim_results", "simc_profiles", "_site")
        for gid, g in sorted(self.gotchas.items()):
            for pat in g["files"]:
                if not any(_match(f, pat) for f in corpus_files):
                    problems.append(f"{g['path']}: files glob `{pat}` matches nothing")
            prose = re.sub(r"```.*?```", "", g["body"], flags=re.S)  # examples in fences are not references
            for tok in set(re.findall(r"`([^`\s]+)`", prose)):
                t = tok.rstrip("(),.:;")
                if re.search(r"[*<>{}$]", t):
                    continue
                if "/" in t and re.search(r"\.(py|sql|html|js|css|yml|yaml|sh|json|md)$", t):
                    t = t.lstrip("/")
                    if t.startswith(generated) or t.startswith("plugins/"):
                        continue
                    if not any(f == t or f.endswith("/" + t) for f in corpus_files):
                        problems.append(f"{g['path']}: path `{tok}` not found")
                elif re.fullmatch(r"(sp|ev|fn)_\w+|fetch_\w+|[A-Z][A-Z0-9_]+_SQL", t.rstrip("()")):
                    if t.rstrip("()") not in known:
                        problems.append(f"{g['path']}: symbol `{tok}` not found")
            for ref in re.findall(r"\[\[([\w-]+)\]\]", re.sub(r"`[^`]*`", "", prose)):
                if ref not in self.gotchas:
                    problems.append(f"{g['path']}: link [[{ref}]] has no gotcha")
        return "kb lint: clean" if not problems else f"kb lint: {len(problems)} problem(s)\n" + "\n".join(problems)

    # ------------------------------------------------------ domain indexes

    def write_indexes(self):
        """Regenerate the gotcha table at the end of each domain SKILL.md from its ref/ frontmatter."""
        header = "| id | rule | files |\n|---|---|---|\n"
        done = []
        for skill in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            refs = sorted((skill.parent / "ref").glob("*.md"))
            text = skill.read_text(encoding="utf-8")
            if not refs or header not in text:
                continue
            rows = []
            for ref in refs:
                meta, _ = _frontmatter(ref.read_text(encoding="utf-8", errors="ignore"))
                rule = re.split(r"\s+Use (?:when|whenever|before|for)\b", meta.get("description", ""))[0].rstrip(".")
                files = meta.get("files") or []
                rows.append(f"| `{meta.get('name', ref.stem)}` | {rule} | {', '.join('`' + f + '`' for f in files)} |")
            skill.write_text(text[: text.index(header) + len(header)] + "\n".join(rows) + "\n", encoding="utf-8")
            done.append(f"{skill.parent.name} ({len(rows)})")
        return "rewrote gotcha tables: " + ", ".join(done)

    # ---------------------------------------------------------- map files

    def write_map(self):
        MAP_DIR.mkdir(parents=True, exist_ok=True)
        (MAP_DIR / "overview.md").write_text(self.overview() + "\n")
        lines = ["# Tables (generated by .claude/kb/kb.py; use `kb.py table <name>` for readers/writers)", ""]
        for t, info in sorted(self.tables.items()):
            lines.append(f"- **{t}**: " + ", ".join(c for c, _ in info["cols"]))
        lines += ["", "# Routines", ""]
        for r, info in sorted(self.routines.items()):
            reads, writes = self.tables_in(info["body"])
            lines.append(f"- **{r}** ({info['kind']}): writes {', '.join(sorted(writes)) or '-'}; reads {', '.join(sorted(reads)) or '-'}")
        (MAP_DIR / "database.md").write_text("\n".join(lines) + "\n")
        lines = ["# databaseConnector functions -> tables (generated)", ""]
        for n, ds in sorted(self.defs.items()):
            for d in ds:
                if d["file"] == "backend_scripts/databaseConnector.py" and d["kind"] == "function":
                    r, w = self.fn_tables(d)
                    lines.append(f"- `{d['sig']}` :{d['line']} R[{', '.join(sorted(r))}] W[{', '.join(sorted(w))}]")
        (MAP_DIR / "connector.md").write_text("\n".join(lines) + "\n")
        lines = ["# Pages (generated)", ""]
        for g in sorted(f for f in self.files if re.match(r"backend_scripts/generate\w+\.py$", f)):
            tpl = self.templates_of(g)
            lines.append(f"- {g} -> {', '.join(tpl) or '-'}")
        (MAP_DIR / "pages.md").write_text("\n".join(lines) + "\n")
        lines = ["# Discord bot commands (generated)", ""] + [f"- /{k} -> {v['file']}::{v['function']}" for k, v in sorted(self.bot_commands.items())]
        (MAP_DIR / "bot.md").write_text("\n".join(lines) + "\n")
        lines = ["# Gotchas (generated index; bodies live in .claude/skills/*/ref/)", ""]
        for gid, g in sorted(self.gotchas.items()):
            lines.append(f"- **{gid}** ({g['path']}) [{', '.join(g['files'])}]: {g['rule']}")
        (MAP_DIR / "gotchas.md").write_text("\n".join(lines) + "\n")
        return f"wrote {MAP_DIR.relative_to(ROOT)}/{{overview,database,connector,pages,bot,gotchas}}.md"


TOOLS = {
    "kb_overview": ("Domains, owning agents, preloaded skills, verification steps, index stats. Call first when routing a task.", [], lambda kb: kb.overview()),
    "kb_table": ("A MySQL table: columns, keys, storage, routines and SQL constants/wrapper fns that read or write it, related gotchas.", ["name"], lambda kb, name: kb.table(name)),
    "kb_symbol": ("A python fn/class/*_SQL constant or a stored proc/event: location, signature, SQL text, tables, callers, callees.", ["name"], lambda kb, name: kb.symbol(name)),
    "kb_page": ("A rendered page by slug, generator or template: workflow invocation, render() keys, connector fns, includes, assets, gotchas.", ["name"], lambda kb, name: kb.page(name)),
    "kb_bot_command": ("A Discord slash command (e.g. 'spec gear'): handler, helpers, databaseConnector fns, gotchas.", ["name"], lambda kb, name: kb.bot_command(name)),
    "kb_file": ("Any repo path: domain, owning agent, verification, gotchas whose files match, who runs/includes/loads it, its defs.", ["path"], lambda kb, path: kb.file(path)),
    "kb_gotcha": ("Full body of one curated gotcha by id.", ["id"], lambda kb, id: kb.gotcha(id)),
    "kb_search": ("Search gotchas, tables, routines, python symbols and bot commands by substring.", ["query"], lambda kb, query: kb.search(query)),
    "kb_lint": ("Report stale paths/symbols/links cited by the curated gotchas.", [], lambda kb: kb.lint()),
}


def main(argv):
    kb = KB()
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--write":
        print(kb.write_map())
        return 0
    if argv[0] == "--index":
        print(kb.write_indexes())
        return 0
    cmd = argv[0]
    name = cmd if cmd.startswith("kb_") else "kb_" + {"bot": "bot_command"}.get(cmd, cmd.replace("-", "_"))
    if name not in TOOLS:
        print(f"unknown command {argv[0]}; one of: {', '.join(t[3:] for t in TOOLS)}", file=sys.stderr)
        return 2
    _, params, fn = TOOLS[name]
    print(fn(kb, *[" ".join(argv[1:])] if params else []))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
