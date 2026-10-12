---
name: dungeon-npc-portrait-icons
description: Which creature-image sources work for the dungeon page NPC portraits and which were tried and rejected, plus the order and the deploy path the icons depend on. Use when touching fetchNpcIcons.py, the NPC self-heal in generateDungeonPages.py, the artifact paths in buildPages.yml, or when a locally rendered dungeon page shows no NPC icons.
kind: external
files:
  - backend_scripts/fetchNpcIcons.py
  - backend_scripts/generateDungeonPages.py
  - .github/workflows/buildPages.yml
---

# Dungeon NPC portrait icons

The working pipeline is in the header comment of `backend_scripts/fetchNpcIcons.py`.

## Sources that do not work

- **Blizzard `render.worldofwarcraft.com` and the creature-display media API:** about 44% coverage,
  the newest creatures answer 403.
- **Scraping Wowhead NPC pages for the display id:** Cloudflare 403 from datacenter and CI
  addresses. `old.wow.tools` is dead.
- **keystone.guru portraits:** behind a hashed CDN, and hotlinking is a terms-of-service problem.

Self-hosting Wowhead's thumbnails is a mild etiquette gray area, accepted for the full coverage.

## What the icons depend on

- **Local order:** after seeding, run `fetchNpcInfo.py`, then `fetchNpcIcons.py`, then render. The
  seeder samples npc ids from `npcs.json`, so in any other order the page looks icon-less and the
  source looks broken when it is not.
- **Self-healed icons reach the site only through the build artifact.** `generateDungeonPages.py`
  fetches missing portraits during the build, and they deploy only because `data/icons` is in the
  `generated-site` upload paths of `.github/workflows/buildPages.yml`. Removing that path makes
  week-one icons 404 on the site while they still work locally ([[artifact-only-deploy]]).
- The self-heal needs `aiohttp` in the build environment. A name that is still unresolved after it
  fails the build. A missing icon falls back to text.
