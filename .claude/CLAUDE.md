# CLAUDE.md

@../AGENTS.md

Claude Code specifics. Everything else is in AGENTS.md, imported above. Do not duplicate it here.

- The repo's `planner` agent replaces the built-in Plan agent, which is denied in settings.
  `Explore` is the repo's own knowledge-map-first version.
- Preview pages in the Browser pane through `.claude/launch.json` (port 8099). The render procedure
  is the `local-test-render` skill. Output dirs (`dungeons/`, `classes/`, `items/`, `pages/`) are
  gitignored, safe to write.
