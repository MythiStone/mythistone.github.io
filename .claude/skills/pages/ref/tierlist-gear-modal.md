---
name: tierlist-gear-modal
description: The sim tierlist's gear sets and its gear modal span two generators, three CI jobs and catalogs baked by other pages. Use when adding or changing a gear set, editing the tierlist_gear.json emit in generateSimcProfiles.py, generateTierlistPage.py, assets/js/tierlist-modal.js, or the sim jobs in buildPages.yml.
kind: coupling
files:
  - assets/js/tierlist-modal.js
  - assets/js/loadout-view.js
  - backend_scripts/generateSimcProfiles.py
  - backend_scripts/generateTierlistPage.py
  - templates/simc_tierlist.html
  - .github/workflows/buildPages.yml
---

# Sim tierlist: gear sets and the gear modal

- **A gear set is listed in several places.** `GEAR_SETS` in
  `backend_scripts/generateSimcProfiles.py` and in `backend_scripts/generateTierlistPage.py`, the
  `gearset` matrix of the `simulate` job in `.github/workflows/buildPages.yml`, `build_mock_results`
  and the methodology copy in `templates/simc_tierlist.html`. Each set adds one sim leg per target
  count.
- **The tierlist generator has no database.** `generateTierlistPage.py` runs in the credential-free
  `assemble` job. The modal's data is therefore written by `generateSimcProfiles.py` in the
  `prepare-sims` job as `tierlist_gear.json`, rides the profiles artifact, and is copied into
  `assets/json/` by `assemble`.
- **The modal reuses catalogs baked by other generators** (talent trees, the gem and enchant index,
  the items index), so those pages must be built in the same run.
- **`assets/js/loadout-view.js` loads before `assets/js/tierlist-modal.js`**, and it holds the
  second copy of the loadout decoder ([[analyzer-page]]).
- The top-50 talent code is `loadout_text`, the real export string. `loadout_key` is a synthetic
  collector token and not a talent code.

Related: [[deep-links]], [[item-quality-from-bonus]].
