---
name: klaro-consent-embeds
description: Third-party iframe embeds (keystone.guru, Twitch, YouTube) are never Klaro-managed; they name their service in data-embed-service and load through MythiConsent.loadEmbed when their panel opens. Use when adding or debugging an iframe embed, editing assets/js/consent.js, finder.js / routes-finder.js / vods-finder.js, the route or VOD macros, or the embed flow on spec/dungeon/streamer/finder pages.
kind: coupling
files:
  - assets/js/consent.js
  - assets/js/finder.js
  - assets/js/routes-finder.js
  - assets/js/vods-finder.js
  - templates/_route_macros.html
  - templates/_vod_macros.html
---

# Embeds load on open, not through Klaro

Klaro swaps `data-src` to `src` on every `data-name` element at init, hidden or not. On a
streamer page that started 332 Twitch and keystone.guru iframes at once and crashed the tab. So:

- **An embed iframe carries `data-embed-service="<klaro service>"` and `data-src`, never
  `data-name`.** `data-name` hands it back to Klaro. `src=""` makes the browser load the page's
  own URL into every iframe.
- **Its `src` is set only by `MythiConsent.loadEmbed`** (`assets/js/consent.js`) on
  `shown.bs.collapse`: via `wireAccordionEmbeds` (`assets/js/dungeon-page.js`,
  `assets/js/spec-page.js`, `assets/js/streamer.js`) or `wirePanelConsent` in
  `assets/js/finder.js`, which also wires the server-rendered skeleton items. Markup comes from
  `templates/_route_macros.html`, `templates/_vod_macros.html`, `assets/js/routes-finder.js` and
  `assets/js/vods-finder.js`. A page that renders an embed must wire it, or it
  never loads. `loadEmbed` checks consent and shows its own blocked notice.
- **Do not reach for Klaro's own API for these elements.** `applyConsents()` ignores them, and
  `renderContextualConsentNotices()` blanks `src` and hides the element.

Related: [[deep-links]].
