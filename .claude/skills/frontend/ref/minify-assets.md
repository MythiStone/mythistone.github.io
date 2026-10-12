---
name: minify-assets
description: How first-party CSS/JS assets are served and minified. Use when editing assets/css/ or assets/js/, wiring a stylesheet or script into a template, or tempted to point a template at a *.min.css / *.min.js variant.
kind: coupling
files:
  - backend_scripts/minifyAssets.py
  - templates/header_imports.html
  - templates/javascript_imports.html
---

# First-party assets are minified at build time by file name

`backend_scripts/minifyAssets.py` minifies CSS and JS in place inside `_site` during the `assemble`
job of `.github/workflows/buildPages.yml`, and skips every file named `*.min.css` or `*.min.js`.
The file name is the contract:

- Templates reference the readable source path. There is no first-party `*.min` file to point at.
- Never commit a minified copy of a first-party file, and never name a first-party file `*.min.*`:
  it would ship unminified.
- A vendor library is committed pre-minified under its `*.min.*` name.
