---
name: in-card-scroll-regions
description: The shared .card-scroll-body / .card-scroll utility for a list or table that scrolls inside a card while filling the card's real height. Use when a card list needs its own scrollbar, when two h-100 cards in a row should stay level, or before hand-rolling an inline max-height + overflow-y box.
---

# In-card scroll regions

For a list/table that should scroll inside a card while filling the card's real height (so two
`h-100` cards in an equal-height row stay level with no dead space under the list), use the shared
utility in `custom-scrollbars.css`:

- `.card-scroll-body` on the `.card-body` (makes it a `min-height:0` flex column).
- `.card-scroll` on the scrolling child (`flex:1 1 auto`, `min-height:0`, `overflow-y:auto`, capped
  at `--card-scroll-max`, default 470px, override inline per card e.g.
  `style="--card-scroll-max: 435px;"`).
- Pair with `.custom-scrollbar` for the themed scrollbar. `.custom-scrollbar` only styles scrollbar
  appearance, so do NOT hand-roll the inline `max-height; overflow-y:auto` box for card-filling
  lists.

The taller sibling drives the row height; the scroll region fills to that height and scrolls its
overflow (sticky `thead` inside still pins). Used by comps Hidden Gems / Best Spec Combinations and
dungeon Most Lusted Pulls.

The utility needs the card height-bounded (an `h-100` card in an equal-height row, or an explicit
height). It is not for a fixed-height scroll box sitting below other content in a column (e.g. comps
`#suggestions-container` keeps its own inline `max-height`).

Related: [[frontend-design-tokens]], [[floating-header-card-rows]].
