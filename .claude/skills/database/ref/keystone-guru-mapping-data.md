---
name: keystone-guru-mapping-data
description: route_data.mapping_version is the keystone.guru per-dungeon mapping version, not its global mapping_version_id. Use when reading or matching route_data.mapping_version, or when matching routes against keystone.guru seeder data.
kind: external
files:
  - backend_scripts/collectLeaderboardData.py
  - backend_scripts/database.sql
---

# keystone.guru mapping version

`route_data.mapping_version` stores the `mappingVersion` field of the keystone.guru route API. That
is the per-dungeon version number (5, 6, 7 ...), not the global `mapping_version_id` (600 to 800
range). When matching against keystone.guru seeder data, match the seeder `version` field, not the
folder number.

Related: [[keystone-route-api-limits]], [[lust-pull-signature]].
