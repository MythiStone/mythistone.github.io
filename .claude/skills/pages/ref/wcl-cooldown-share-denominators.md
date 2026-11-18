---
name: wcl-cooldown-share-denominators
description: Warcraft Logs cooldown relation, usage and target tables can cover fewer runs than the cooldown cast table, so their shares never divide by its casts. Use when computing a percentage on the spec page's Cooldown Usage modal.
kind: coupling
files:
  - backend_scripts/generateSpecCooldowns.py
  - backend_scripts/wclPullBuilder.py
---

# Compare cooldown tables only with their own coverage

`fetch_wcl_spec_cooldowns` and `fetch_wcl_spec_pulls` cover every processed run in the window.
`fetch_wcl_spec_relations`, `fetch_wcl_spec_usage` and `fetch_wcl_spec_targets` only hold runs
processed since their collection in `run_deltas` last changed shape, and processed runs are never
collected again. In `build_dungeon`, a share built from those three uses a denominator from the
same group, such as the usage table's casts. Dividing by the cast table understates every share
until the 14 day window has refilled.
