---
name: chart-theming
description: Use window.MythiChart (assets/js/chart-theme.js) for Chart.js chrome colors, icon preloading, patch annotations, and live re-theming; do not re-copy chart boilerplate. Use when adding or editing any Chart.js chart on a page.
kind: workflow
files:
  - assets/js/chart-theme.js
  - assets/js/dashboard.js
  - assets/js/dungeon-page.js
  - assets/js/spec-page.js
---

# Adding a Chart.js chart

- Build chart chrome from `window.MythiChart` (`assets/js/chart-theme.js`): ticks, grid, legend,
  tooltip and patch lines read its live `colors` object, never a literal hex. Charts built that way
  re-theme on their own.
- Series colors are the opposite: they carry class or rarity meaning, so they come from the class
  and quality tokens ([[frontend-design-tokens]]) and never from the chrome palette.
- `chart-theme.js` is loaded on every page, Chart.js is not. A page with a chart includes
  `plugins/chartjs.min.js` itself, plus the zoom and annotation plugins it uses.
- Gate zoom and pan to `min-width: 992px`, or they fight touch scrolling on phones.
