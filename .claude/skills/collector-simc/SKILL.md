---
name: collector-simc
description: "MythiStone data collection and SimulationCraft: the leaderboard collector and its smoke-tested Docker image, simc builds and chunked BiS runs, talent loadout encoding, keystone.guru route API limits. Use when editing collect*/fetch*/simc* scripts, Dockerfile, entrypoint.sh or the collector/simc image CI."
---

# Collector SimC domain

Owner agent `collector-infra`. Owns collectors (`collect*`, `fetch*`, `download*`, `process*`), `simcBis.py` and the simc shell scripts, `Dockerfile`, `Dockerfile.simc`, `entrypoint.sh`.

**Verify:** The `collector-smoke-test` gotcha: build the image and run it against a seeded DB. Update the smoke test in lockstep with collector changes.

**Look things up, do not read whole files.** The `mythi-kb` MCP tools (or `python .claude/kb/kb.py <tool> <arg>`)
return the slice you need: `kb_table`, `kb_symbol`, `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`.
Open a source file only at the range a tool pointed to.

## Gotchas

Before changing a file listed below, read its gotcha: `ref/<id>.md` in this skill (or `kb_gotcha <id>`).
`kb_file <path>` lists every gotcha for a path across all domains.

| id | rule | files |
|---|---|---|
| `collector-smoke-test` | The collector image push is gated on a runtime smoke test that runs the built image against a seeded throwaway DB (with a real spec-62 slice) and must actually collect + run simc | `backend_scripts/collectLeaderboardData.py`, `entrypoint.sh`, `Dockerfile`, `backend_scripts/simcBis.py`, `.github/workflows/buildCollectorImage.yml` |
| `keystone-route-api-limits` | The keystone.guru route API gives only npc_id (creature type) + enemyForces per pull, so per-run pack/position/route-consensus analytics are permanently impossible | `backend_scripts/collectLeaderboardData.py`, `backend_scripts/generateDungeonPages.py` |
| `loadout-v2-encoder` | The shared Blizzard "serialization v2" talent-loadout encoder (commonUtils.encode_loadout), now used ONLY by the local seeder, and the rules that make its output both decode in the browser AND init in SimulationCraft | `backend_scripts/commonUtils.py`, `backend_scripts/localDev/*` |
| `simc-baseline-vs-page-gear` | Why the simcBis baseline gear can legitimately differ from the spec page's displayed equipped items, and why not to "fix" it | `backend_scripts/simcBis.py` |
| `simc-chunked-checkpoint` | simc BiS runs are chunked and checkpointed to simc_bis_progress so heavy specs resume across the ~daily collector restart | `backend_scripts/simcBis.py` |
| `simc-resilient-build` | simc builds validate-and-walk-back over commits instead of trusting raw HEAD, and the gate must SIMULATE a real fight (not just init) | `backend_scripts/simcWalkback.sh`, `backend_scripts/validateSimc.sh`, `backend_scripts/buildResilientSimc*.sh`, `.github/workflows/buildSimcImage.yml`, `.github/workflows/buildPages.yml`, `Dockerfile.simc` |
