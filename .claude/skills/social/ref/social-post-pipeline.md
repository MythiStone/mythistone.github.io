---
name: social-post-pipeline
description: How the daily automated social post is selected, turned into facts and hooks, drafted and judged by free LLMs, and where its records live. Use when editing backend_scripts/generateSocialsPost.py, anything under backend_scripts/social_posts/ (pipeline.py, hooks.py, voice.py, llm.py, context.py, snapshot.py), automatedSocialMediaPosts.yml, or when adding a new post type.
files:
  - backend_scripts/generateSocialsPost.py
  - backend_scripts/social_posts/*
  - .github/workflows/automatedSocialMediaPosts.yml
---

# Social post pipeline

`automatedSocialMediaPosts.yml` runs `generateSocialsPost.py` daily -> `social_posts/pipeline.py`.
`socials.json` (text records) and `social_snapshot.json` (weekly standings) live on the
`social-images` branch next to the images (`--socials-file` / `--snapshot-file`); the workflow
commits all three. Launch-window and pre-season gates post static copy (no LLM) before any DB work.
Besides Bluesky and the fixed `DISCORD_WEBHOOK`, the post goes to every server channel subscribed
through the bot (see [[bot-news-channel-subscriptions]]).

- **Selection** (`pipeline.select_post`): one weighted pick per group (`GROUP_WEIGHTS`), so all spec
  overviews share one slot. Anti-repeat (`blocked_groups`): never the last post's type, at most 2
  spec overviews per 7 days, underdog cooldown 7 days; blocked groups are a last-resort fallback.
- **Facts -> hooks** (`hooks.build_facts`): the model never sees raw `post_data` keys. It gets a few
  human-labelled facts plus 1-3 hook sentences whose comparisons (role rank, gap to role/dungeon
  average, timer ratio, hero-tree dominance) are computed in Python from `context.load_season_context`
  (all specs/dungeons: runs, timed %, tier via `tierMath`, cached per process). Gaps are computed
  from the ROUNDED percentages so "88% vs 81%" reads as 7 points. Hook text counts as allowed
  numbers for validation. Types that build their own `{"facts", "hooks"}` (weekly mover, underdog)
  pass through; `static_copy` still reads the raw keys for blog copy.
- **Voice** (`voice.py`): persona per post, weighted by post type, never the previous record's
  `persona`. The prompt lists the last 8 captions' openings as "do not start like these".
- **Drafts + judge** (`llm.py`): up to `DRAFT_COUNT` (4) validated drafts across the top free
  OpenRouter models within `MAX_DRAFT_CALLS` (12). Validation rejects invented numbers, snake_case
  keys, more than 3 numbers, semicolons, a recycled opening (kept only as a last-resort fallback)
  and >230 chars. A free-model judge scores the drafts (drafts under 6 accuracy never win); any judge
  failure falls back to fewest-numbers. Records store `persona` and `judge_score`.
- **Weekly mover** is only offered when `snapshot.find_movers` finds a big move against the snapshot
  7-10 days old (same season): a dungeon's highest timed key rose or its tier changed, or a spec's
  tier changed or its share of groups moved >= 1.5 points (or >= 25% relative and >= 0.5 points).
  Popularity is deliberately not used for dungeons (it barely moves late in a season). 6-day cooldown.
- **Underdog spotlight**: an S/A-tier spec in the less-played half of its role
  (`context.underdog_candidates`), once per spec per month. Both of these types render with
  `image_generation/spotlight_card.py`.
- **New post types** need a `generateBlogPage.py` `POST_TYPE_META` + `FILENAME_TYPE_PATTERNS` entry
  and `static_copy` title/blog branches. Chart point labels from `chartData.create_spec_scatter` are
  bare spec names ("Frost"), so resolve full names via the icon before putting them in post facts.
- **Offline testing**: stub `llm.select_models` / `get_openai_client` (and
  `posts.get_openai_client`) with a fake client and run the generators against the seeded local DB
  ([[local-test-render]]). `--debug` needs neither.

Related: [[social-image-mock-harness]].
