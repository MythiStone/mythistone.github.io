---
name: wcl-dungeon-pull-id
description: Warcraft Logs boss example links use the dungeonPulls id, and trash examples open by time window because a trash pull has no reliable pull link. Use when linking to a WCL pull or matching a rebuilt pull to a WCL one.
kind: external
files:
  - backend_scripts/wclPullBuilder.py
  - backend_scripts/wclClient.py
  - backend_scripts/pageGeneration.py
---

# Linking to a WCL pull

`dungeonPulls` ids can skip numbers, so an id is not the pull's position in the list. Boss examples
link with the `id` that `wcl_pull_id` returns for the winning attempt. WCL merges chained trash pulls
that `wclPullBuilder` keeps apart, and a trash `pull=` link has opened the pull after the intended
one, so `wcl_example_url` opens trash pulls by their own time window.
