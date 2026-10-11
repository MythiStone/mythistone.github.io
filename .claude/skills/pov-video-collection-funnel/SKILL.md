---
name: pov-video-collection-funnel
description: The gates a raider.io POV video passes before it lands in route_videos and on a streamer / VOD page (0-indexed leaderboard paging, one-shot run-details, keystone.guru route eligibility, timed-only rendering). Use when a streamer page or the VOD finder is missing videos that raider.io shows, or when editing route_poller_task, fetch_raider_page, fetch_run_details or fetch_keystone_route in collectLeaderboardData.py.
---

# POV video collection funnel

Streamer pages and the VOD finder render `route_videos`, which only the collector's
`route_poller_task` (collectLeaderboardData.py) fills. A raider.io video reaches a page only if it
passes every gate below, in order.

1. **Discovery is the world leaderboard only.** The poller pages
   `/api/v1/mythic-plus/runs?region=world&dungeon=<slug>&page=N` for each dungeon. Pages are
   **0-indexed** (page 0 = ranks 1-20) and 20 runs each; past the last page raider.io answers
   **HTTP 400** ("page must be less than or equal to N"; N is 100 without an access key), which
   `fetch_raider_page` treats as end of list. Only entries with `run.logged_run_id` are kept.
   Unlogged runs carry no `videos` in run-details anyway.
2. **Run-details are read once.** `handled_run_ids` is preloaded from `aura_run`
   (`read_aura_run_ids`), so any run with an `aura_run` row is never re-fetched. A video
   attached on raider.io after that fetch is never seen. Runs older than 28 days are skipped.
3. **keystone.guru route required.** `fetch_keystone_route` returns the route, `{}` for a 404,
   or `None` for a transient failure. On `None` the poller queues nothing and leaves the run
   unhandled, so no `aura_run` row exists and a later sweep (or restart) retries the whole run.
   Queuing it would persist auras and make the next restart's preload drop the route and videos
   for good. `_store_route_job` stores videos only for a newly inserted, eligible route
   (`route_key`, `mappingVersion`, `enemyForces >= enemyForcesRequired`): `route_videos` has a
   foreign key to `route_data`, so a logged run without a keystone.guru route keeps no videos.
4. **Rendering is timed-only.** `fetch_comp_vods` and `fetch_streamer_candidates` keep runs with
   `rd.duration <= dd.upgrade_1_duration`, so depleted runs never show.

## Diagnosing a missing VOD

The raider.io API needs no auth for these reads (send a normal User-Agent; urllib's default is
refused). For the character, `/api/v1/characters/profile?...&fields=mythic_plus_recent_runs,
mythic_plus_best_runs` gives `keystone_run_id`s. `/api/v1/mythic-plus/run-details?season=<slug>&id=<id>`
shows `videos`, `logged_run_id`, `logged_details.route_key` and `clear_time_ms` vs
`keystone_time_ms`. Scanning the dungeon's `/mythic-plus/runs` pages gives the run's page.
`https://mythistone.com/assets/json/compVods.json` is what was actually collected (keyed
`route_key_video_id`, with `run_id`).
