---
name: artifact-only-deploy
description: Built pages are never committed; the site deploys straight from the Pages artifact and generated paths are gitignored. Use when adding a generator, wiring output dirs, reasoning about deployment, or wondering why old commit hashes or committed HTML are missing.
kind: coupling
files:
  - .github/workflows/buildPages.yml
  - .gitignore
---

# Nothing generated is committed

`.github/workflows/buildPages.yml` assembles `_site/` and deploys it as a Pages artifact. Two
things follow for every generator:

- **A new generated path goes into `.gitignore`.** Generated JSON is listed there per file, not by
  wildcard.
- **A generator creates its own output directory.** A CI checkout has none of them.

Related: [[season-snapshot-archive]].
