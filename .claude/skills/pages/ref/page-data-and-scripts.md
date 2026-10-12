---
name: page-data-and-scripts
description: Page JS and CSS live in assets/js/<page>.js and assets/css/<page>.css, never inline in templates, and server data reaches the script either as a fetched JSON file or an inline application/json block depending on how the page consumes it. Use when adding or moving page logic, passing generator data to JavaScript, touching dashboard.js / comps.js data loading, or reaching for window.X = {{ ... }}.
files:
  - assets/js/dashboard.js
  - assets/js/comps.js
  - backend_scripts/generateDashboardPage.py
  - backend_scripts/generateCompPage.py
---

# Page logic and data belong in files, not inline

Keep JS and CSS out of the templates: page behavior lives in `assets/js/<page>.js` (cache-bust the
include `?v={{ generated_at | int }}`), styling in `assets/css/<page>.css`. Because there is no build
step, external JS cannot hold Jinja, so server data reaches it through the DOM one of two ways. The
choice is **how the page consumes the data, not the page's cardinality**:

- **Fetched JSON file** when the data only feeds content rendered *asynchronously* and nothing needs
  it synchronously. The generator writes a compact `assets/json/<page>_data.json`
  (`os.makedirs("assets/json")`, `json.dump(data, f, separators=(",", ":"))`, add the filename to
  `.gitignore` by the other generated JSON) and the page JS `fetch`es it. `generateDashboardPage.py` is the
  reference: its charts build async (icons load via promises) and it registers no deep-link state, so
  a file keeps the large heatmap/scatter payload out of the HTML. `build_overall_spec_chart` +
  `write_dashboard_data` assemble the payload in Python (label/colour/icon precompute included), and
  `dashboard.js` fetches it and builds each chart wrapped so one failure never aborts the others.
- **Inline `<script type="application/json" id="<page>-data">{{ data | tojson }}</script>`** (read
  with `JSON.parse(el.textContent)`) when the page reads the data *synchronously*, because it derives
  values at parse time or, critically, calls `MythiLink.registerState`/`registerRevealer`, which must
  run before the deep-link boot (a `fetch` callback lands too late and silently breaks
  `#`-permalinks, see [[deep-links]]). This is also the right idiom for high-volume per-entity pages
  (item/spec/dungeon: one file per entity, and they register link state). `comps.js` uses it for its
  lookups even though comps is a singleton, precisely because it registers `'comp'` state and derives
  `buffProviders`/`META_COMP_SPECS` at load. Prefer it over `window.X = {{...}}` global injection.

**Shared cross-page helpers.** `assets/js/page-init.js` (sidenav smooth-scrollbar, `.timestamp`
relative-time init, modal focus-blur fix, `sidebarColor`) is included once from
`javascript_imports.html` after `material-dashboard.js`. `timeAgo`/`formatDuration` are intentionally
global there because other page scripts call them. `MythiConsent.wireAccordionEmbeds(selector)` (in
`consent.js`) is the shared "load the route embed when its accordion panel first opens" block for the
spec, dungeon and route finder pages (see [[klaro-consent-embeds]]). The per-keylevel `runsBarChart`
is deliberately NOT shared between spec and dungeon pages (they differ on canvas id, reset-button
mechanism and bar sizing); each keeps its own copy.

**Stays inline by design (do not extract):** the theme pre-paint script in `header_imports.html`, SEO
`application/ld+json` blocks, and the `text/plain data-src` Klaro/analytics consent stubs. Truly
dynamic `style=` (bar widths, `background-image` urls) stays inline; static ones become utility
classes.

**Chart axes.** Every chart axis is themed from the `MythiChart` palette (ticks `colors.tickText`,
grid `colors.grid`, titles `colors.axisText`, legend `colors.legendText`). The Chart.js default tick
colour is a dim `#666`, so a scatter that sets none looks greyed-out next to the rest of the page
(see [[chart-theming]]).

Related: [[build-new-page]], [[minify-assets]].
