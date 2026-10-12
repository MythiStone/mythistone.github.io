---
name: in-card-scroll-regions
description: The shared .card-scroll-body / .card-scroll utility for a list or table that scrolls inside a card while filling the card's real height. Use when a card list needs its own scrollbar, when two h-100 cards in a row should stay level, or before hand-rolling an inline max-height + overflow-y box.
kind: workflow
files:
  - assets/css/custom-scrollbars.css
---

# In-card scroll regions

A list or table that scrolls inside a card uses the `.card-scroll-body` / `.card-scroll` utility in
`assets/css/custom-scrollbars.css`, not an inline `max-height; overflow-y: auto` box. The utility
fills the card's real height, so two `h-100` cards in a row stay level.

It needs a height-bounded card: an `h-100` card in an equal-height row, or an explicit height. A
fixed-height scroll box that sits below other content in a column keeps its own inline `max-height`.

Related: [[floating-header-card-rows]].
