---
name: deep-links
description: Covers site-wide \#fragment deep links, copy-link buttons, and the instant-scroll workaround in assets/js/deep-link.js. Use when making a modal/accordion/tab addressable, registering page state via window.MythiLink, or debugging a programmatic scroll that does not land.
kind: workflow
files:
  - assets/js/deep-link.js
  - assets/js/share.js
---

# Making something deep-linkable

The header comment of `assets/js/deep-link.js` describes the hash grammar and what the module does
on its own. What a page has to get right:

- **Register page state before boot.** A script block placed above the `javascript_imports.html`
  include has no `window.MythiLink` yet and registers inside a `DOMContentLoaded` listener.
- **A panel whose id embeds a run id carries `data-share-id` without it.** Otherwise a link goes
  stale with the next build and opens the wrong route.
- **Reveal through the Bootstrap API**, never by adding the `show` class: `assets/js/spec-page.js`
  hydrates its panels on the collapse events.
- **Any programmatic scroll passes `behavior: "instant"`.** `<html>` sets smooth scrolling, and the
  pages reflow while hundreds of unsized icons load, so an animated scroll is abandoned and the page
  stays where it was.

Related: [[klaro-consent-embeds]], [[bootstrap-capture-phase]].
