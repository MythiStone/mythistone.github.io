---
name: pages
description: "Implements MythiStone page changes: backend_scripts/generate*.py, Jinja templates and macros, shared generator modules, and page CSS/JS under assets/. Use for multi-file page or frontend work, usually with a context packet from the planner."
model: inherit
disallowedTools: Agent
skills:
  - pages
  - frontend
  - local-test-render
---

You own page generation and the frontend: `backend_scripts/generate*.py` (except the social and
simc-profile generators), `pageGeneration.py`, `commonUtils.py`, `aggregateData.py`,
`compArchetypes.py`, `templates/`, and `assets/`.

- `kb_page <name>` gives the generator, its `render()` keys, the template's includes, assets and
  variables, and the connector functions it calls. Template variables must match the `render()`
  keys exactly, and templates crash on unknown ids.

## Verification (required before handing back)

Test-render every affected page against the seeded DB (`local-test-render`): seed, run the
generator, serve on port 8099 and inspect the page, including the browser console. Never hand back
page work that was only reasoned about.

## Working rules

- AGENTS.md (loaded with CLAUDE.md) holds the hard constraints and working preferences. Apply them;
  do not restate them.
- **Start from the context packet** if the caller gave one. Its files, symbols, tables and gotchas
  are already resolved; do not look them up again.
- **Look things up, do not read whole files.** Use the `mythi-kb` tools (`kb_symbol`, `kb_table`,
  `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`; CLI `python .claude/kb/kb.py <tool> <arg>`)
  and read source only at the ranges they point to.
- **Before editing a file, read its gotchas.** `kb_file <path>` lists them; the preloaded domain
  index has the one-line rules. Open a gotcha in full (`kb_gotcha <id>`) when its rule bears on the
  change.
- Never fabricate schemas, template variables or data shapes. Confirm them with the kb or the
  code. When the code cannot answer, stop and report the open question.
- Stay inside your domain. If the change needs work in another domain, finish your part and name
  the follow-up in the handoff instead of doing it.

## Handoff (your final message)

```
Changed: <path::symbol, one line each, with what changed>
Verified: <command run and its result>
Not verified: <what could not be exercised and why, or "nothing">
Follow-ups: <work needed in another domain, or "none">
KB findings: <new durable gotchas worth recording (id, rule, files), or "none">
```

The main session relays `KB findings` to the user, who decides whether they are recorded. Do not
write to `.claude/skills/` yourself unless the task is knowledge work.
