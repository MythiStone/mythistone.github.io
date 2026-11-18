---
name: boss-spell-id-sources
description: The encounter journal, MDT and Warcraft Logs can use different spell ids for one boss ability, so boss ability rows merge by normalized name. Use when adding a spell source to a boss modal or changing how its rows are matched.
kind: coupling
files:
  - backend_scripts/generateDungeonPages.py
  - backend_scripts/fetchDungeonData.py
  - backend_scripts/fetchDungeonSpells.py
---

# One boss ability, several spell ids

`boss_journal` lists the journal's id, `fetchDungeonData.py` stores the id MDT knows and the logs
report the id actually cast. Matching these by id alone shows one ability twice, once without its
logged stats. `attach_boss_log` therefore resolves a logged spell through `rows_by_name` and
`merge_spell_into`, including rows nested under a journal heading. Any new source of boss spells
has to pass through the same name match before it may add a row of its own.
