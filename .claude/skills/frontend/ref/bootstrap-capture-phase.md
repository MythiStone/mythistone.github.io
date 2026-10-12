---
name: bootstrap-capture-phase
description: Bootstrap 5 data-api handlers run at document capture phase, so stopPropagation on a link inside an accordion button is useless; use a window-capture shield. Use when a link nested inside a [data-bs-toggle] control gets swallowed / preventDefault'd instead of navigating.
kind: external
files:
  - assets/js/spec-page.js
---

# Bootstrap 5 data-api runs in the capture phase

Bootstrap 5 registers its data-api handlers on `document` in the capture phase. A link or control
nested inside a `[data-bs-toggle]` element is toggled and `preventDefault()`ed before its own
handler runs, so `stopPropagation()` on the nested element does nothing.

Only a capture listener on `window` runs earlier. The "Item-name link capture" block in
`assets/js/spec-page.js` is the reference: copy that pattern for any new nested link.

Related: [[deep-links]], [[klaro-consent-embeds]].
