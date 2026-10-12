---
name: infinite-scroll-pages
description: How paginated listing pages (blog, items, routes) load more entries via the shared window.MythiInfinite sentinel helper, and the server-render-page-1 + JSON-manifest + shared-card pattern. Use when adding or editing infinite scroll on a listing, touching assets/js/infinite-scroll.js, blog-infinite.js, items.js, finder.js, generateBlogPage.py, or verifying scroll loading in the Browser pane.
kind: workflow
files:
  - assets/js/consumables.js
  - assets/js/infinite-scroll.js
  - assets/js/blog-infinite.js
  - assets/js/items.js
  - assets/js/finder.js
  - backend_scripts/generateBlogPage.py
---

# Adding infinite scroll to a listing

The sentinel helper is `window.MythiInfinite` in `assets/js/infinite-scroll.js` (its header comment
is the API). The blog is the reference for a listing whose data is generated offline. The parts
that span files:

- **Page 1 is server-rendered, the rest comes from one JSON manifest.** `generateBlogPage.py`
  renders only the first page and writes every later post to the manifest. `.gitignore` lists
  generated manifests per file, so a new manifest is added there.
- **One card definition serves both render paths.** The Jinja macro that renders page 1 is rendered
  once more into a hidden `<template>`, and the page script clones that. Never build card HTML as a
  string in JS: the two paths drift.
- **Appended nodes miss the one-shot passes in `templates/javascript_imports.html`.** Re-run the
  relative-time fill and the tooltip init on the new nodes.

## Verifying in the Browser pane

The pane keeps its tabs hidden, so `IntersectionObserver` and `requestAnimationFrame` never fire
and a scroll gesture loads nothing. Drive the real load path instead: stub
`window.IntersectionObserver` with one that calls its callback on `observe()`, then re-run the page
script. For the finders, call the `doQuery` that `MythiFinder.create` returns with `append: true`.

Related: [[local-test-render]], [[artifact-only-deploy]].
