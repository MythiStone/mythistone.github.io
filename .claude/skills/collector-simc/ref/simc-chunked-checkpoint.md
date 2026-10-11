---
name: simc-chunked-checkpoint
description: simc BiS runs are chunked and checkpointed to simc_bis_progress so heavy specs resume across the ~daily collector restart. Use when editing run_simc_bis / _build_run / _next_stage_work / _select_target_spec / prep snapshots in simcBis.py, or the simc_bis_progress[_meta] tables.
files:
  - backend_scripts/simcBis.py
---

# simc Chunked Checkpoint / Resume

The collector container restarts ~daily. On a 2-core host simc is pinned to ONE core (docker-compose `SIMC_CPUSET=1`/`SIMC_THREADS=1`/`SIMC_CPUS=1`, to protect co-located MySQL), so the heaviest specs (Balance/Guardian Druid) need more than one container lifetime to finish a run.

**Why not just raise the timeout:** a per-spec timeout ABOVE the restart interval is worse than a short one. A run killed mid-flight by the restart never completes, so without checkpoints that spec restarts from zero every boot and head-of-line-blocks every other spec. `SIMC_RUN_TIMEOUT` (default 8h) bounds ONE chunk and must stay below the restart interval.

**Phases (`_next_stage_work`).** A run is a sequence of chunks, each checkpointed to `simc_bis_progress` (per-profileset means, keyed `<stage>:<name>`) + `simc_bis_progress_meta` (header and prep snapshot). A killed chunk loses only itself.

- `t`: sims the talent candidates on the seed gear set. The winner becomes the base actor for the gear phases.
- `s1`: screens every gear combo at low precision (`SIMC_SCREEN_TARGET_ERROR` / `SIMC_SCREEN_ITERATIONS`, bigger `SIMC_SCREEN_CHUNK_SIZE`).
- `s2`: re-sims only the finalists at full precision (`_select_finalists`: top `SIMC_FINALISTS`, widened to everything within `SIMC_FINALIST_KEEP_PCT` of the best, capped at `SIMC_FINALISTS_MAX`).
- `r`: refines the gear winner (`_build_refine`), one category at a time (enchants, gems, embellishment comp, missive, consumables), `SIMC_REFINE_OPTIONS` options each.
- `_finalize_run` is idempotent: all-banked + stored baseline finalizes with zero sims.

**Revalidation (`_revalidate_names`).** When a spec's `profile_signature` matches its last completed run, the inputs are newer than the latest content go-live, and the talent winner is unchanged, the run skips `s1` and re-sims only the stored `revalidate_set` (`SIMC_REVALIDATE_TOP` combos plus per-slot references). A changed talent winner falls back to the full gear search. The talent and refine phases always run in full.

**Determinism is what makes resume work.**

- `_build_run`: `tier_slots` MUST be sorted there, because `detect_tier` returns a set and Python's per-process string-hash randomisation would otherwise reorder the profile and change the signature every restart.
- `profile_signature` = sha256 of the run's profile text (talent, stage-1 and refine inputs), EXCLUDING the simc build, so 6-hourly image pulls do not discard a run. A revalidation run gets its own checkpoint signature derived from it.
- **Prep snapshot** (`_snapshot_prep` / `_load_prep_snapshot`): header, candidates, baseline, tier and active slots stored in `simc_bis_progress_meta`. Resume rebuilds the run from the snapshot, NOT from re-prepared data, because candidate bags come from nightly-rebuilt popularity aggregations whose drift would otherwise mismatch the signature and discard all banked chunks. A signature mismatch therefore only means the profile-generation code changed (a legitimate reset).

**Queue order (`_select_target_spec`).** An unfailed in-progress run queues by its `started_at` (front, so a run interrupted by the restart resumes immediately). A failed run (a genuinely failing chunk sets `failed`) queues by `last_attempt_at` (back, so it cannot monopolise the loop). A spec with no run in progress queues by its completed `simc_bis_meta.updated_at`; never-run specs go first. A SIGTERM-killed chunk checks `cancel_event` and leaves the checkpoint untouched (NOT failed).

Pages read only the rank-1 item per slot from `simc_bis_items` (the SIM badge) plus the ranked talent, tier-comp and refinement choices in `simc_bis_choices`. See also [[pooled-connection-gotchas]] and [[simc-baseline-vs-page-gear]].
