# Standard Operating Procedures

Short, followable, engine-agnostic. Engine specifics are in `docs/ENGINE_FLOW.md`.

| SOP | When to use it | Skill that runs it |
|---|---|---|
| SOP-01 Feature workflow | Building anything new | `/new-feature` |
| SOP-02 Bug workflow | Something is broken | `/bug-hunt`, `/stuck` |
| SOP-03 Playtest and tuning | After anyone plays the build; player reports in GitHub Issues | `/playtest-report`, `/triage-issues` |
| SOP-04 Assets and licensing | Any third-party or AI-assisted content | `/asset-intake`, `/gen-brief` |
| SOP-05 Git | Branching, commits, LFS | (manual) |
| SOP-06 Build and release | Shipping a build | `/release-check` |
| SOP-07 Claude Code hygiene | Every session; running out of tokens or usage | `/start-session`, `/end-session`, `/token-audit` |
| SOP-08 Scope control | Planning, new ideas, feeling the creep, moving to the next tier | `/gdd-sync`, `/next-tier` |
| SOP-09 Testing | Writing or reviewing tests | `code-reviewer` subagent |
| SOP-10 Performance | Frame time or memory trouble | `/perf-pass` |
| SOP-11 3D pipeline | Models, rigs, animation | `/model-pipeline` |
| SOP-12 Job plan, model roles, budgets | Starting a project, splitting work, effort levels, long or `/goal` runs | (manual; start from `docs/FIRST_HOUR.md`) |
| SOP-13 Publish to GitHub | Sharing the code: license, secret scan, private first, lock-down settings | `/publish-repo` |
| SOP-14 Game AI | Enemies, NPCs, companions: perception, decisions (FSM, BT, utility), pathfinding, debug views | `/game-ai` |
| SOP-15 Language models in your game | Talking NPCs, generated text: cloud vs local small models, keys, licenses, fallbacks, the "train our own LLM" reality check | (manual) |
| SOP-16 2D art pipeline | Exports from GIMP, Inkscape, Blender sprite sheets; pixel-art rules | `/dotwork` (pixel art on your own GPU), `/model-pipeline` (3D to 2D), (manual) |
| SOP-17 Procedural generation | Levels made at runtime: invariants first, one seed one level, retry with a fallback, property tests and bots over many seeds | `/procgen` |
| SOP-18 Game feel | Shake, hitstop, easing, follow camera, input buffer, squash; the shake off switch and the flash limit | `/game-feel` |
| SOP-19 Front end and settings | Menus, settings, versioned saves with backups, rebinding and prompts, localization and the pseudo-locale, crash logs, consent-first telemetry | `/game-shell` |
| SOP-20 Accessibility | Subtitles and captions, text size, colour, controls, motion and flashes, difficulty: the baseline every game ships | (manual; `/game-shell` builds the settings) |
| SOP-21 Ship on Steam and itch | Store page and assets, SteamPipe and butler uploads, achievements, cloud, demos, signing, CI, the legal checklist | `/release-check` |
| SOP-22 Balancing and economy | Numbers in data, a balance sheet, sources and sinks, curves, bots and playtests that measure | (manual) |
| SOP-23 Marketing | Coming Soon early, capsules and screenshots, trailer, press kit, devlog, the wishlist beat plan | (manual) |

Every SOP starts with a **Goal**, gives the procedure, and ends with **Done when** and **Common mistakes** (SOP-08 calls them Warning signs).

New game? Start with `docs/FIRST_HOUR.md`. Why a rule exists and how sure we are: `docs/EVIDENCE.md` (claims taken from videos, docs or tests cite `E##` sources and `F##` findings; standard practice is uncited).
