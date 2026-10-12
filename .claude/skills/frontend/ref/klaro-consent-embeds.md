---
name: klaro-consent-embeds
description: Klaro only manages embeds present at its init, so client-rendered keystone.guru iframes must gate consent themselves via MythiConsent.loadEmbed. Use when adding or debugging a dynamically rendered iframe embed, editing assets/js/consent.js, finder.js / routes-finder.js, or the embed flow on spec/dungeon/routes pages.
kind: coupling
files:
  - assets/js/consent.js
  - assets/js/finder.js
  - assets/js/routes-finder.js
---

# Client-rendered embeds and Klaro

Klaro only manages elements that exist when it initialises (header comment of
`assets/js/consent.js`). What that asks of templates and page scripts:

- **A third-party iframe is loaded through `MythiConsent.loadEmbed`** on `shown.bs.collapse`, as
  `templates/_route_macros.html` and `assets/js/finder.js` do. Nothing else sets its `src`.
- **An embed iframe in a template carries `data-src` only.** `src=""` makes the browser load the
  page's own URL into every iframe, and a real `src` on an embed Klaro manages stops Klaro's swap.
- **Do not reach for Klaro's own API for dynamic elements.** `applyConsents()` ignores them, and
  `renderContextualConsentNotices()` blanks `src` and hides the element.

Related: [[deep-links]].
