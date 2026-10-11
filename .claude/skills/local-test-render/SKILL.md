---
name: local-test-render
description: How to render MythiStone pages locally against a throwaway seeded MySQL. Use whenever you change a templates/*.html, a backend_scripts/generate*.py, pageGeneration.py/aggregateData.py/commonUtils.py, or page CSS/JS, and must verify the rendered page before handing it back.
files:
  - templates/*
  - backend_scripts/generate*.py
  - backend_scripts/pageGeneration.py
  - backend_scripts/aggregateData.py
  - backend_scripts/commonUtils.py
  - assets/js/*
  - assets/css/*
  - backend_scripts/localDev/*
---

# Local test render workflow

Never hand back page work that was only reasoned about. Render it against the local seeder in `backend_scripts/localDev/` (full docs: `backend_scripts/localDev/README.md`).

1. Seed a throwaway MySQL (needs Docker Desktop running). It starts one reusable `mysql:8` container `mythistone-testdb`, loads `backend_scripts/database.sql`, seeds plausible data from `data/static/**`, and runs the real `sp_run_agg_pipeline()`. Run `python backend_scripts/localDev/seed_test_db.py`. It prints `DATABASE_*` exports (user Test/test, host port 3399) in cmd / PowerShell / bash form. Point the generators at those. Seeded runs are timestamped inside the last 14 days, because the aggregations ignore older gear/talent data ([[gear-and-talent-data-retention]]).

   The local render is the required verification, so make Docker available rather than skipping it or hand-building a repro. **If Docker Desktop is not running, start it** (`Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`, then wait until `docker version` reports a Server) and proceed. GOTCHA: on this Windows box the **Bash tool cannot reach Docker** (`docker` there fails with `npipe:////./pipe/dockerDesktopLinuxEngine ... cannot find the file`). That error is the Bash-tool docker client, NOT proof Docker is down. Run docker and the seeder from the **PowerShell tool**, setting `DATABASE_*`/`KEYSTONE_GURU_*` with `$env:`. Never conclude "Docker isn't running" from a Bash failure, and never fall back to a custom test page to dodge the real render.

2. Render the page you changed with its generator. Use the arguments that the buildPages workflow uses. Output dirs (`dungeons/`, `classes/`, `items/`, `pages/`) are gitignored. Examples:
   - `python backend_scripts/generateDungeonPages.py --template templates/dungeon_page.html --output_dir dungeons`
   - `python backend_scripts/generateItemPages.py --template templates/items.html --output_dir pages --items_dir items`
   - `python backend_scripts/generateCompPage.py --template templates/comps.html --output_dir pages`
   - `python backend_scripts/generateSpecPages.py --template templates/spec_page.html --output_dir classes` (add `--spec=252` to render just one spec; `--spec` takes a numeric spec id, NOT a class/spec token, so Unholy DK is `--spec=252`, not `--spec=unholy`. Passing a token silently matches nothing and renders no page.)

3. Serve the repo root (pages use absolute `/assets/` paths) and inspect in the Browser pane: `python -m http.server 8099 --bind 127.0.0.1` (port matches `.claude/launch.json`), then open `http://127.0.0.1:8099/<path>`. A freshly opened page shows a cookie banner: decline all cookies first, then confirm the cards you touched render with data and the console has no errors.

4. Optional teardown: `python backend_scripts/localDev/seed_test_db.py --teardown`.

Every generator (spec, index, dashboard, dungeon, item, comp, routes, analyzer, tierlist, search, sitemap, llms) is credential-free: it needs only the `DATABASE_*` exports.

Dungeon renders: For synthetic seed routes the keystone.guru thumbnail fetch can poll an error job for up to 25 minutes per dungeon (looks like a hang). Without the credentials, it fails fast and the page renders minus the route-map image, which cannot exist for a fake route. See [[add-database-table]] for keeping the seeder complete when the schema grows.
