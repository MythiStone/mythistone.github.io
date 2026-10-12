---
name: analyzer-page
description: The analyzer's talent tree is assembled from two artifacts built by two different workflows and decoded by two hand-kept copies of the loadout decoder. Use when editing assets/js/analyzer.js, assets/js/loadout-view.js, generateAnalyzerPage.py, processTalents.py output, or assets/css/analyzer.css.
kind: coupling
files:
  - assets/js/analyzer.js
  - assets/js/loadout-view.js
  - backend_scripts/generateAnalyzerPage.py
  - assets/css/analyzer.css
  - templates/analyzer.html
---

# Analyzer page: what must stay in step

- **Tree geometry and meta loadouts ship separately on purpose.** Geometry comes from
  `data/static/talents/`, which the weekly `getStaticData.yml` refreshes, and is baked by
  `generateAnalyzerPage.write_talent_trees`. The meta loadouts are in `spec_meta`, baked by
  `generateSpecPages.py` in the frequent `buildPages.yml`. Geometry baked into `spec_meta` would go
  stale between talent dumps.
- **The committed talent files must carry `fullNodeOrder`, the nodes and their positions.** Without
  them `write_talent_trees` skips the spec and the page falls back to a flat chip list.
- **The loadout decoder exists twice**, as `decodeLoadout` in `assets/js/analyzer.js` and in
  `assets/js/loadout-view.js`. A format change belongs in both.
- **The Gear and Talents cards flip to their narrow layout at one shared container width**
  (`assets/css/analyzer.css`). The fully wide state therefore only appears on large monitors. That
  is an accepted tradeoff, not a bug: an even split and lower thresholds were rejected.

Related: [[tierlist-gear-modal]].
