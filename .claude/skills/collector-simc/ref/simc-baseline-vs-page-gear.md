---
name: simc-baseline-vs-page-gear
description: Why the simcBis baseline gear can legitimately differ from the spec page's displayed equipped items, and why not to "fix" it. Use when someone reports a mismatch between a spec page's per-slot item and the simc BiS reference set, or when editing set_is_valid / fetch_slot_rows in simcBis.py.
kind: coupling
files:
  - backend_scripts/simcBis.py
---

# simc baseline and spec page gear may differ

`simcBis.set_is_valid` makes the simc baseline the most popular legal set. The spec page
(`fetch_slot_info` in `backend_scripts/generateSpecPages.py`) shows the most popular item per slot
independently, with no equip limits, so it can show a set nobody can wear.

Leave both as they are. Forcing the baseline to match the page would create an illegal reference
set, for example with three embellishments. The page showing an unequippable loadout is a known and
accepted display quirk.
