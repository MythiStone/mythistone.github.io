---
name: social
description: "MythiStone automated social posts: post selection, facts and hooks, LLM drafting and judging, and the social image renderers. Use when editing generateSocialsPost.py, social_posts/, image_generation/ or automatedSocialMediaPosts.yml."
---

# Social domain

Owner agent `collector-infra`. Owns `generateSocialsPost.py`, `backend_scripts/social_posts/`, `backend_scripts/image_generation/`, `renderAllSocialImages.py`.

**Verify:** The `social-image-mock-harness` gotcha renders images against the seeded DB.

**Look things up, do not read whole files.** The `mythi-kb` MCP tools (or `python .claude/kb/kb.py <tool> <arg>`)
return the slice you need: `kb_table`, `kb_symbol`, `kb_page`, `kb_bot_command`, `kb_file`, `kb_search`.
Open a source file only at the range a tool pointed to.

## Gotchas

Before changing a file listed below, read its gotcha: `ref/<id>.md` in this skill (or `kb_gotcha <id>`).
`kb_file <path>` lists every gotcha for a path across all domains.

| id | rule | files |
|---|---|---|
| `social-image-mock-harness` | How to verify the social image renderers in backend_scripts/image_generation/ locally against the seeded local test DB | `backend_scripts/image_generation/*` |
| `social-post-pipeline` | How the daily automated social post is selected, turned into facts and hooks, drafted and judged by free LLMs, and where its records live | `backend_scripts/generateSocialsPost.py`, `backend_scripts/social_posts/*`, `.github/workflows/automatedSocialMediaPosts.yml` |
