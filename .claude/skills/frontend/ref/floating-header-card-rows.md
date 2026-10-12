---
name: floating-header-card-rows
description: Rows of cards with the Material Dashboard floating header (the gold ribbon, mt-n4) need their own mb-4 or top clearance, or the ribbon collides with the card above on wide screens. Use when adding or reordering card rows on the dungeon or spec page, or when a card header overlaps the card above it.
kind: external
files:
  - templates/dungeon_page.html
  - templates/spec_page.html
---

# Floating-header card rows need their own margin

A Material Dashboard card with the floating header (`.card-header` with `mt-n4`, the gold ribbon)
pulls the ribbon 1.5rem above the card. The column margin of the row above is fully consumed by it.

- A row of such cards is `row mb-4`. A bare `<div class="row">` lets the next row's ribbon collide
  with the card above on wide screens.
- After a row whose columns use `mb-xl-0`, the next ribbon row needs its own top clearance
  (`mt-4 mt-xl-5`).

Related: [[build-new-page]], [[in-card-scroll-regions]].
