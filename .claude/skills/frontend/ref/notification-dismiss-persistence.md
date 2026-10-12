---
name: notification-dismiss-persistence
description: "Dismissible site notifications are injected client-side from assets/json/notifications.json and persist per-browser in localStorage keyed by a stable key, and first-party functional storage is NOT gated behind Klaro consent. Use when touching assets/js/notifications.js, templates/notifications.html, pageGeneration.load_notifications, the .page-notification styling in responsive.css, or deciding whether client-side preference storage needs a consent check."
kind: coupling
files:
  - backend_scripts/pageGeneration.py
  - assets/css/responsive.css
  - assets/js/notifications.js
  - templates/notifications.html
---

# Site notifications: what must stay in step

Dismissible notifications are injected by `assets/js/notifications.js`, the others are rendered by
`templates/notifications.html`. `pageGeneration.load_notifications` splits them.

- **The page filter exists twice**, as the Jinja condition in `templates/notifications.html` and in
  `assets/js/notifications.js`. Change both.
- **Style by the `.page-notification` class in `assets/css/responsive.css`, never by id.** Static
  alerts get a per-loop id and injected ones get none.
- **The dismissal key is what visitors' browsers have stored.** Editing the `message` or `link` of
  an entry without an `"id"` in `data/static/notifications.json` changes its key, and everyone who
  dismissed it sees it again. Give an entry an `"id"` before rewording it, and never change the key
  rule.
- **First-party preference storage is not gated behind Klaro.** A new client-side preference writes
  to `localStorage` directly, like the theme and the dismissals. Klaro governs third-party embeds
  only ([[klaro-consent-embeds]]).
