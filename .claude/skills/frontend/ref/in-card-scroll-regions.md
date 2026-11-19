---
name: in-card-scroll-regions
description: The shared .card-scroll-body / .card-scroll utility for a list or table that scrolls inside a card while filling the card's real height. Use when a card list needs its own scrollbar, when two h-100 cards in a row should stay level, or before hand-rolling an inline max-height + overflow-y box.
kind: workflow
files:
  - assets/css/custom-scrollbars.css
---

# In-card scroll regions

A list or table that scrolls inside a card uses the `.card-scroll-body` / `.card-scroll` utility in
`assets/css/custom-scrollbars.css`, not an inline `max-height; overflow-y: auto` box.

- The list adds only a floor (`--card-scroll-min`, per use) to the row's height and grows to fill
  a taller `h-100` card. It never makes the row taller than its neighbour, and never leaves dead
  space beside one. Stacked it shows the floor, or less where `calc-size()` lets a short list shrink.
- It needs a height-bounded card: an `h-100` card in an equal-height row, or an explicit height. A
  fixed-height scroll box that sits below other content in a column keeps its own inline
  `max-height`.
- A long list in a card that stacks on phones also gets "Show all": put `data-show-all="<noun>"`
  plus `show-all-lg` or `show-all-xxl` (the breakpoint where its row goes side by side) on the
  element whose direct children are the items. Below it the scroll box is dropped, 5 items show
  and `assets/js/show-all.js` adds the button. It re-counts when the list is re-rendered.

Related: [[floating-header-card-rows]].
