---
name: top-trends-bar
description: The Top Trends bar depends on a CI step order, on two stored weeks and on a stable archetype key. Use when the bar is missing, or when editing snapshotTrends.py, pageGeneration.build_trends / build_global_trends, the buildPages.yml step order, or the trend seeding in the local seeder.
kind: coupling
files:
  - backend_scripts/snapshotTrends.py
  - backend_scripts/pageGeneration.py
  - templates/trends_bar.html
  - templates/top_chrome.html
  - assets/js/trends-bar.js
---

# Top Trends bar: what it depends on

The design is in the header comment of `backend_scripts/snapshotTrends.py`. What sits outside it:

- **`snapshotTrends.py` runs before the generators**, in `.github/workflows/buildPages.yml` and
  locally. Without its live JSON the bar hides.
- **The bar shows nothing until two weekly snapshots exist**, about a week into a season. Locally,
  `backend_scripts/localDev/seed_test_db.py` seeds a previous week, so the bar renders after one
  `snapshotTrends.py` run ([[local-test-render]]).
- **The archetype feed keys on the most-played member, not on the displayed core.** The displayed
  core of a family flips whenever a sister comp posts a higher key, so `compArchetypes._family`
  also exposes a stable key for the snapshot.

Related: [[spec-team-comps]], [[frontend-json-dungeon-keys]].
