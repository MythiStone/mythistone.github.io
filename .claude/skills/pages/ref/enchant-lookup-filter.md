---
name: enchant-lookup-filter
description: Which enchants a spec or item page shows is decided by one shared predicate, an offline expansion id and a 14-day denominator, and a missing enchant is usually deliberate. Use when enchant entries look missing on a spec or item page, or when editing enchant filtering in generateSpecPages.py / generateItemPages.py / commonUtils.py.
kind: coupling
files:
  - backend_scripts/generateSpecPages.py
  - backend_scripts/generateItemPages.py
  - backend_scripts/commonUtils.py
---

# Enchant display filter

- **One predicate for both pages.** `commonUtils.is_enchant_relevant` decides for
  `generateSpecPages.py` and `generateItemPages.py`. Do not filter enchants anywhere else.
- **An id absent from `data/static/enchantments.json` is hidden on purpose.** That is how
  old-expansion enchants on normally unenchantable slots are suppressed. Supplement files and
  wago.tools imports for absent ids were rejected: do not propose generating enchant metadata from
  another source.
- **Generators stay offline.** `commonUtils.current_expansion_id` reads the value that
  `backend_scripts/fetchSeasonAndPeriodInfo.py` writes into `seasonInfo.json`. A build that fails
  on a missing `expansion_id` means the season fetch has not run since the field was added.
- **Popularity thresholds use the 14-day `fetch_spec_sample_size` denominator**, never the
  season-wide `fetch_runs_per_spec` ([[gear-and-talent-data-retention]]).

When an enchant is missing, check the threshold first, then its catalog record's expansion and
slot fit.

Related: [[enchant-link-icon-rune-fallback]].
