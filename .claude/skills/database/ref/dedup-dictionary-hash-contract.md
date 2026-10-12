---
name: dedup-dictionary-hash-contract
description: The talent and bonus-id dictionaries (talent_sets / bonus_sets) tie the Python collector, any SQL that writes them and every talent aggregate together through one content hash and one join rule. Use when touching commonUtils.talent_set_hash / bonus_set_hash, the members.talent_set_id / equipment.bonus_set_id write path, a talent or bonus aggregate, the purge event, or any one-time SQL that backfills the dictionaries.
kind: coupling
files:
  - backend_scripts/commonUtils.py
  - backend_scripts/collectLeaderboardData.py
  - backend_scripts/database.sql
  - backend_scripts/databaseConnector.py
---

# Dedup dictionaries: what must stay in step

- **One hash, two languages.** `commonUtils.talent_set_hash` and `commonUtils.bonus_set_hash`
  define the canonical string in their docstrings. Any SQL that writes a dictionary (a backfill, a
  migration) must produce byte-identical ids. If it does not, a collector insert lands on a
  different id than the SQL wrote and the same content splits into two entries.
- **A talent aggregate INNER JOINs `talent_sets`.** `ev_purge_old_run_details_incremental` keeps a
  purged member's row and only NULLs its pointer, so a LEFT JOIN counts purged members.
- **No foreign key points at a dictionary.** The reason and the replacement are in the comments of
  `sp_agg_talent_sets_gc` and `sp_agg_bonus_sets_gc`.

Related: [[gear-and-talent-data-retention]], [[season-rollover-wipe]].
