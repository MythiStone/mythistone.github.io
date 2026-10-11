---
name: floating-header-card-rows
description: Rows of cards with the Material Dashboard floating header (the gold ribbon, mt-n4) need their own mb-4 or top clearance, or the ribbon collides with the card above on wide screens. Use when adding or reordering card rows on the dungeon or spec page, or when a card header overlaps the card above it.
---

# Floating-header card rows need their own `mb-4`

Cards using the Material Dashboard floating header (`.card-header ... mt-n4 mx-3 z-index-2`, the gold
ribbon) pull the ribbon up 1.5rem above the `.card` element. A card row therefore only shows a real
gap below it if the ROW carries `mb-4`. A bare `<div class="row">` leaves just the column `mb-4`,
which the next row's `mt-n4` ribbon fully consumes, so the ribbons collide with the card above on
wide screens.

- Every dungeon-page card row must be `row mb-4` (the column `mb-4` alone is not enough).
- The spec page's top stat row is worse: its columns use `mb-xl-0` (zero bottom margin on wide
  screens), so a floating-ribbon card placed after it needs its own top clearance
  (`mt-4 mt-xl-5` on the row) or the ribbon overlaps the stat cards on xl. This is why the spec
  "Latest Hotfixes" row carries that top margin.

Related: [[build-new-page]], [[in-card-scroll-regions]].
