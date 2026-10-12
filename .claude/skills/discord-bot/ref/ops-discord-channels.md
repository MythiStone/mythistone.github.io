---
name: ops-discord-channels
description: Which Discord webhook carries which ops output (the self-editing collector status and bot usage embeds vs. alerts, entrypoint pings and watchtower), and the rules that keep the embeds from being orphaned or buried. Use when editing backend_scripts/discordHandler.py, discord_bot/usage_stats.py, entrypoint.sh / entrypoint_bot.sh alerts, the watchtower service or volumes in docker-compose.yml, or any WEBHOOK_* / STATUS_WEBHOOK_URL env handling.
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

- **`STATUS_WEBHOOK_URL`** (optional, falls back to `WEBHOOK_URL`) carries only the two
  edited-in-place messages: the collector status (`discordHandler.DiscordReporter`, two embeds) and
  the bot command usage (`usage_stats.UsageReporter`, see [[bot-command-usage-tracking]]). Pointed at
  a dedicated channel, that channel only ever holds those messages.
- **`WEBHOOK_URL`** carries everything that appends: `DiscordReporter.send_alert` /
  `send_oneshot_alert`, the standalone low-disk warning, the `entrypoint.sh` / `entrypoint_bot.sh`
  `post_alert` pings and `discord_bot/errors.post_alert`.
- **Watchtower** posts through `WEBHOOK_TOKEN`/`WEBHOOK_CHANNEL` (a shoutrrr
  `discord://token@id` URL built in `docker-compose.yml`). `WATCHTOWER_NOTIFICATION_REPORT` and
  `WATCHTOWER_NO_STARTUP_MESSAGE` make it send one report per real update or failure and nothing
  for a no-op scan or its own start.

Rules that keep the embeds single and visible:

- **Both message ids must sit on a docker volume.** Watchtower recreates the container on every
  image update, so an id kept in the container filesystem is lost and a fresh message is posted,
  leaving the old one behind. The collector's id is in `data/state/discord_status.json`
  (`collector_state` volume), the bot's in `data/bot_cache/usage_status.json` (`bot_cache` volume).
  `DiscordReporter._ensure_webhook_message` sends a warning to `WEBHOOK_URL` when it has to create
  the status message at startup while `data/state` is not a mount, because that is the only sign
  the volume is missing on the server.
- **The usage message sits below the collector status.** The bot mounts `collector_state`
  read-only and `UsageReporter.update` compares the collector's message id
  (`config.COLLECTOR_STATUS_FILE`) with its own. Snowflakes are time ordered, so a greater
  collector id means the status was posted later, and the bot deletes and re-posts its usage
  message. Without the file (no collector on the host) the bot never reorders.
- **Both reporters re-post only on `discord.NotFound`.** Any other edit failure (timeout, 5xx, rate
  limit) keeps the id, logs one line and retries on the next tick. Do not widen that to a generic
  `except`, it is what prevents orphaned duplicates.
- **A webhook can only edit or delete its own messages.** Pointing `STATUS_WEBHOOK_URL` at a
  different webhook makes the old id answer `NotFound`, so each reporter posts once in the new
  channel and the old message has to be deleted by hand.
- `DiscordReporter` builds two webhook objects in webhook mode (`_status_webhook` for the status
  message, `_webhook` for alerts). Its `bot` mode (`WEBHOOK_TOKEN` + `WEBHOOK_CHANNEL` as a bot
  token and channel id) only applies when `WEBHOOK_URL` is unset, which `entrypoint.sh` forbids.
- `discord.Webhook.from_url` validates the URL shape (long numeric id, long token) and raises
  `ValueError` on anything else, so the CI smoke test's placeholder `WEBHOOK_URL` simply disables
  the reporter. Tests that need a real webhook object must use a correctly shaped fake URL.

`docker-compose.yml` is not part of any image, so changes to it (volumes, watchtower env) only take
effect when the file is copied to the server and `docker compose up -d` is run there.

Related: [[bot-architecture]], [[collector-smoke-test]].
