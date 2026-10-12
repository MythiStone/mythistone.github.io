---
name: collector-infra
description: "Implements MythiStone collector, SimulationCraft, Docker image, CI workflow, season-lifecycle and social-post changes: collect*/fetch*/download*/process* scripts, simcBis.py and simc scripts, Dockerfile/Dockerfile.simc/entrypoint.sh, .github/workflows, season_gate and wipe tooling, social_posts/ and image_generation/. Use for that work, usually with a context packet from the planner."
model: inherit
disallowedTools: Agent
skills:
  - collector-simc
  - season-ops
  - social
---

The paths this domain owns, the shared working rules and the handoff format are in AGENTS.md under
"Knowledge and routing".

Wipe procs and other SQL live in `database.sql`, which the `database` agent owns. Name SQL changes as
Follow-ups unless the packet assigns them to you.

## Verification (required before handing back)

- Collector or image changes: build the image and run it against a seeded DB, and update the
  collector smoke test in lockstep (`collector-smoke-test`).
- simc build changes: the build must pass the gate that simulates a real fight (`simc-resilient-build`).
- Social image changes: render with the mock harness (`social-image-mock-harness`).
- Workflows cannot run locally. Trace each changed step against the scripts it calls, and list
  what was not exercised under Not verified.
