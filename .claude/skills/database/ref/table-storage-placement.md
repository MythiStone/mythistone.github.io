---
name: table-storage-placement
description: Where the large MySQL tables physically live (general tablespaces vs. per-table DATA DIRECTORY on specific host drives) and the only working way to move a table to another drive. Use when a drive fills up, when adding or relocating a large raw/aggregated table, when a wiped table does not give disk space back, or when editing TABLESPACE / DATA DIRECTORY clauses in backend_scripts/database.sql.
kind: external
files:
  - backend_scripts/database.sql
---

# Physical storage placement and moving a table to another drive

Large raw/aggregated tables are pinned to specific host drives; `innodb_directories`
(`/var/lib/mysql`, `/sdb/mysql-vol`, `/mnt/HC_Volume_103256352/mysql-vol`) lists those drives so
external files are rediscovered on restart. Two mechanisms coexist:

- Legacy **general tablespaces** (`/*!50100 TABLESPACE `name` */`, created MANUALLY on the server,
  NOT in `database.sql`): `members`/`equipments` on the Hetzner volume, `ts_runs`/`ts_run_members`
  on `/sdb`, `ts_character_stats`/`ts_agregated_equipment` (tablespace name is misspelled)/
  `aggregated_bonus_lists` on the datadir.
- Per-table **`DATA DIRECTORY='...'`** file-per-table tables: `member_character` and
  `member_dungeon_score` on the Hetzner volume.

**Prefer `DATA DIRECTORY` (file-per-table)** for anything the season wipe TRUNCATEs or the pipeline
DROP/rebuilds. A general tablespace's shared `.ibd` NEVER returns freed space to the OS (TRUNCATE and
DROP free pages only internally, and there is no shrink op), so wiped general-tablespace tables bloat
permanently; a file-per-table `.ibd` is recreated by TRUNCATE and deleted by DROP, so disk is
reclaimed.

**Moving an existing table to another drive.** `DATA DIRECTORY` is honored only by `CREATE TABLE`,
never `ALTER TABLE`. `ALTER ... DATA DIRECTORY` warns `<DATA DIRECTORY> option ignored` and leaves
the file in the datadir, and `ALTER ... TABLESPACE=innodb_file_per_table` converts a
general-tablespace table to file-per-table but also lands it in the datadir. So recreate it on the
target drive with the collector paused:

1. `CREATE TABLE t_mig (<same cols + indexes, but NO foreign key>) ... DATA DIRECTORY='/drive/path/'`
2. `INSERT INTO t_mig SELECT * FROM t`, then check `COUNT(*)` matches.
3. With `foreign_key_checks=0`: `RENAME TABLE t TO t_old, t_mig TO t`.
4. Re-`ADD CONSTRAINT` the FK, then `DROP TABLE t_old`.

The temp table omits the FK because constraint names are schema-unique. Verify placement in
`information_schema.INNODB_TABLES` + `INNODB_DATAFILES` (`SPACE_TYPE='Single'`, `PATH` under the
drive).

The local seeder strips tablespace and `DATA DIRECTORY` clauses (`schema_loader.py`), so none of this
applies to the throwaway test DB. Related: [[season-rollover-wipe]], [[aggregation-pipeline]],
[[verify-database-sql]].
