---
name: build-new-page
description: How to scaffold a NEW static page so its markup, includes, and asset wiring match existing pages. Use when adding a page to templates/ and its generate*Page.py, or when a new page's navbar/sidenav/footer/theme is missing or out of order.
kind: workflow
files:
  - backend_scripts/pageGeneration.py
  - templates/base_template.html
  - templates/header_imports.html
  - templates/javascript_imports.html
---

# Scaffolding a new page

Copy the shape of `templates/comps.html`. The include list and the "never include the navbar,
notifications or trends bar directly" rule are in `AGENTS.md` ("Templating"). The order matters:

1. **`<head>`:** title and SEO meta, then `header_imports.html`, then the page stylesheets, so they
   can override the theme. Add `stat-colors.css` and `datatables.min.css` when the page needs them.
2. **`<body>`:** `sidenav.html`, then `<main>` starting with `top_chrome.html`. A page that needs
   extra navbar controls sets `navbar_extra` before that include. Content goes in the
   `container-fluid` div, with `footer.html` as its last child. `right_aside.html` and
   `fixed_plugin.html` follow `</main>`.
3. **Scripts:** `javascript_imports.html`, then per-page plugin scripts, then `<page>.js` with a
   cache-busting query string. Data reaches the script as in [[page-data-and-scripts]].
4. **Files:** one `assets/css/<page>.css`, one optional `assets/js/<page>.js`, and a
   `backend_scripts/generate<Page>Page.py` that is wired into `.github/workflows/buildPages.yml`.

Related: [[frontend-framework-choices]], [[frontend-design-tokens]], [[local-test-render]].
