# SOP-09: Testing

## Goal
Cheap automated checks catch regressions so playtesting time goes to fun, not to re-finding old bugs.

## Test pyramid for games
1. **Static/parse checks** (`dev.py check`): seconds. Run after every edit.
2. **Unit tests** (`dev.py test`): pure logic with no engine, no rendering. Fast and deterministic.
3. **Headless smoke test** (`dev.py smoke`): boot the game for N frames with no window or a dummy driver. Fails on errors in the log.
4. **Scripted scenarios** (as the project matures): simulated input traces or replays, assert on end state.
5. **Manual playtests**: for feel, fun, readability. Logged per SOP-03.

## What to unit test
- State machines, scoring, inventory, damage math, procedural generation with fixed seed, save/load round trips,
  input buffering (coyote time, jump buffer), cooldown timers, pathfinding on small grids.

## What not to unit test
- "Does it look right", animation polish, anything that needs a human eye. Use playtests.

## Rules
- Tests run without the editor or a display wherever the engine allows.
- Tests are deterministic. Seed RNG. Inject time instead of reading the clock.
- Name tests as behaviors. One assertion idea per test.
- Bug fix means a regression test when feasible.
- Flaky tests get fixed or deleted. Never ignored.
- **One acceptance suite per system** (tip, E51): combat, classes, maps, saves, each with tests that drive the real game (or a
  real local server), all run before a release. Then adding a class or a level does not mean retesting the old ones by hand.
- **Visual self-checks use several viewpoints** (tip, F10 grade C; a default because it costs almost nothing): front, side, rear, top, a close-up of anything that moves, and the first, middle and last frame of any sequence. One-angle checks missed invisible tires on an AI-built truck (E19).

## Exams for tools and pipelines
When Claude builds a tool (animation retargeter, asset validator, importer), build an **exam** alongside it:
- A fixed set of inputs with known-good expected outputs (clips, meshes, files).
- Numeric pass criteria (joint error, poly count, foot-slide distance, file validity), not "looks fine".
- One command to run it all, and a printed score. Re-run after every change so improvements do not silently break old cases.
- Add every new failure case to the exam. The exam is how an AI-built tool stays trustworthy.

## Interaction smoke checklist (AI-built 3D games)
Most AI-built 3D games reviewed for this kit broke in the same places (F1, grade B, seven independent creators). Claude runs these before saying "done",
and automates what it can in `dev.py smoke` or a scripted scenario:
| Check | Typical failure seen |
|---|---|
| Walk into every wall, building, bridge; stand on roofs; look for holes in floors | No or wrong collision |
| Spawn points clear of geometry; every building and room can be exited | Stuck at spawn or inside a building |
| Frame-rate floor measured on the target machine, as a number in the test | Builds dropping to single-digit FPS |
| Every key on the controls screen does what it says | Documented bindings that do nothing |
| Every menu button leads somewhere | Dead garage or loadout buttons in a "finished" game |
| Player model, hands and held item visible in first and third person | Invisible character or weapon |
| Audio plays in a fresh run: music, a UI click, a gameplay sound (browser builds: after the first click) | Whole game silent |
| Enemies cannot see or hit through walls (raycast test with a wall between) | Bots shooting through walls |
| Enter and exit every vehicle, drive 60 seconds; flip rate and chase camera acceptable, tuning in config | Cars that flip constantly, no exit |
| Every time-of-day and weather preset: fog, exposure, post-processing readable | Washed out by fog, pitch-black water |
| Animation spot check: run, jump, attack, idle, hold item, from two angles | Floating feet, items through the head |

## Reviewing tests (`code-reviewer` checklist)
- Fails for the right reason? Remove the fix and see.
- Tests behavior, not implementation details.
- No sleeping on real time.

## Done when
- New logic has tests or a written reason why not. `test` and `smoke` are green on main. Exception: a project with no tests yet
  (a fresh or Blueprint-only Unreal project has no `<Game>.Smoke` tests) gets exit 2 "nothing ran"; record that gap in HANDOFF
  and use the engine substitute from `docs/ENGINE_FLOW.md` (Unreal: `test --filter` on functional tests) until real tests exist.

## Common mistakes
- Testing only in the editor, or only from one camera angle.
- Trusting the agent's own "all checks passed" without looking (E02 scored 84 percent while most frames were broken).
- Sleeping on real time or unseeded randomness, then calling the test flaky.
