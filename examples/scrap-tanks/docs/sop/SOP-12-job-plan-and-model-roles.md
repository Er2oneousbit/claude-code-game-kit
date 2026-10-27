# SOP-12: Job Plan, Fresh Sessions, Model Roles, and Budgets

## Goal
Build a whole game without ever asking for "the whole game". Split the work into small jobs, give each a clean session and a test,
so a failure sends back one job, not the project. Evidence: F2, F4, F5, F9 in `docs/EVIDENCE.md` (grade B, many creators).

## Steps
1. **References before anything.** A mood image, screenshots of the feel you want, then in-game mockups from an image model.
   Lock one FINAL image per scene in `docs/CONCEPTS.md` (F3). The game in your head is not in the prompt until you show it.
2. **Color bible.** Palette with names and hex per role (ground, sky, light, danger, UI, each faction) in `docs/CONCEPTS.md`.
   If the reference is daylight and the game is night, translate every color first and write the translation down (tip, E03).
   Put the palette into the `docs/BRIEFS.md` style fragments so every generator prompt carries it.
3. **Plan with the strongest model, in its own session.** Ask for the job list: what we build, why, in what order, and the test that proves
   each job. Save it to `docs/ROADMAP.md`. End the planning prompt with "Ask me questions first" or "Do you understand? Restate the plan." (tip, E05)
4. **One job, one fresh session.** Give it only the job, the docs it needs (`@docs/...`), and the test. A fresh session reads less,
   makes fewer mistakes, and costs fewer tokens. Run `/end-session` and `/clear` between jobs (`SOP-07`).
5. **Every job ends with its tests** (`SOP-09`): `check` and `test` always, plus `smoke` or a scripted scenario when the
   job touches the running game. If it fails, only that job goes back.
6. **Mechanics before art.** Plain tiles for levels and placeholder pixel-art sprites for characters first (`tools/art/pixel_sprite.py`; in 3D, a capsule with a head and arms). The game must be playable and fun with placeholders (`SOP-01`, F4).
7. **Debug panel early.** Sliders and presets (lighting, speeds, spawn rates), plus god mode, teleport, time of day (F7). Strip it from release (`SOP-06`).
8. **Parallel tracks when the work is independent** (tip, E05). For example: characters (concept, 3D draft, rig, own `.blend`), environment props
   (separate `.blend`), and a gray-box mechanics gym. Bring each into the game only when ready, through a preview scene.
9. **Record cost and time per job** in the "Budget and cost log" table in `docs/ROADMAP.md`. You learn which model is cheapest per good result.

## Model roles (an example split, not a benchmark)
| Role | Job |
|---|---|
| Strongest planning model | Hard calls: what we build and why, the job list, design arguments, the shared brief |
| Coding model | Mechanics, systems, tests, build scripts |
| Blender-capable model | Blender scripts, decimation, materials. Pick by taste on your own art, not by reputation |
| Cheap helper model | Capture prompts, screenshots, commit messages, journals |
| You | Mood, taste, playtesting, saying no |
Any model can do any row. The principle is separation of jobs (F9). A brief written by a different session than the builder reads more like your intent.

## Effort and budget rules
| Situation | Effort level | Budget rule |
|---|---|---|
| Iteration, small fixes, tests | Medium | Default |
| A hard design call, a hero scene, the first slice | High or xhigh | Write a time or token cap in the job |
| Max, multi-hour unattended runs | Only on purpose | Check your plan's weekly limit first, set a hard credit cap on every paid generator API |
Level names differ between Claude Code versions (videos call the top levels "extra" and "ultra"); check the effort picker in yours.
Reported reality (F5, grade B): one-request scenes took 1.5 to 7+ hours and $20 to $125+ (E19); a 36-hour run used a full weekly limit and about
$2,200 API-equivalent (E25); one hobby run hit its limit after about 1.5 to 2 hours (E26); another hit a session limit partway through (E21). Detail in `docs/evidence/field-reports.md`.
- **Spend on the brief before the effort level** (tip, E62): one creator built the same real-time strategy clone from one
  short prompt at each Opus 5.5 level: low $3.80 (19 min), medium $9.25 (36 min), high $16 (1 h), xhigh $35 (1 h 41),
  max $70 (about 3 h). Low already had most of the game's buildings and logic; the higher levels mostly bought graphics
  and fewer stuck units. Then a long brief listing everything the runs had missed, at low, cost $13.57 (1 h 23): about
  what high cost. The transcript read for the kit stops before his verdict on it.
- **Price one job before many** (tip, E51): before fanning out paid generation (images, 3D, voice) or a swarm of parallel agents, run
  one, write down what it cost and how long it took, then size the batch. One developer spent a week of image quota on parallel
  jobs in one go, about half of it on art he threw away.

## Several agents on one job (worked example: this kit)
For work wider than one session holds well: an audit, a big review, a migration. One session coordinates, helpers each take
one slice and report back, and the coordinator checks every finding before anything changes.

| Role | Who | What it does |
|---|---|---|
| Coordinator | Your main Claude Code session | Splits the job, briefs the helpers, verifies each finding against the files, makes the changes |
| Wide readers | Subagents on a cheaper model (for example Sonnet; **verify** current models) | One slice each, read-only, the same report shape: severity, file and line, evidence, one-line fix |
| Hard calls | A subagent on the strongest model (for example Fable) | A design choice, a tricky bug, judging between plans. Costs the most **(verify current models and prices)**: use it where quality decides the outcome |
| Second opinion | Another vendor's model, read-only (`tools/second_opinion.py`, Kimi Code CLI) | Reviews a change the coordinator made, and catches what the author agrees with itself about (F9) |

Rules:
- **Findings are claims.** The coordinator verifies each against the files before fixing; in the audit below 2 of 48 were wrong (K01).
- **Outside helpers are read-only.** A CLI agent in non-interactive mode approves its own tool calls (Kimi Code's `-p`, E55), so give it
  a tool allowlist with no shell, no writing and no web (`tools/second_opinion/kimi-agent.md`: Read, Grep, Glob).
- **Your data leaves the machine** with any outside model: keep secrets and work material out of the folder it reads (`SOP-13`).
- **Price one before many** (tip, E51): run one helper, note its cost, then fan out. Give helpers slices that do not overlap.

Worked example (K01, 2026-10-22):
- **Audit:** five Sonnet reviewers (beginner path, tools, engine overlays, SOPs, examples), about 0.8M tokens against about 23M for
  an earlier all-out run. 48 findings: 45 confirmed and fixed, 2 refuted by the coordinator, 1 not reproduced and left alone.
- **Second opinion:** Kimi K3, read-only, reviewed a Godot export change: it confirmed the parser and the exit codes and found the
  one real problem (two notes still calling a just-verified command untested). Asked to review `second_opinion.py` itself, its
  review quoted the error strings the tool looks for and tripped the tool's own login check: a bug found by using the tool.
  Once that was fixed, its review listed four problems. The coordinator checked each before touching code: three were real
  (one had already happened live, one was measured at 20 s past a 2 s timeout), and the fourth only partly so.
```
python tools/second_opinion.py --check                                     # installed and logged in?
python tools/second_opinion.py --ask "Review this change for real bugs" --files tools/dev.py docs/ENGINE_FLOW.md
```

## Long autonomous runs (`/goal` or an overnight run)
Use only when the job has a verifiable end state. Claude Code's `/goal` keeps working until a small model judges the condition met, and that judge
reads only the transcript, so the condition must demand printed proof (F19, E28). Recipe (E25, E28):
1. Human prep first: GDD, references, mockups, color bible, in/out list, and your own skills, all in the repo.
2. Commit, branch, auto mode, deny rules still on (`SOP-07`). Never bypass permissions outside a sandbox.
3. Condition = measurable end states + the command that proves each + constraints + "stop after N turns".
4. Make it keep a journal: milestone screenshots and a log of your feedback. It doubles as crash recovery.
5. State lives in files (`HANDOFF.md`, `ROADMAP.md`, git), so a crash or reboot costs minutes, not the run (tip, F15).
6. Afterwards review like a stranger: the interaction smoke checklist in `SOP-09`.

## Done when
- The plan is in `ROADMAP.md`, each job has a test and a budget, references and the color bible exist, and the game was playable with placeholders before final art.

## Common mistakes
- Letting one long chat carry ten jobs.
- One giant prompt for the whole game, then rework when it is not your game (E26 lost 1.5 hours this way).
- Starting art before the color bible and references exist.
- Running max effort by default and hitting the weekly limit on day one.
- Asking for realistic meshes instead of simple stylized ones (`SOP-11`).
