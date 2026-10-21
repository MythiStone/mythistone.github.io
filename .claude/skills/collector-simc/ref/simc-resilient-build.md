---
name: simc-resilient-build
description: The one simc build (the GHCR image) walks back over commits instead of trusting raw HEAD, its gate must SIMULATE a real fight (not just init), and buildPages re-gates that image against our gearsets. Use when editing simcWalkback.sh, validateSimc.sh, the fetch-simc job in buildPages.yml, or buildSimcImage.yml.
kind: external
files:
  - backend_scripts/simcWalkback.sh
  - backend_scripts/validateSimc.sh
  - backend_scripts/buildResilientSimcImage.sh
  - .github/workflows/buildSimcImage.yml
  - .github/workflows/buildPages.yml
  - Dockerfile.simc
---

# simc builds ship a validated commit

simc is built once, as the image `.github/workflows/buildSimcImage.yml` publishes. Its walk-back
publishes the newest sampled commit that passes `backend_scripts/validateSimc.sh` on simc's own
`profiles/CI.simc`. The collector and the tierlist sims both run that image. The `fetch-simc` job in
`.github/workflows/buildPages.yml` extracts the binary and gates it again on our generated
gearsets. If a spec we rank cannot sim, the build fails and has no fallback. The fix is a new
image, published by dispatching buildSimcImage. The reasons for the gate are in the headers of
`backend_scripts/validateSimc.sh` and `backend_scripts/simcWalkback.sh`. What is not written there:

- **Pinning is not an option.** simc's `midnight` branch is the live-WoW branch, and simc stopped
  publishing usable release tags years ago.
- **A hand-rolled smoke profile needs gear.** A bare actor fails init. The gates use simc's own
  `profiles/CI.simc`.
- **A broken spec can deadlock instead of exiting.** Every simc invocation is wrapped in `timeout`,
  and exit 124 or 137 counts as a failed candidate, not as an infrastructure error. A new
  invocation gets the same wrapper.
- Shell trap: `if ! cmd; then rc=$?` captures 0. Use `cmd || rc=$?`.

Related: [[simc-chunked-checkpoint]].
