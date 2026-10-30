# Distill Prompt: shape the Claude Code Game Kit

How to use: unzip the kit into an empty folder, open Claude Code there with Opus at high or extra effort (not max), start a FRESH session, paste everything below the line. Commit first. Plan mode first, then let it build.

> **Status:** first distill done on 2026-10-19 (see `CHANGELOG.md`). On a re-run, the material to fold in is whatever was added since: new rows in `core/docs/evidence/video-notes.md`, new `E##` rows in `core/docs/EVIDENCE.md`, and anything appended to `core/docs/resources/`. Keep the existing structure unless it has clearly failed.

How to use as a goal (recommended): run Claude Code in auto mode on a new branch, then paste the one-line command from `DISTILL_GOAL.txt`. `/goal` keeps Claude working turn after turn until a small evaluator model sees every end-state check proven in the transcript, so the goal text demands printed proof. The goal points at this file for the full process. The condition limit is 4,000 characters.

---

You are the lead maintainer of the "Claude Code Game Kit", a reusable starter kit (CLAUDE.md, skills, subagents, SOPs, per-engine flows, a scaffolder, and resource lists) for starting a game project with Claude as co-developer, project manager and programmer. Visuals and audio are made with other tools; Claude writes briefs, scripts, glue and tests.

## What happened so far
Over many sessions I pasted transcripts of about 25 videos and several screenshots, and the kit grew by appending. Everything was recorded fast with honest labels (claimed, unverified, creator's claims), on purpose: "record it all now, clean it up later". Later is now. The kit is bloated, repetitive, and some of it is raw notes instead of rules.

## Your job
Distill it into a smaller, sharper, trustworthy kit. Keep what is true, repeated or high-value. Cut or demote what is one-off hype. Do not invent facts, and do not delete evidence I may want. Move it instead.

## Read first (in this order)
1. `README.md`, `core/CLAUDE.md`, `core/docs/sop/README.md`
2. All `core/docs/sop/SOP-*.md`
3. `core/docs/RESOURCES.md` (index), `core/docs/resources/`, `core/docs/EVIDENCE.md`, `core/docs/evidence/` (raw notes)
4. `core/docs/BRIEFS.md`, `VERTICAL_SLICE.md`, `CONCEPTS.md`, `GDD.md`
5. `core/.claude/` (skills, agents, settings), `core/tools/`, `scripts/new_game.py`
6. `engines/*/` (godot, cpp-sdl2, unreal, unity: `engine.json`, `ENGINE.md`, `FLOW.md`, skeleton)

## Process (follow this order, one job per fresh sub-agent or session, each ends with a check)
**Job 1: Evidence ledger.** Build `core/docs/EVIDENCE.md`: one row per source (video, tool, repo, doc) with: id, title, channel, date, what it claims, confidence (see scale below), which kit files rely on it. Pull from the RESOURCES video table and the sections that cite them. Mark sponsored or affiliate sources.
**Job 2: Claims audit.** List every instruction in the SOPs, skills and flows that rests on a single source. Classify each claim:
- **Standard:** backed by 2+ independent sources, or by official docs, or by something already tested in this kit. Becomes a rule.
- **Reported:** one source, plausible. Stays as a clearly labeled tip.
- **Hype:** vague, sponsored, or contradicted. Move to the ledger only.
Recurring themes I already noticed (verify, do not trust me): vertical slice before art; GDD and color bible first; one job per fresh session ending in a test; plan with the strongest model, build with a cheaper one; reference images in the brief; mockups before building; static scenes look great while animation, collision, audio, vehicle feel and UI wiring break; vary camera angles when self-checking; interaction smoke checklist; Steam AI disclosure buckets; long autonomous runs cost real money and limits; bypass-permissions risk; do not ship clones of commercial games.
**Job 3: Restructure RESOURCES.md.** Split it into small files under `core/docs/resources/` (music, sfx, art-2d, art-3d, fonts-ui, tools-and-mcp, map-data, learning, marketing-release, license-cheatsheet) plus `EVIDENCE.md`. Keep a short `RESOURCES.md` index with a "start here" pick per category. Every row keeps its license caveat and **(verify)** marker. Target: no file over about 150 lines, and the index fits on one screen.
**Job 4: Tighten the SOPs.** Merge overlaps, fold "data point" content into the right SOP as rules, keep each SOP to Goal, Steps, Done when, Common mistakes. Update `SOP-09` (smoke checklist), `SOP-11` (3D pipeline, incl. creature animation as experimental), `SOP-12` (job plan, model roles, long autonomous runs). Keep copyright and IP guidance in `SOP-04`.
**Job 5: Slim the always-loaded context.** `core/CLAUDE.md` must stay short and index-like (target under 80 lines). Anything long moves to docs that load on demand. Check every `@import`. Skills must have crisp descriptions so they trigger correctly. Subagents should have narrow jobs and minimal tools.
**Job 6: Engines.** Make the four engine overlays consistent (same sections, same command contract `python tools/dev.py check|test|smoke|build|run|clean|doctor`, same exit codes 0/1/2, `--debug` everywhere). Keep each overlay's tested status exactly as README "What was tested" and CHANGELOG record it; never downgrade an earlier verified result, only add new verification. Consider adding a Roblox stub overlay using `engines/_template/`, marked experimental.
**Job 7: Close the gaps.** Tell me what is missing for a solid starter kit and build the cheap ones: for example `tools/blender/validate_asset.py` (UV and poly checks, needs `bpy`, mark untested if you cannot run it), a one-page "first 60 minutes with a new game" guide, and a decision tree "which engine, which flow". Do not build big speculative systems.
**Job 8: Independent review.** Spawn a separate reviewer agent that has NOT seen your work. Give it the final tree and ask it to find contradictions, broken links, stale references, rules without evidence, and anything that would confuse a stranger on day one. Fix what it finds.

## Confidence scale (use in EVIDENCE.md)
- **A:** official docs or tested in this kit
- **B:** 2+ independent creators agree
- **C:** one creator, plausible, results shown on video
- **D:** one creator, hype or sponsored, or numbers unclear
- **X:** contradicted or unusable

## Hard constraints
- No em dashes anywhere. Plain ASCII punctuation in docs and code.
- Honesty: never present a NEW claim as verified unless you verified it this session (earlier verified results stay as recorded). Keep **(verify)** on store policies, licenses and prices. Say "I don't know" and what you checked.
- Do not delete source evidence. Demote it into `EVIDENCE.md` or a clearly named archive file.
- Code style for anything you write: high-level pseudocode comment first, small modular functions, comments for a reader six months later, robust error handling, `--debug`, a real `--help`. Header comment names Claude and the model used. Footer: none on kit tools, `{{FOOTER}}` on starter code (see `profiles/README.md`). PowerShell must be PS7+ and warn on PS5.
- Handoff quality: a tester or dev must be able to use the kit without asking me. Organized for unfamiliar users.
- Scope control: if a change is big or risky, write an ADR in `core/docs/adr/` instead of just doing it.
- Do not tell me to stop and go do things. Make the call, note the assumption, keep moving.

## Verification (run it, show the output)
- For each engine: `python3 scripts/new_game.py --name "Test Game" --engine <id> --dest /tmp/gs/<id>` then `python3 tools/doctor.py` inside the result. All must pass.
- `LC_ALL=C.UTF-8 grep -rnP "\x{2014}" .` must print nothing (that pattern is the em dash character; the locale makes grep accept it).
- No leftover `{{` placeholders in scaffolded output (doctor's own check string is the only expected hit).
- Every markdown link and `@import` resolves.
- Delete `__pycache__`, then zip the kit and give me the zip.

## Deliverables
1. The distilled kit (zip).
2. `CHANGELOG.md` entry: what moved where, what was cut, what was promoted to a rule, and why.
3. A one-page report to me: top 10 rules the kit now enforces, top 10 things that are still unverified, and the 5 most valuable next experiments I should run myself to turn "reported" into "tested".

## Ask me at most three questions, and only if you are truly blocked. Otherwise state your assumptions at the top of your plan and begin. Show the plan first.
