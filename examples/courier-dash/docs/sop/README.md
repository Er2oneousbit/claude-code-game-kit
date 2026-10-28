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
| SOP-07 Claude Code hygiene | Every session | `/start-session`, `/end-session` |
| SOP-08 Scope control | Planning, new ideas, feeling the creep, moving to the next tier | `/gdd-sync`, `/next-tier` |
| SOP-09 Testing | Writing or reviewing tests | `code-reviewer` subagent |
| SOP-10 Performance | Frame time or memory trouble | `/perf-pass` |
| SOP-11 3D pipeline | Models, rigs, animation | `/model-pipeline` |
| SOP-12 Job plan, model roles, budgets | Starting a project, splitting work, effort levels, long or `/goal` runs | (manual; start from `docs/FIRST_HOUR.md`) |
| SOP-13 Publish to GitHub | Sharing the code: license, secret scan, private first, lock-down settings | `/publish-repo` |
| SOP-14 Game AI | Enemies, NPCs, companions: perception, decisions (FSM, BT, utility), pathfinding, debug views | `/game-ai` |
| SOP-15 Language models in your game | Talking NPCs, generated text: cloud vs local small models, keys, licenses, fallbacks, the "train our own LLM" reality check | (manual) |
| SOP-16 2D art pipeline | Exports from GIMP, Inkscape, Blender sprite sheets; pixel-art rules | `/model-pipeline` (3D to 2D), (manual) |
| SOP-17 Procedural generation | Levels made at runtime: invariants first, one seed one level, retry with a fallback, property tests and bots over many seeds | `/procgen` |

Every SOP starts with a **Goal**, gives the procedure, and ends with **Done when** and **Common mistakes** (SOP-08 calls them Warning signs).

New game? Start with `docs/FIRST_HOUR.md`. Why a rule exists and how sure we are: `docs/EVIDENCE.md` (claims taken from videos, docs or tests cite `E##` sources and `F##` findings; standard practice is uncited).
