---
name: pov-video-collection-funnel
description: What a raider.io POV video has to pass before it is stored and shown on a streamer or VOD page, and how to find out where a missing one was dropped. Use when a streamer page or the VOD finder is missing videos that raider.io shows, or when editing route_poller_task, order_route_sweep, fetch_raider_page or fetch_keystone_route in collectLeaderboardData.py.
kind: external
files:
  - backend_scripts/collectLeaderboardData.py
  - backend_scripts/generateVodsPage.py
---

# POV video collection funnel

Streamer pages and the VOD finder render `route_videos`, which only `route_poller_task` in
`backend_scripts/collectLeaderboardData.py` fills. A raider.io video is lost at one of three gates:

1. **Discovery reads the world leaderboard only.** raider.io pages are 0-indexed with 20 runs each
   and answer HTTP 400 past the last page, which is page 100 without an access key. Only runs with a
   `logged_run_id` are kept.
2. **A sweep is a sample.** The fixed delay per run caps a sweep well below the leaderboard size.
   `order_route_sweep` puts runs with a video that is not stored first, everything else is newest
   first, and runs older than 28 days are skipped.
3. **A keystone.guru route is required.** `route_videos` has a foreign key to `route_data`, so a
   logged run without an eligible route keeps no videos. On a transient keystone.guru failure the
   run must stay unhandled, as `fetch_keystone_route` and its caller arrange: queuing it would
   persist its auras, and the next restart would drop the route and its videos for good.

## Diagnosing a missing VOD

The raider.io API needs no auth for these reads, but refuses urllib's default User-Agent.

- `/api/v1/characters/profile?...&fields=mythic_plus_recent_runs,mythic_plus_best_runs` gives the
  character's `keystone_run_id`s.
- `/api/v1/mythic-plus/run-details?season=<slug>&id=<id>` shows `videos`, `logged_run_id`, the
  route key and whether the run was timed.
- The live compVods.json (https://mythistone.com/assets/json/compVods.json) is what was actually
  collected.
- The collector status embed shows "VODs Stored" and "VODs w/o Route". The second number is the
  size of gate 3. Read it before deciding whether `route_videos` should stop depending on
  `route_data`.
