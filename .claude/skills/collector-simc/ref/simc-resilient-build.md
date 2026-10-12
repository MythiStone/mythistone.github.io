---
name: simc-resilient-build
description: simc builds validate-and-walk-back over commits instead of trusting raw HEAD, and the gate must SIMULATE a real fight (not just init). Use when editing simcWalkback.sh, validateSimc.sh, the build-simc job in buildPages.yml, or buildSimcImage.yml.
kind: external
files:
  - backend_scripts/simcWalkback.sh
  - backend_scripts/validateSimc.sh
  - backend_scripts/buildResilientSimc*.sh
  - .github/workflows/buildSimcImage.yml
  - .github/workflows/buildPages.yml
  - Dockerfile.simc
---

# simc builds ship a validated commit

Both simc builds, the binary for the tierlist in `.github/workflows/buildPages.yml` and the
collector image in `.github/workflows/buildSimcImage.yml`, walk back over commits until one passes
`backend_scripts/validateSimc.sh`. The reasons are in the headers of that script and of
`backend_scripts/simcWalkback.sh`. What is not written there:

- **Pinning is not an option.** simc's `midnight` branch is the live-WoW branch, and simc stopped
  publishing usable release tags years ago.
- **A hand-rolled smoke profile needs gear.** A bare actor fails init. The gates use simc's own
  `profiles/CI.simc`.
- **A broken spec can deadlock instead of exiting.** Every simc invocation is wrapped in `timeout`,
  and exit 124 or 137 counts as a failed candidate, not as an infrastructure error. A new
  invocation gets the same wrapper.
- Shell trap: `if ! cmd; then rc=$?` captures 0. Use `cmd || rc=$?`.

Related: [[simc-chunked-checkpoint]].
