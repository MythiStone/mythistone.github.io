---
name: viewport-audit-consent-blind-spot
description: viewport_audit.py declines every Klaro service, so layout bugs caused by consent-gated third-party scripts (Wowhead power.js tooltips, video and route embeds) never show up in its report and must be checked by hand with consent on. Use when running the viewport audit, or debugging overflow or layout that only appears with Wowhead tooltips or embeds loaded.
kind: workflow
files:
  - backend_scripts/localDev/viewport_audit.py
  - backend_scripts/localDev/README.md
---

# The viewport audit cannot see consent-gated scripts

`viewport_audit.py` writes a `klaro` cookie that declines every service in `KLARO_SERVICES`, to
keep the consent banner out of the screenshots. So power.js and the embeds never load, and a clean
report says nothing about them. Wowhead tooltips are also only built on hover, which the audit
never does.

To check a layout bug that involves them, use the browser pane on the local render:

- Set the `klaro` cookie on localhost with the service set to `true`, then reload.
- Use a desktop viewport. power.js loads under a touch user agent but builds no tooltips, so phone
  emulation shows nothing.
- Hover a real link. Then move the open `.wowhead-tooltip` flush against the right edge and compare
  `document.documentElement.scrollWidth` with `clientWidth`. That is the worst case power.js can
  produce.
- Set the cookie back to `false` afterwards.

Related: [[klaro-consent-embeds]].
