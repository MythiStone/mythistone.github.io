---
name: key-scaling-number-format
description: The dungeon page's key scaling formats numbers in JS the same way the humanize filter does in Python, so the two must change together. Use when changing number humanizing or the Minimum key rescaling.
kind: coupling
files:
  - assets/js/dungeon-page.js
  - backend_scripts/commonUtils.py
---

# Two number formatters, one look

The page renders damage and health through `humanize_number` in `commonUtils.py`. When Minimum key
changes, `humanizeNumber` in `dungeon-page.js` rewrites those same numbers in the browser. If only
one side changes, a number's format jumps when a reader touches the dropdown and returning to Any
key no longer restores the rendered text.
