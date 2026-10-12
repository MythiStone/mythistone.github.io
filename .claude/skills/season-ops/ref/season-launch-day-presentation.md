---
name: season-launch-day-presentation
description: How the social auto-poster and the Discord bot present the pre-season gap vs the season's first 24h, and why launch day needs its own time-based gate. Use when touching season_gate, social_posts/pipeline.py, image_generation/season_countdown.py, or the bot's guards/errors/embeds around a season start.
kind: coupling
files:
  - backend_scripts/season_gate.py
  - backend_scripts/social_posts/pipeline.py
  - backend_scripts/image_generation/season_countdown.py
  - discord_bot/guards.py
  - discord_bot/errors.py
  - discord_bot/embeds.py
---

# Pre-season and launch day: two gates, two consumers

The social poster (`backend_scripts/social_posts/pipeline.py`) and the bot
(`discord_bot/guards.py`, `discord_bot/errors.py`) both switch to a "no data yet" presentation
around a season start. They share two gates and must apply them in the same order:

1. **Launch window**, `in_launch_window` in `backend_scripts/image_generation/season_countdown.py`:
   the first 24 hours after the earliest regional start.
2. **Pre-season**, `season_gate.season_has_started`: the season has no runs yet.
3. Otherwise the normal data paths.

The time gate exists because the run gate flips on the first logged run, while the nightly
aggregation has not run for the new season yet. The aggregate tables that the generators and the
bot commands read are absent on launch day, not just thin.

Both presentations are pure time plus `seasonInfo.json`. Verify them with a synthetic `seasonInfo`
whose starts are relative to now (for example us -3h, eu +10h, kr +29h). No DB is needed.

Related: [[social-post-pipeline]], [[bot-architecture]].
