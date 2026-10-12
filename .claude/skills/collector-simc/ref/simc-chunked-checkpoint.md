---
name: simc-chunked-checkpoint
description: A simc BiS run outlives the collector container, so its chunk timeout is tied to the container restart interval and to the single core docker-compose gives simc. Use when changing SIMC_RUN_TIMEOUT or the simc resource limits in docker-compose.yml, or the checkpoint and resume code in simcBis.py.
kind: coupling
files:
  - backend_scripts/simcBis.py
  - docker-compose.yml
---

# simc runs span container restarts

The collector container restarts about daily, and `docker-compose.yml` pins simc to one core to
protect the co-located MySQL. The heaviest specs therefore need more than one container lifetime,
which is why `simcBis.run_simc_bis` checkpoints every chunk (the phases and the queue order are in
the docstrings of `_build_run` and `_select_target_spec`).

- **`SIMC_RUN_TIMEOUT` bounds one chunk and stays below the restart interval.** Raising it above
  the interval is worse than a short timeout: a chunk killed by the restart never completes, and
  that spec blocks every other spec.
- A changed profile signature discards the banked chunks. That is intended when the profile
  generation code changed, and a bug when anything else caused it.

Related: [[pooled-connection-gotchas]], [[simc-baseline-vs-page-gear]].
