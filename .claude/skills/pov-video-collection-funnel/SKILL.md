---
name: pov-video-collection-funnel
description: The gates a raider.io POV video passes before it lands in route_videos and on a streamer / VOD page (0-indexed leaderboard paging, VOD-first sweep ordering, run-details re-read only for a video that is not stored, keystone.guru route eligibility, timed-only rendering). Use when a streamer page or the VOD finder is missing videos that raider.io shows, or when editing route_poller_task, order_route_sweep, fetch_raider_page, fetch_run_details or fetch_keystone_route in collectLeaderboardData.py.
---

# POV video collection funnel

Streamer pages and the VOD finder render `route_videos`, which only the collector's
`route_poller_task` (collectLeaderboardData.py) fills. A raider.io video reaches a page only if it
passes every gate below, in order.

1. **Discovery is the world leaderboard only.** Every `ROUTE_SWEEP_SECONDS` the poller pages
   `/api/v1/mythic-plus/runs?region=world&dungeon=<slug>&page=N` for all dungeons, then works one
   queue until the next scan. Pages are **0-indexed** (page 0 = ranks 1-20) and 20 runs each; past
   the last page raider.io answers **HTTP 400** ("page must be less than or equal to N"; N is 100
   without an access key), which `fetch_raider_page` treats as end of list. A page that fails any
   other way is skipped, three in a row end that dungeon's scan. Only entries with `run.logged_run_id` are kept. Each list entry carries
   the same `videos` array as run-details, and `listed_video_ids` reads it.
2. **Run-details are read once, except for a video that is not stored.** `handled_run_ids` is
   preloaded from `aura_run` (`read_aura_run_ids`) and `known_video_ids` from `route_videos`
   (`read_route_video_ids`). `order_route_sweep` queues every unhandled run, plus any handled run
   whose list entry shows a video id outside `known_video_ids`: raider.io links VODs after a run
   was first collected, and an `aura_run` row does not prove the route was stored. Runs with such
   a video go first, then newest first, across all dungeons. The fixed 10 s per run caps a sweep
   well below the leaderboard size, so anything without a new video is a newest-first sample. A
   re-fetched run drops its `run_details_cache` entry first. Runs older than 28 days are skipped.
3. **keystone.guru route required.** `fetch_keystone_route` returns the route, `{}` for a 404,
   or `None` for a transient failure. On `None` the poller queues nothing and leaves the run
   unhandled, so no `aura_run` row exists and a later sweep (or restart) retries the whole run.
   Queuing it would persist auras and make the next restart's preload drop the route and videos
   for good. `_store_route_job` stores videos with a newly inserted, eligible route
   (`route_key`, `mappingVersion`, `enemyForces >= enemyForcesRequired`), and on a duplicate
   route through `insert_route_video_for_run`, which only matches the route of the video's own
   run. `route_videos` has a foreign key to `route_data`, so a logged run without an eligible
   keystone.guru route keeps no videos. Those count as `vod_runs_without_route` in the collector
   stats and are re-checked once per collector restart.
4. **Rendering is timed-only.** `fetch_comp_vods` and `fetch_streamer_candidates` keep runs with
   `rd.duration <= dd.upgrade_1_duration`, so depleted runs never show.

## Diagnosing a missing VOD

The raider.io API needs no auth for these reads (send a normal User-Agent; urllib's default is
refused). For the character, `/api/v1/characters/profile?...&fields=mythic_plus_recent_runs,
mythic_plus_best_runs` gives `keystone_run_id`s. `/api/v1/mythic-plus/run-details?season=<slug>&id=<id>`
shows `videos`, `logged_run_id`, `logged_details.route_key` and `clear_time_ms` vs
`keystone_time_ms`. Scanning the dungeon's `/mythic-plus/runs` pages gives the run's page.
The live site's compVods.json (https://mythistone.com/assets/json/compVods.json) is what was
actually collected (keyed `route_key_video_id`, with `run_id`).
