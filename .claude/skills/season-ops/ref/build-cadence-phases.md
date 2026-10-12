---
name: build-cadence-phases
description: buildPages schedules daily/every-3-days/weekly by phase, gated on days since the most recent content update (season start or a .5/.7 patch). Use when touching the buildPages cron, computeBuildPhase.py, the resolve-season cadence gate, or reasoning about how often the site rebuilds.
kind: coupling
files:
  - .github/workflows/buildPages.yml
  - backend_scripts/computeBuildPhase.py
---

# Build cadence: what the gate is tied to

`backend_scripts/computeBuildPhase.py` decides whether a scheduled build runs (its header comment
has the phases). What ties it to other files:

- **The cron in `.github/workflows/buildPages.yml` skips Wednesday.** Wednesday builds come from
  the `workflow_run` of `getStaticData.yml` and are never gated.
- **Everything downstream hangs off `prepare-sims`.** A gated-off day skips the whole pipeline and
  ends green with no deploy.
- **Patch go-lives are snapped to the reset week twice**, here and in
  `generateDashboardPage.compute_patch_annotations`. Change one, change the other.
- **Before the season starts it reports `should_build=false` and does not raise**, although the
  repo fails loudly elsewhere. The `has_data` gate already owns the clean pre-season skip, and a
  crash would turn the job red.

Related: [[artifact-only-deploy]], [[blizzard-preseason-period]].
