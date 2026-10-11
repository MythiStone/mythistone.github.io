---
name: build-new-page
description: How to scaffold a NEW static page so its markup, includes, and asset wiring match existing pages. Use when adding a page to templates/ and its generate*Page.py, or when a new page's navbar/sidenav/footer/theme is missing or out of order.
files:
  - backend_scripts/pageGeneration.py
  - templates/base_template.html
  - templates/header_imports.html
  - templates/javascript_imports.html
---

# Scaffolding a new page

Pages are **standalone full HTML documents** assembled with `{% include %}`, not `{% extends %}`
/ `{% block %}`. `templates/base_template.html` is only a minimal skeleton reference; real pages
copy its shape. Use `templates/comps.html` or `templates/spec_page.html` as the working model.

**`<head>` order:** `<title>`, then SEO / Open Graph / Twitter meta, then
`{% include "header_imports.html" %}`, then per-page stylesheets AFTER the include so they can
override the theme, e.g. `<link rel="stylesheet" href="/assets/css/<page>.css">`. Add
`stat-colors.css` and `datatables.min.css` when the page needs stat coloring or DataTables
(spec_page.html pulls `stat-colors.css` + `spec-page.css`; dungeon_page.html and item.html pull
`datatables.min.css`).

**`<body>` shell:** `<body class="g-sidenav-show g-sidenav-show-right">`, then
`{% include "sidenav.html" %}`, then `<main class="main-content position-relative border-radius-lg">`
starting with `{% include "top_chrome.html" %}`. `top_chrome.html` is the sticky page header: it
wraps `navbar.html`, `notifications.html` and `trends_bar.html`, and `top-chrome.js` condenses it on
scroll and publishes its height as `--top-chrome-h`. Never include those three directly. A page
that needs extra navbar controls sets `navbar_extra` (a `{% set %}` block) before the include. Page
content goes inside `<div class="container-fluid py-2 mx-3 w-auto">` with `{% include "footer.html" %}`
at the end of that div. After `</main>` add `{% include "right_aside.html" %}` and
`{% include "fixed_plugin.html" %}`.

**Scripts:** `{% include "javascript_imports.html" %}` near the end of `<body>`, THEN per-page
plugin `<script src>` tags and the `<page>.js` script (spec_page.html loads `plugins/chartjs.min.js`
+ `hammer.min.js` + `chartjs-plugin-zoom.min.js`; dungeon_page.html and item.html load
`plugins/dataTables.min.js`). Pass server data to the script as described in
[[page-data-and-scripts]]. Cache-bust volatile per-page assets with a query string, e.g.
`/assets/js/comps.js?v={{ generated_at | int }}`.

**Convention:** one `<page>.css` per page in `assets/css/`, one optional `<page>.js` in
`assets/js/`. A new page also needs a `generate<Page>Page.py` generator (build its own Jinja2
`Environment`, `os.makedirs` the output dir, `template.render(...)`) and wiring into
`.github/workflows/buildPages.yml`. See [[frontend-framework-choices]], [[frontend-design-tokens]],
[[local-test-render]].
