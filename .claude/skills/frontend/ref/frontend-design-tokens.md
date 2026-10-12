---
name: frontend-design-tokens
description: Never hardcode domain hex (class, item-rarity, stat, scrollbar colors) in page CSS/templates; use the CSS custom properties and utility classes. Use when styling anything colored by WoW class, item quality, or stat, when theming, or when adding icons.
kind: workflow
files:
  - assets/css/*.css
  - assets/scss/*
---

# Colors and icons come from tokens

Never hardcode a class, rarity, stat, brand or scrollbar color in page CSS or a template. Use the
custom properties and utility classes that already exist:

| For | Defined in |
|---|---|
| Brand gold, scrollbars | `assets/css/material-dashboard.css` |
| WoW class colors, text and fill variants | `assets/css/classes.css` |
| Item rarity, stats | `assets/css/stat-colors.css` |

- **A page that renders item names or icons links `stat-colors.css` in its `<head>`**, after
  `header_imports.html`. Without it the quality classes are inert and names render plain white.
- **A new token is defined twice**, once for the light theme and once for the dark theme.
- **Overriding a bootstrap-select or primary button color needs a real `color` rule with raised
  specificity.** `bootstrap-select.min.css` loads after `material-dashboard.css` and sets colors
  directly, not through the `--bs-btn-*` variables.
- Peripheral widgets (link hover, focus rings, pagination, progress bars, range sliders,
  form-check) still carry the vendor's stock pink. Convert them when one is used.
- Game icons are served from `/data/icons/<id>.jpg` (specs, buffs) or `.png` (items).

The displayed rarity of an item is not its base quality: [[item-quality-from-bonus]].
