# Plan: shared knowledgebase, domain agents, lower token use

Working document. Delete it once the phases below are done; the durable parts end up in
`AGENTS.md`, `.claude/agents/`, `.claude/skills/` and `.claude/kb/`.

Decisions already made: map files + local MCP server, consolidate skills by domain, a planner plus
four domain agents (database, pages/frontend, discord-bot, collector+infra), every agent on
`model: inherit`, and the main/Explore agent must start with the full routing knowledge.

## 1. Where the tokens go today (measured)

| Cost | Size | When it is paid |
|---|---|---|
| Skill listing (58 descriptions) | ~5.1k tokens | Every turn of every session and of every subagent that lists skills |
| `databaseConnector.py` | 228 KB, ~57k tokens | Each time an agent reads it to find a query or the function that wraps it |
| `database.sql` | 159 KB, ~40k tokens | Each time an agent looks up a table, column or proc |
| `generateSpecPages.py` / `templates/spec_page.html` / `simcBis.py` | ~190 KB each, ~48k tokens | Each time someone touches spec pages or simc |
| Built-in `Explore` / `Plan` | Start with no CLAUDE.md or AGENTS.md | They rediscover the architecture with grep and reads on every call |
| Same rules stated 3-4 times | test-render mandate in CLAUDE.md, AGENTS.md, `mythistone-expert.md`, and a hook | Every session |
| Post-edit hooks | ~100 tokens of reminder on **every** edit under `backend_scripts/`, `templates/`, `assets/`... | 20-60 times in a normal task, and each one nudges the agent to go re-read skills |

Health problems found while measuring:

- **`.claude/settings.json` is invalid JSON** (trailing comma after `"Bash(git show:*)",`). The
  allow/deny lists and all three hooks may not be loading at all.
- **Stale references in skills.** `route-search.js` (three skills, including two always-loaded
  *descriptions*), `comp-routes-worker.js`, `backend_scripts/fetchRouteData.py`,
  `fetch_runs_per_region_day`, and `fetch_period_run_stats` no longer exist. Agents are sent looking for files
  that aren't there, then search further to recover.
- `mythistone-expert` restates AGENTS.md and preloads nothing, so it costs a cold start without
  saving one.

## 2. Target architecture

```
                      ┌──────────────── main session / Explore (override) ───────────────┐
                      │ AGENTS.md routing table + kb MCP. Small single-domain edits inline │
                      └───────────────┬───────────────────────────────┬──────────────────┘
                     cross-domain or  │ unclear scope                 │ multi-file, one domain
                                      ▼                               ▼
                               ┌─────────────┐   context packet   ┌────────────────────────────┐
                               │   planner   │ ─────────────────▶ │ database │ pages │ bot │ infra │
                               └─────┬───────┘                    └─────┬──────────────────────┘
                                     │      all read the same source    │ handoff note (findings)
                                     ▼                                  ▼
                 ┌────────────────────────── mythi-kb (local MCP, stdlib) ──────────────────────────┐
                 │ live map (parsed from code on start)      +      curated gotchas (.claude/skills/*/ref) │
                 │ tables, procs, SQL consts, connector fns,       one md per gotcha, with `files:` globs │
                 │ callers, generator→template→assets, bot cogs                                          │
                 └───────────────────────────────────────────────────────────────────────────────────────┘
```

Agents never share knowledge by talking to each other. They share it in three ways:

1. **One source of truth, two layers.** The *map* is generated from the code, so it cannot go
   stale. The *gotchas* are curated, and each one declares which files it covers. The MCP server
   serves both, and the same files are readable without MCP (Codex, Cline).
2. **Context packets.** The planner resolves the KB lookups once and hands each domain agent a
   packet: files, symbols, tables and gotcha ids. The domain agent starts from the packet and does
   not repeat the lookups.
3. **Handoff notes.** Each domain agent returns changed symbols plus any new findings. The main
   agent passes these on to the next agent in the plan, and proposes the findings to the user for
   recording (the existing "ask first" rule stays).

The subagent `memory:` field is deliberately **not** used. It writes per-agent silos without asking
the user, which conflicts with the recording rule and would split knowledge across agents.

Honest caveat: a subagent starts cold, so delegating a 2-line fix costs more than doing it inline.
The savings come from the preloaded indexes and the MCP slices. The number of agents doesn't
create them. The routing rule below keeps small work inline.

## 3. Components

### 3.1 `mythi-kb` MCP server + map builder

- `.claude/kb/kb.py`: a single **stdlib-only** module (`ast` + regex, no `mcp` pip package,
  consistent with the repo's no-requirements reality). It builds the index in memory from the code
  on start, which takes well under a second.
- `.claude/kb/server.py`: a minimal stdio JSON-RPC MCP server (`initialize`, `tools/list`,
  `tools/call`) over `kb.py`. It is registered in a root `.mcp.json`, so every session and subagent
  inherits it.
- `python .claude/kb/kb.py --write` emits `.claude/kb/map/*.md` (gitignored) for tools without MCP.

| Tool | Returns (a slice, typically 0.3-2k tokens instead of a 40-60k file) |
|---|---|
| `kb_overview()` | Domains, owning agent, domain skill, verification command |
| `kb_table(name)` | Columns, keys, tablespace, writer procs, reading `*_SQL` consts → connector fns → callers, gotchas |
| `kb_symbol(name)` | Any connector fn / `*_SQL` / proc / generator fn: location, signature, SQL text, callers |
| `kb_page(name)` | generator → template → includes/macros → page css/js → emitted JSON → connector fns |
| `kb_bot_command(name)` | cog → slash command → embeds/fetchers → connector fns |
| `kb_file(path)` | Domain, owner agent, gotchas whose `files:` globs match |
| `kb_gotcha(id)` / `kb_search(q)` | One gotcha body / search across gotchas and the map |
| `kb_lint()` | Every path/symbol cited in a gotcha that no longer exists |

The prototype run on the current tree parses 90 tables, 36 procs, 211 `*_SQL` constants (209
resolve to tables), 225 connector functions (169 with external callers), and 18 generators.

### 3.2 Skills: 58 micro-skills → 9 domain skills + reference files

Each domain skill's `SKILL.md` is a short index: what the domain owns, its verification step, and
a table of `gotcha id → one-line rule → files`. The current skill bodies move unchanged (except
for stale-ref fixes) to `.claude/skills/<domain>/ref/<id>.md`, each with a `files:` frontmatter
glob list. Claude loads a reference file only when it needs it, and the MCP server reads the same
files. Only the 9 short descriptions are listed per turn (~1k tokens instead of ~5.1k).

| Domain skill | Absorbs |
|---|---|
| `database` | add-database-table, aggregation-pipeline, dedup-dictionary-hash-contract, gear-and-talent-data-retention, pooled-connection-gotchas, runs-per-dungeon-rollup, table-storage-placement, verify-database-sql, comp-routes-specs-fallback, keystone-guru-mapping-data |
| `pages` (generators, templates, page data) | build-new-page, page-data-and-scripts, enchant-lookup-filter, enchant-link-icon-rune-fallback, item-quality-from-bonus, item-source-filters, dungeon-best-loot-card, dungeon-npc-portrait-icons, spec-team-comps, frontend-json-dungeon-keys, top-trends-bar, tierlist-gear-modal, analyzer-page, route-accordion-macro |
| `frontend` (css/js/ui) | frontend-design-tokens, frontend-framework-choices, chart-theming, minify-assets, deep-links, bootstrap-capture-phase, datatables-empty-state, floating-header-card-rows, in-card-scroll-regions, infinite-scroll-pages, klaro-consent-embeds, notification-dismiss-persistence, sidenav-footer-flow |
| `local-test-render` | stays standalone (shared by pages, bot smoke test, social images) |
| `discord-bot` | discord-bot, bot-command-usage-tracking, bot-news-channel-subscriptions, ops-discord-channels |
| `collector-simc` | collector-smoke-test, simc-baseline-vs-page-gear, simc-chunked-checkpoint, simc-resilient-build, loadout-v2-encoder, keystone-route-api-limits |
| `season-ops` (CI, deploy, season lifecycle) | season-rollover-wipe, season-wipe-invariants, season-snapshot-archive, season-launch-day-presentation, blizzard-preseason-period, build-cadence-phases, artifact-only-deploy |
| `social` | social-post-pipeline, social-image-mock-harness |
| `knowledgebase-authoring` | stays, updated for the new layout (gotcha = ref file with `files:`; map facts are never hand-written) |

### 3.3 Agents (`.claude/agents/`, all `model: inherit`)

| Agent | Preloads (`skills:`) | Tools | Owns |
|---|---|---|---|
| `Explore` (overrides built-in) | `kb-routing` slice of AGENTS.md via `kb_overview` | Read, Grep, Glob, Bash (read-only), `mcp__mythi-kb` | Lookups. MCP first, file reads only for the exact range a tool pointed at |
| `planner` | all 9 domain indexes (short) | read-only + `mcp__mythi-kb` | Cross-domain or unclear tasks. Outputs a plan where every step names the owning agent plus a context packet |
| `database` | `database`, `local-test-render` | all + kb | `database.sql`, `databaseConnector.py`, aggregation, `localDev/` registry |
| `pages` | `pages`, `frontend`, `local-test-render` | all + kb | `generate*.py`, `templates/`, `assets/`, shared generator modules |
| `discord-bot` | `discord-bot`, `local-test-render` | all + kb | `discord_bot/`, `Dockerfile.bot`, bot CI, ops webhooks |
| `collector-infra` | `collector-simc`, `season-ops`, `social` | all + kb | collectors, simc, Docker images, workflows, season ops, social posts |

- `permissions.deny: ["Agent(Plan)"]` routes planning to `planner`. Explore is overridden by name
  (documented behaviour), so it keeps working but now carries the knowledge.
- `mythistone-expert.md` is removed. Its unique content (the docker and bot "verify by running it"
  mandates, the self-check list) moves into the matching domain agents.
- Each domain agent prompt ends with the handoff format: *changed symbols, verification run and
  result, proposed KB findings*.

### 3.4 AGENTS.md / CLAUDE.md

- AGENTS.md gains a **Routing** section: domain → agent → skill → verify command, plus the rule
  *"single-domain edit of a few files: do it inline; multi-file in one domain: domain agent;
  cross-domain or unclear: planner first; never grep-read the 40-60k-token files for lookups when
  a kb tool answers it."*
- Remove the duplicated test-render text (keep it once in AGENTS.md; CLAUDE.md just points).
- The directory map stays because it is small and stable. Anything the map generates (file
  sizes, function lists) is never hand-written.

### 3.5 Hooks

- Merge `remind-test-render.py` + `remind-update-skills.py` into one `kb-file-context.py`
  (PreToolUse on Edit|Write). On the **first** edit of a file per session it injects only the
  gotcha ids whose `files:` match, plus the test-render reminder once per session per domain. A
  state file in the temp dir, keyed by `session_id`, dedupes. Expected effect: from ~50 reminders
  per task to a handful, each one specific.
- SessionStart: `kb.py --write` only when a source file is newer than the map.
- Keep `block-git-write.py` as is.
- `kb_lint` runs in the SessionStart hook (warn) so stale references surface immediately.

## 4. Phases

| # | Work | Done when |
|---|---|---|
| 0 | Fix `settings.json` trailing comma; fix the 5 stale refs (confirm renames: `route-search.js`→`routes-finder.js`? `comp-routes-worker.js`→`finder-worker.js`? where `fetchRouteData.py` and the two `fetch_*` went) | JSON parses, hooks fire, no dead refs |
| 1 | `kb.py` + `server.py` + `.mcp.json` + `kb_lint` | Every tool answers on the current tree; lint is clean |
| 2 | Skill consolidation (move bodies, add `files:`, write 7 new domain indexes, update `knowledgebase-authoring`) | `kb_file()` maps every touched subsystem to its gotchas; old skill dirs gone |
| 3 | Agents + Explore override + planner + `Agent(Plan)` deny + AGENTS.md routing; remove `mythistone-expert` | Agents load with their preloads; routing table matches `kb_overview()` |
| 4 | Hook merge + SessionStart rebuild/lint | Reminder count per task drops; no reminder without a matching gotcha |
| 5 | Measure: re-run 3 representative past tasks (one DB, one page, one bot) and compare session tokens to a baseline taken before phase 0 | Documented before/after; tune preloads |

Each phase lands as one reviewable change you commit yourself (per AGENTS.md, no agent git).

## 5. Open questions

1. **Stale renames** in phase 0: are `routes-finder.js` and `finder-worker.js` the successors,
   and were `fetchRouteData.py` / `fetch_runs_per_region_day` / `fetch_period_run_stats` removed
   or renamed?
2. **Other tools:** do you use Codex/Cline on this repo? If yes, commit `.claude/kb/map/*.md`
   (with a CI drift check) instead of gitignoring it.
3. **Pages vs frontend agent:** one `pages` agent preloading both skills (planned), or split it
   into two agents? Split only if the preload is still too heavy after phase 5.
