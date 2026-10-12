---
name: enchant-link-icon-rune-fallback
description: Every enchant link/icon render surface must fall back to spellId/spellIcon because DK weapon runes have no scroll itemId. Use when rendering or editing any enchant Wowhead link or icon in templates/spec_page.html (gear-item macro, Enchantment Details accordion, Enchant Combos) or the enchant table in templates/item.html.
kind: coupling
files:
  - templates/spec_page.html
  - templates/item.html
---

# Every enchant surface handles the rune shape

`_enchant_link_fields` in `backend_scripts/generateSpecPages.py` bakes a scroll `itemId` or, for
Death Knight weapon runes, only a `spellId`. Every place that renders an enchant must handle both:

- **Link:** `item=<itemId>` when there is one, else `spell=<spellId>`.
- **Icon:** `itemIcon` when present, else `spellIcon`.

The surfaces are the gear-item macro, the Enchantment Details accordion and the Enchant Combos in
`templates/spec_page.html`, the enchant table in `templates/item.html`, and
`assets/js/loadout-view.js`. A new surface follows the same two rules.

To see a rune in a test render, a Death Knight spec's top weapon enchant must be a rune id. The
seeder picks enchants at random, so force one in the throwaway DB ([[local-test-render]]).

Related: [[enchant-lookup-filter]].
