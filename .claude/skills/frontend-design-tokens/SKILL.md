---
name: frontend-design-tokens
description: Never hardcode domain hex (class, item-rarity, stat, scrollbar colors) in page CSS/templates; use the CSS custom properties and utility classes. Use when styling anything colored by WoW class, item quality, or stat, when theming, or when adding icons.
---

# Frontend design tokens

Do not hardcode domain hex values. The palette lives in CSS custom properties defined in
`assets/css/material-dashboard.css`, `assets/css/classes.css`, and `assets/css/stat-colors.css`.

- **Brand:** Legendary Gold, `var(--bs-primary)` = `#f59e0b`, edited directly into
  `material-dashboard.css` (no separate override file): the stock pink is remapped at the source in
  the token blocks and in the vendor's own `.bg-primary`/`.bg-gradient-primary`/`.shadow-primary`/
  `.btn-primary`/`.badge.bg-primary` rules, plus a small "MythiStone gold accent" block after
  `.bg-gradient-primary`. Gold is bright, so content ON a gold fill uses near-black `#241700`.
  GOTCHA: the vendor sets primary-button and `.btn-outline-light` colours DIRECTLY (not via
  `--bs-btn-*`), and `bootstrap-select.min.css` loads AFTER `material-dashboard.css`, so ribbon
  overrides for the Perfect-Fit selectpicker need real `color` `!important` at raised specificity
  (`button.dropdown-toggle`, and its label is `.filter-option-inner-inner`), not just the button
  vars. Peripheral components (link-hover, focus rings, list-group/pagination active, progress bars,
  range sliders, form-check) still carry stock pink literals to convert when those widgets are
  polished.
- **WoW class colors:** dual tokens in `classes.css`: `--class-<Name>` is contrast-tuned for TEXT
  on the current theme's surfaces, `--class-<Name>-raw` is the true Blizzard hex for FILLS (bars,
  chips, swatches). Names are PascalCase (`--class-DeathKnight`, `--class-DemonHunter`). Utility
  classes `.class-<Name>-text` and `.class-<Name>-bg` are provided.
- **Item rarity:** `--quality-0` .. `--quality-8` in `stat-colors.css`, with utility classes
  `.item-quality-N` (text) and `.border-quality-N` (border). Any page rendering item names/icons
  must link `stat-colors.css` in `<head>` (after `header_imports.html`) or the classes are inert and
  names fall back to plain white. The displayed rarity is not the base `quality`, see
  [[item-quality-from-bonus]].
- **Stat tiers:** `--stat-*` (and `--stat-*-raw`) in `stat-colors.css` (`--stat-crit`,
  `--stat-haste`, `--stat-mastery`, `--stat-vers`, ...), with `.stat-<name>` utility classes
  (both short and long forms exist, e.g. `.stat-crit`, `.stat-int` / `.stat-intellect`).
- **Scrollbars:** `--mythi-scrollbar-track`, `--mythi-scrollbar-thumb`, `--mythi-scrollbar-thumb-hover`
  (defined in `material-dashboard.css`, consumed by `assets/css/custom-scrollbars.css`).

**Theming.** Dark is the **unconditional default** via `data-bs-theme` on `<html>`, set by an
inline pre-paint script in `templates/header_imports.html` that reads `localStorage.theme`; the OS
`prefers-color-scheme` is deliberately ignored. Every token is defined twice: under
`:root,[data-bs-theme=light]` and again under `[data-bs-theme=dark]`. On toggle,
`material-dashboard.js` dispatches a `window` `mythistone:themechange` event (see [[chart-theming]]).

**Icons.** UI glyphs use Material Symbols Rounded (`<i class="material-symbols-rounded">name</i>`).
Game icons are served from `/data/icons/<id>.jpg` (specs, buffs) or `.png` (items) as
`<img class="avatar avatar-sm">`. See [[build-new-page]], [[frontend-framework-choices]],
[[in-card-scroll-regions]].
