---
name: keystone-route-api-limits
description: The keystone.guru route API gives only npc_id (creature type) + enemyForces per pull, so per-run pack/position/route-consensus analytics are permanently impossible. Use before proposing pack-popularity, route-consensus, or spatial dungeon-page features.
kind: external
files:
  - backend_scripts/collectLeaderboardData.py
  - backend_scripts/generateDungeonPages.py
---

# The keystone.guru route API is type-level only

The public route API that `backend_scripts/collectLeaderboardData.py` reads gives, per pull, only
the creature type (`npcId`) and the pull's enemy forces. The per-instance id is deliberately
commented out on their side, and there are no coordinates. The spells of a pull are player casts
such as Bloodlust, not enemy abilities.

So a stored pull cannot be tied to a specific pack or position. Anything that needs "how often is
this pack pulled" (route consensus maps, pack popularity, spatial correlations) is permanently
impossible from run data. keystone.guru's open-source seeders do hold pack ids and positions, but
the run side has nothing to join on, and rebuilding their map duplicates their core product.

Feasible dungeon content is type-level and aggregate: skip rates, timing distributions, enemy
forces, comp and gear meta, loot. Do not propose pack or route-consensus features again.

Related: [[keystone-guru-mapping-data]].
