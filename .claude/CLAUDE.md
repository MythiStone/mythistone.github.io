# CLAUDE.md

@../AGENTS.md

Claude Code specifics. Everything else is in AGENTS.md, imported above. Do not duplicate it here.

- The repo's `planner` agent replaces the built-in Plan agent, which is denied in settings.
  `Explore` is the repo's own knowledge-map-first version. Domain agents: `database`, `pages`,
  `discord-bot`, `collector-infra`.
- Serve the repo root on **port 8099** (matches `.claude/launch.json`) and open the page in the
  Browser pane: `python -m http.server 8099 --bind 127.0.0.1`. Output dirs (`dungeons/`,
  `classes/`, `items/`, `pages/`) are gitignored, safe to write.
