---
name: season-snapshot-archive
description: Each season's built _site is force-pushed to a season-<id> branch in a separate archive repo as cold storage before the DB wipe. Use when touching the "Archive snapshot to season branch" step in buildPages.yml or reasoning about where old-season sites live.
kind: external
files:
  - .github/workflows/buildPages.yml
---

# Season snapshot archive

Every build force-pushes the built `_site` to branch `season-<blizzard_season_id>` of the separate
repo `MythiStone/Mythistone_Archive` (the "Archive snapshot" step of
`.github/workflows/buildPages.yml`). When the season id increments, the next build targets a new
branch and the old one freezes.

- **Manual prerequisites:** the archive repo and a write-enabled deploy key in the
  `ARCHIVE_DEPLOY_KEY` secret.
- **It is a separate repo** so that season branches are not pulled by every clone of the main repo.
- **Cold storage only.** The site hardcodes its domain and root-absolute `/assets/` links, so a
  snapshot serves correctly only from a URL root.

The wipe that follows it: [[season-rollover-wipe]].
