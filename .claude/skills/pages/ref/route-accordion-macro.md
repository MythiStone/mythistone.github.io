---
name: route-accordion-macro
description: The keystone.guru route accordion item is one shared Jinja macro used by the spec, routes and dungeon pages, and assets/js/routes-finder.js must mirror its full markup. Use when editing templates/_route_macros.html, the route panels on spec_page.html / find_routes.html / dungeon_page.html, or routes-finder.js.
kind: coupling
files:
  - templates/_route_macros.html
  - templates/spec_page.html
  - templates/find_routes.html
  - templates/dungeon_page.html
  - assets/js/routes-finder.js
---

# Route and VOD rows: one macro, one JS mirror

`route_accordion_item` in `templates/_route_macros.html` is the only server-side source of the
route accordion markup, for `templates/spec_page.html`, `templates/find_routes.html` and
`templates/dungeon_page.html`.

- **`renderRouteItem` in `assets/js/routes-finder.js` rebuilds the same markup client-side.** A
  change to the macro is repeated there. `templates/_vod_macros.html` and
  `assets/js/vods-finder.js` are the same pair for VODs.
- **Client-added rows miss the one-shot inits.** `assets/js/finder.js` wires consent and refills
  the timestamps for each new row ([[klaro-consent-embeds]]).

Related: [[deep-links]].
