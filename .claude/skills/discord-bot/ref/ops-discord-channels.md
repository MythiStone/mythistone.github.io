---
name: ops-discord-channels
description: Which Discord webhook carries which ops output (the self-editing collector status and bot usage embeds vs. alerts, entrypoint pings and watchtower), and what the embeds need from docker-compose.yml to stay single and visible. Use when editing backend_scripts/discordHandler.py, discord_bot/usage_stats.py, entrypoint.sh / entrypoint_bot.sh alerts, the watchtower service or volumes in docker-compose.yml, or any WEBHOOK_* / STATUS_WEBHOOK_URL env handling.
kind: external
files:
  - backend_scripts/discordHandler.py
  - discord_bot/usage_stats.py
  - entrypoint.sh
  - entrypoint_bot.sh
  - docker-compose.yml
---

# Ops Discord channels

Two webhooks split the ops output so the self-editing embeds are never buried under messages that
append.

- **`STATUS_WEBHOOK_URL`** carries only the two messages that are edited in place: the collector
  status (`discordHandler.DiscordReporter`) and the bot usage (`usage_stats.UsageReporter`).
  Pointed at a dedicated channel, that channel only ever holds those two.
- **`WEBHOOK_URL`** carries everything that appends: collector alerts, the `post_alert` pings of
  `entrypoint.sh` and `entrypoint_bot.sh`, and the bot's `errors.post_alert`.
- **Watchtower** posts through `WEBHOOK_TOKEN` / `WEBHOOK_CHANNEL`.

What keeps the two embeds single and visible:

- **Both message ids live on docker volumes declared in `docker-compose.yml`** (`collector_state`,
  `bot_cache`). Watchtower recreates a container on every image update, so an id stored anywhere
  else is lost and a second message is posted.
- **The bot mounts `collector_state` read-only** to read the collector's message id and keep its
  own message below it. On a host without the collector the bot never reorders.
- **Both reporters re-post only on `discord.NotFound`.** Widening that to a generic `except` in
  either one leaves orphaned duplicates after a timeout or a rate limit.
- **A webhook can only edit or delete its own messages.** Pointing `STATUS_WEBHOOK_URL` at another
  webhook makes each reporter post once in the new channel, and the old messages have to be
  deleted by hand.
- `discord.Webhook.from_url` raises `ValueError` on a URL that is not shaped like a real webhook,
  so the placeholder `WEBHOOK_URL` of the CI smoke test disables the reporter. A test that needs a
  webhook object needs a correctly shaped fake URL.

`docker-compose.yml` is not part of any image. A change to it takes effect only after the file is
copied to the server and `docker compose up -d` is run there.

Related: [[collector-smoke-test]].
