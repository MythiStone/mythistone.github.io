---
name: knowledgebase-authoring
description: How MythiStone durable knowledge is laid out (code-derived map vs curated gotchas in domain skills) and how to record a finding (ask first, present tense, no history or line numbers). Use when adding or editing a gotcha, a domain skill or AGENTS.md, or deciding whether to record something after a task.
files:
  - .claude/skills/*
  - .claude/kb/*
  - AGENTS.md
---

# Authoring the knowledgebase

Durable repo knowledge has two layers. Never use a tool's private auto-memory or the subagent
`memory:` field. Neither transfers across machines and tools, and both split knowledge per agent.

- **The map is generated, never hand-written.** `.claude/kb/kb.py` parses tables, procs, `*_SQL`
  constants, connector functions, callers, generator → template → asset wiring and bot commands from
  the code on demand (served by the `mythi-kb` MCP server). Do not restate any of that in prose: a
  column list, a function inventory or "X calls Y" in a gotcha goes stale. If the map gets a fact
  wrong, fix the parser in `kb.py`.
- **Gotchas are curated.** Gotchas cover what the code cannot tell you: why something is the way it
  is, cross-file couplings, traps, and rejected approaches. Each gotcha is one file,
  `.claude/skills/<domain>/ref/<id>.md`, under the domain skill that owns it (`database`, `pages`,
  `frontend`, `discord-bot`, `collector-simc`, `season-ops`, `social`). Only domain skills appear
  in the per-turn skill listing, so never add a new top-level skill for a single gotcha.
- **`AGENTS.md`** holds always-on repo truth and the routing table. Keep it short. It is loaded
  every session.

## When to record

When a task produced durable knowledge (non-obvious mechanics, cross-file coupling, gotchas,
corrected assumptions), **ask the user for permission to record it** as the last line of your final
message. Do not record first, and do not record silently. A domain agent proposes findings in its
handoff note; the main session asks the user.

- Skip the ask when nothing is new: planning-only work, or a behavior a gotcha already documents.
- Judge "new" against the knowledgebase, not the code. A fact derivable from the code still
  deserves a gotcha if it is a trap nobody would spot without reading three files.

## How to write a gotcha

```markdown
---
name: <id, kebab-case, unique across all domains>
description: <one sentence stating the rule>. Use when <the trigger>.
files:
  - <repo-relative glob of every file where this rule bites>
---

# Title

Body: the rule, why it holds, and how to work with it.
```

- `files:` drives `kb_file`, the per-file hook reminder and the domain index. A gotcha with an
  empty or wrong `files:` list is never surfaced.
- After adding, renaming or editing a gotcha's frontmatter, run `python .claude/kb/kb.py --index`
  (regenerates the gotcha table in each domain `SKILL.md`) and `python .claude/kb/kb.py lint`
  until it is clean. `python .claude/kb/kb.py --strict` also lists cited names that appear nowhere
  in the source; review those (external API fields and placeholders are expected), since a renamed
  function only shows up there.
- Quote a `description` that contains `: ` or ` #` (`description: "..."`). Unquoted, YAML rejects
  the first and silently truncates at the second.
- **State only the current truth, never history.** No "this used to be X", changelogs, migration
  notes or dated lines. When behavior changes, edit the gotcha so it reads as if the new behavior
  was always the behavior.
- **No line-number references.** Identify code by file, function, proc, SQL constant, class or CSS
  selector. Lines shift, and `kb_symbol` gives the live location.
- **One rule per gotcha.** Link related gotchas with `[[id]]`. `kb lint` rejects links to ids
  that do not exist.
