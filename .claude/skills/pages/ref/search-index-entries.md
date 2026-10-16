---
name: search-index-entries
description: Every page the search index walks declares its own entry with the search_meta macro, or the build raises, and every spec id needs a key in search_aliases.json. Use when adding a page or template, a new spec appears, or a site search result looks wrong.
kind: coupling
files:
  - backend_scripts/generateSearchIndex.py
  - templates/_search_macros.html
  - data/static/search_aliases.json
  - assets/js/site-search.js
---

# Pages declare their own search entry

`generateSearchIndex.py` does not scrape titles or body text. It reads only the `search:*` metas
that `search_meta` in `templates/_search_macros.html` writes into a page's `<head>`, and raises on
any walked page that lacks them. A new page therefore either calls `search_meta` or is added to
`SKIP_FILES` / `SKIP_PREFIXES`. Items and consumables are the exception: their entries come from
`items_index.json` and `consumables_index.json`, not from their pages.

The index runs in the `assemble` job of `buildPages.yml`, after the tier list render, so a missing
meta fails the deploy, not the page build.

The `type` value is shown as the badge and drives ranking in `MythiSearch` (`TYPE_FACTOR` in
`site-search.js`). Reuse an existing type unless the new one should rank differently.

`generateSpecPages.py` subscripts `search_aliases.json` by spec id without a guard, so a spec added
to `specs.json` needs a key there (an empty list is fine) before the spec pages render.

Related: [[build-new-page]].
