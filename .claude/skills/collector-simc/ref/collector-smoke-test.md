---
name: collector-smoke-test
description: The collector image is pushed only after a runtime smoke test passes, and that test must change together with the collector's runtime contract. Use when changing the collector (collectLeaderboardData.py, entrypoint.sh, Dockerfile, simcBis.py, shipped data/static) or its build, and ALWAYS update the smoke test in lockstep.
kind: coupling
files:
  - backend_scripts/collectLeaderboardData.py
  - entrypoint.sh
  - Dockerfile
  - backend_scripts/simcBis.py
  - .github/workflows/buildCollectorImage.yml
---

# Collector smoke test: keep it in step with the collector

`.github/workflows/buildCollectorImage.yml` pushes the image only after its smoke job passes, and
the server pulls `:latest` on its own, so that push is the deploy gate. What the test checks is in
the header comment of `backend_scripts/localDev/collector_smoke.py`. The gate goes stale without
an error unless these move together:

| Collector change | Also change |
|---|---|
| New required env in `entrypoint.sh` | the smoke env in the workflow, and `FORWARD_ENV` in `collector_smoke.py` if the container needs it |
| Startup log line in `collectLeaderboardData.py` | `STARTUP_MARKER` in `collector_smoke.py` |
| New dependency or data file | the `COPY` blocks of `Dockerfile` and the `on.push.paths` of the workflow |
| Profile generation in `simcBis.py` | nothing, but the real spec-62 slice from `backend_scripts/localDev/simc_live_seed.py` is what proves it. Keep that slice working |

Run locally: seed with `--simc-live-spec 62` and `LIVE_DATABASE_*` ([[local-test-render]]), build
the image, run `collector_smoke.py`. `--network host` is limited on Windows Docker Desktop, so the
Linux CI run is the authoritative one.

Related: [[simc-resilient-build]], [[simc-chunked-checkpoint]].
