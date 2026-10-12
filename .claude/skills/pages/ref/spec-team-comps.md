---
name: spec-team-comps
description: The comps page Details modal shows family totals that compArchetypes emits and comps.js assembles, and the archetype ranking rules live in the compArchetypes docstrings. Use when editing backend_scripts/compArchetypes.py, the comps-page Details modal in assets/js/comps.js, or templates/_team_comp_macros.html.
kind: coupling
files:
  - backend_scripts/compArchetypes.py
  - backend_scripts/generateSpecPages.py
  - assets/js/comps.js
  - templates/_team_comp_macros.html
  - templates/comps.html
---

# Team comp archetypes across Python and JS

The ranking rules and their invariant are in the module docstring of
`backend_scripts/compArchetypes.py` and in `_core_rank`. What crosses files:

- **The Details modal shows family totals, not the core comp's runs.** `_family` emits the merged
  per-dungeon data, and `attachSlots` in `assets/js/comps.js` builds the comp object from the
  archetype. A change to what `_family` emits needs the matching change there.
- **`comp_slots` in `templates/_team_comp_macros.html` draws only the five main specs**, so
  `spec_team_comps` must hand it a comp that visibly contains the spec.

Related: [[frontend-json-dungeon-keys]], [[top-trends-bar]].
