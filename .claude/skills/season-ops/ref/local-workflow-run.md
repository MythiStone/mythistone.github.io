---
name: local-workflow-run
description: A workflow change is verified by running the changed job through act (nektos/act) against the seeded local DB, from a scratch copy of the workflow. Use when editing anything under .github/workflows or a script a workflow step calls.
kind: workflow
files:
  - .github/workflows/*
---

# Run changed workflow jobs locally with act

act runs a job in Docker with the real actions. It is the workflow counterpart of
[[local-test-render]]. It needs the Docker engine, started as that skill says. winget installs act at
`%LOCALAPPDATA%\Microsoft\WinGet\Links\act.exe`, which a shell started before the install does not
have on `PATH`.

1. **Seed** the test DB (`seed_test_db.py`, see [[local-test-render]]). Write a secret file in
   the scratchpad, never the repo: `DATABASE_HOST=host.docker.internal`, `DATABASE_PORT=3399`,
   and `DATABASE_USER`, `DATABASE_NAME` and `DATABASE_PASSWORT` (the secret's real spelling) from
   the seeder's printout. `resolve-season` and `prepare-sims` pass on the seeded data.
2. **Scratch copy of the workflow without `ref: main`.** With `ref:` set, act runs the real
   `actions/checkout`, which clones origin `main` into the container, so the local edits never run.
   Without it, act uses the working tree. `grep -v "^          ref: main$"` into the scratchpad,
   then `-W <copy>`.
3. **Runner image with gh.** `catthehacker/ubuntu:act-latest` has docker and node but no `gh`, so
   `gh` steps exit 127. Build `FROM catthehacker/ubuntu:act-latest` + `apt-get install -y gh` as a
   local tag, pass `-P ubuntu-latest=<tag> --pull=false`.
4. **Run** `act workflow_dispatch -W <copy> -j <job> --secret-file <file> -s GITHUB_TOKEN
   --artifact-server-path <scratch dir>`, with `GITHUB_TOKEN` exported from `gh auth token`. `-j`
   also runs every job in the `needs` chain and applies their `if:` gates. Artifacts v4 pass
   between those jobs. A GHCR pull needs the token's `read:packages` scope. `act -l` prints the job
   graph without Docker.

Traps:

- **Never run a job that publishes**: deploy, the season archive, an image push, social posts or
  Discord broadcasts. act uses the real token, so they would really publish. Pick the job with `-j`.
- Seeded gear and talents are synthetic, and simc rejects them at init. A simc gate over
  generated gearsets fails locally. Prove the pass path with a second scratch copy that gates on
  simc's `profiles/CI.simc`.
- act masks every secret value in its logs, even inside words. The seeded password `test` turns
  `latest` into `la***`.
- act cannot show `schedule` and `workflow_run` triggers, the `permissions:` scoping of the real
  `GITHUB_TOKEN`, the repo token's GHCR package access, or a Pages deploy. List them under Not
  verified.
