---
name: sidenav-footer-flow
description: The left sidenav uses a flex-column flow layout so its scrollable nav list is contained above the support-buttons footer; do not restore absolute positioning or a fixed 72vh list height. Use when editing the sidenav footer/scroll region in templates/sidenav.html or the sidenav rules in assets/css/responsive.css / material-dashboard.css.
kind: coupling
files:
  - templates/sidenav.html
  - assets/css/responsive.css
  - assets/css/material-dashboard.css
---

# Sidenav footer stays in flow

`assets/css/responsive.css` overrides the sidenav rules of `assets/css/material-dashboard.css` on
purpose, to lay `#sidenav-main` out as one flex column whose list ends at the footer. The comments
on those rules say what each override undoes.

- Do not answer a reported overlap with absolute positioning, a `padding-bottom` or a fixed `vh`
  height on the list. Those are what the override removes.
- Keep `flex-wrap: nowrap`: `templates/sidenav.html` puts Bootstrap's `.navbar` on the aside, which
  would wrap the footer back over the list.

Verify by DOM measurement, not by eye, because the Browser pane may not composite frames: the list
bottom is at or above the footer top, no item straddles it, and the footer is on screen at a short
(about 800px) and a tall viewport and in the offcanvas below 1200px.
