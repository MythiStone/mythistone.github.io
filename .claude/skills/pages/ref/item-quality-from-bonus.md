---
name: item-quality-from-bonus
description: Item quality/color (rarity) is resolved from the item's bonus ids, not the base item quality, on both the spec page and the items page, through one shared commonUtils helper. Use when an item's border/name color looks wrong, or when editing quality resolution in generateSpecPages.py / generateItemPages.py / commonUtils.py / templates/item.html / assets/js/items.js.
kind: coupling
files:
  - backend_scripts/generateSpecPages.py
  - backend_scripts/generateItemPages.py
  - backend_scripts/commonUtils.py
  - templates/item.html
  - assets/js/items.js
---

# Item rarity comes from the bonus-id variant

The color an item renders with is the quality of its bonus-id variant, not the base quality.

- **Resolve it only through `commonUtils.resolve_bonus_quality`**, in every generator.
- **Templates and JS pick `quality_override` when set, else `quality`.** `templates/item.html`,
  `templates/spec_page.html` and `effQuality` in `assets/js/items.js` all make that same choice. A
  new surface makes it too, for the color and for any quality filter.
- **`items_index.json` carries `quality_override` only when it differs from the base**, so a reader
  must fall back to `quality`.
- The item page header link and tooltip point at the base item on purpose. Only the color follows
  the variant.

Related: [[frontend-design-tokens]].
