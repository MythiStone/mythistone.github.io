---
name: page-data-and-scripts
description: Page JS and CSS live in assets/js/<page>.js and assets/css/<page>.css, never inline in templates, and server data reaches the script either as a fetched JSON file or an inline application/json block depending on how the page consumes it. Use when adding or moving page logic, passing generator data to JavaScript, touching dashboard.js / comps.js data loading, or reaching for window.X = {{ ... }}.
kind: workflow
files:
  - assets/js/dashboard.js
  - assets/js/comps.js
  - backend_scripts/generateDashboardPage.py
  - backend_scripts/generateCompPage.py
---

# Page logic and data belong in files, not inline

Page behavior lives in `assets/js/<page>.js` and styling in `assets/css/<page>.css`. External JS
cannot hold Jinja, so generator data reaches it one of two ways. The choice depends on how the
page consumes the data:

- **A fetched JSON file** when the data only feeds content that renders asynchronously.
  `backend_scripts/generateDashboardPage.py` and `assets/js/dashboard.js` are the reference. Add
  the file to `.gitignore` next to the other generated JSON.
- **An inline `<script type="application/json">` block** when the script needs the data
  synchronously. That is always the case when it registers deep-link state: a `fetch` callback
  lands after the deep-link boot and permalinks break without an error ([[deep-links]]).
  `assets/js/comps.js` is the reference.

Never inject data as `window.X = {{ ... }}`.

Stays inline by design: the theme pre-paint script in `templates/header_imports.html`, the
`application/ld+json` blocks, the consent stubs, and truly dynamic `style=` values.

The per-keylevel bar chart is deliberately not shared between the spec and the dungeon page.

Related: [[build-new-page]], [[minify-assets]].
