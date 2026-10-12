---
name: social-post-pipeline
description: What the daily social post depends on outside social_posts/ (its records on the social-images branch, the blog generator's post-type tables, chart labels) and how to test it offline. Use when adding a post type, editing backend_scripts/generateSocialsPost.py, anything under backend_scripts/social_posts/, or automatedSocialMediaPosts.yml.
kind: coupling
files:
  - backend_scripts/generateSocialsPost.py
  - backend_scripts/social_posts/*
  - .github/workflows/automatedSocialMediaPosts.yml
---

# Social post pipeline: what sits outside the modules

Selection, hooks, voices, drafting and judging are described in the module docstrings under
`backend_scripts/social_posts/`.

- **The records live on the `social-images` branch**, next to the images: `socials.json` and
  `social_snapshot.json`. `.github/workflows/automatedSocialMediaPosts.yml` commits all three.
- **A new post type is registered in `backend_scripts/generateBlogPage.py` too**, in both
  `POST_TYPE_META` and `FILENAME_TYPE_PATTERNS`, and gets title and blog branches in `static_copy`.
- **Chart labels from `chartData.create_spec_scatter` are bare spec names** ("Frost"). Resolve the
  full name through the icon before one goes into post facts.
- **Offline test:** stub `llm.select_models` and `get_openai_client` with a fake client and run the
  generators against the seeded local DB ([[local-test-render]]). `--debug` needs neither.

Around a season start the post is static copy: [[season-launch-day-presentation]].
