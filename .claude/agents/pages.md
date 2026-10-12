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

The paths this domain owns, the shared working rules and the handoff format are in AGENTS.md under
"Knowledge and routing".

## Verification (required before handing back)

Test-render every affected page against the seeded DB (`local-test-render`): seed, run the
generator, serve on port 8099 and inspect the page, including the browser console. Never hand back
page work that was only reasoned about.
