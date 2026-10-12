---
name: notification-dismiss-persistence
description: "Dismissible site notifications are injected client-side from assets/json/notifications.json and persist per-browser in localStorage keyed by a stable key, and first-party functional storage is NOT gated behind Klaro consent. Use when touching assets/js/notifications.js, templates/notifications.html, pageGeneration.load_notifications, the .page-notification styling in responsive.css, or deciding whether client-side preference storage needs a consent check."
files:
  - backend_scripts/pageGeneration.py
  - assets/css/responsive.css
  - assets/js/notifications.js
  - templates/notifications.html
---

# Dismissible notification persistence

`data/static/notifications.json` holds the site notifications. `pageGeneration.load_notifications`
splits them at build time:

- **Non-dismissible** entries are returned to the generators and rendered statically by
  `templates/notifications.html` (included via `top_chrome.html` on every page), filtered by
  `page` against `active_page` / `current_dungeon`.
- **Dismissible** entries (`"dismissible": true`) are written to `assets/json/notifications.json`,
  each with a stable `key = id or (message + "|" + link)`, and are never in the static HTML. So a
  dismissed banner cannot flash on load, and crawlers do not index them.

`assets/js/notifications.js` (loaded `defer` at the tail of `notifications.html`) fetches that JSON,
applies the same page filter as the Jinja condition (keep the two in sync), skips keys already in
`localStorage["mythistone.dismissedNotifications"]` (a JSON array), and injects the rest into
`#page-notifications` as `alert-dismissible` alerts carrying `data-notification-key`. It records a
key on Bootstrap's `close.bs.alert` (which bubbles to `document`; the `data-bs-dismiss` handler is
delegated, so injected alerts need no wiring).

- The key is what visitors' stored dismissals match. Editing a notification's `message`/`link`
  (with no `id`) changes the key, so a previously-dismissed notification reappears; add an `"id"`
  to decouple the key from the copy. Never change the key rule itself.
- `assets/json/notifications.json` is generated and gitignored like the other runtime JSON.

## Style the alert by CLASS, not id
`assets/css/responsive.css` styles notifications via `.page-notification` (background-image reset,
border, `.btn-close` colour, and the `max-width:575.98px` wrap block). Static alerts get a per-loop
id (`page-notification-1`, ...) and injected ones none, so an id selector matches nothing reliably.

## First-party functional storage is NOT gated behind Klaro consent
Remembering a dismissal is strictly-necessary first-party functional storage, exactly like the
light/dark theme preference (`localStorage['theme']`, written in `material-dashboard.js`, read
inline in `header_imports.html`). It writes to `localStorage` unconditionally, guarded only by
try/catch (private mode / disabled storage degrades gracefully). The Klaro banner governs
**third-party embeds** ([[klaro-consent-embeds]]); it does not gate the site's own preference
storage. When adding client-side preference storage, follow this pattern; do not add a Klaro service
or a consent check for it.
