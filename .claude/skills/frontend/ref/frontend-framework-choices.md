---
name: frontend-framework-choices
description: Which frontend library to reach for per concern (modals, tables, selects, charts, search, consent) and the no-build-step conventions. Use when adding client-side UI to a page, picking a widget library, or wondering why jQuery is present.
kind: workflow
files:
  - templates/header_imports.html
  - templates/javascript_imports.html
  - assets/js/plugins/*
---

# Which library for which job

The stack and its no-build-step rule are in `AGENTS.md` ("Frontend stack"). Per concern:

| Need | Use | Include |
|---|---|---|
| Modals, dropdowns, collapse, tabs, tooltips | Bootstrap 5 `data-bs-*` attributes | global |
| Selects, icon multi-selects | bootstrap-select (`.selectpicker`) | global |
| Sortable or searchable tables | DataTables, Bootstrap 5 build | per page: `plugins/dataTables.min.js` and `datatables.min.css` |
| Charts | Chart.js v4 with [[chart-theming]] | per page |
| Fuzzy search | Fuse.js | global through `site-search.js` |
| Third-party embeds | `MythiConsent` ([[klaro-consent-embeds]]) | global |

Do not hand-roll any of these, and do not write new jQuery-dependent code.
