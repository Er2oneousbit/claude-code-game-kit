# Troubleshooting Log

> Known issues and verified fixes. Future-you and testers should not need to ask how to fix these.
> Add an entry whenever a bug cost more than ~30 minutes or is likely to come back.

## Template (copy)
```
### <Short symptom>
- First seen: YYYY-MM-DD
- Environment: OS, engine version, build type
- Symptom: exact error text or behavior
- Root cause: 
- Fix: 
- How to verify: 
- Related: commit / ADR / issue
```

## Entries
### Smoke test hung: every scenario run waited forever
- First seen: 2026-10-22
- Environment: UE 5.8.4, UnrealEditor-Cmd automation
- Symptom: the pair test logged "Starting PIE for the automation tests" and then nothing for many minutes
- Root cause: `AutomationOpenMap` called inside a latent command queues its "start PIE" step at the END of the test's
  latent queue, behind all later runs, so the first run waits for a session that cannot start yet
- Fix: each run requests PIE itself (`GEditor->RequestPlaySession` + `StartQueuedPlaySessionRequest`), see `RDSmokeTests.cpp`
- How to verify: `python tools/dev.py smoke` finishes in about 3.5 minutes (2 before the regression test was added)

### Dead orcs looked alive
- First seen: 2026-10-22
- Symptom: "Room cleared" on screen while two orcs stood next to the mage
- Root cause: the Kenney `die` clip ends upright
- Fix: corpses are hidden `ARDOrc::CorpseSeconds` after death
- How to verify: record a run (`-record=`) and look at the frames after `ROOM_CLEARED`

### An open gate still looked closed
- First seen: 2026-10-22
- Symptom: the mage walked through a gate that was drawn shut
- Root cause: the Kenney gate's own animation keeps its bars in the doorway as seen from the top-down camera
- Fix: the gate meshes are hidden when the gate opens (the collider is removed and the door sound plays)
- How to verify: the frames after the first `ROOM_CLEARED`

### The packaged replay seemed not to match the test (it does)
- First seen: 2026-10-22
- Symptom: weaver seed 4 cleared at 40.0 s with 54 damage in the smoke test but 41.4 s with 84 in the packaged game
- Root cause: the two were built from different code (the packaged build predated a change to where the bot looks while
  walking); a first guess blamed the runtime NavMesh and was wrong
- Fix: compare like with like: package from the same code you tested
- How to verify: the smoke test and `RuneDelve.exe -autoplay=weaver -seed=6 -fixedfps -quitatend` both report 31 bolts,
  10 wards, 10 blocks, 138 damage (44.5 s against 44.6 s, 2026-10-26). Before the review fixes it was seed 4: 30 bolts,
  8 wards, 9 blocks, 54 damage (40.0 s against 40.1 s)

### -quitatend exited 0 when the mage died
- First seen: 2026-10-26
- Environment: UE 5.8, packaged Windows build
- Symptom: `RuneDelve.exe -autoplay=masher -seed=0 -fixedfps -quitatend` logs `MAGE_DOWN` and
  `RequestExitWithStatus(0, 3)`, but the process exit code is 0
- Root cause: a clean exit drops the code on Windows: it only reaches `PostQuitMessage`, and `GuardedMain` returns
  its own 0. Only a forced exit (`TerminateProcess`) carries it
- Fix: `ARDGameMode::QuitAtEnd` asks for a clean exit and, for a non-zero code, forces the exit with the code from
  `FCoreDelegates::OnExit`, after the world is shut down and the log flushed
- How to verify: the masher on seed 0 exits 3, the weaver on seed 6 exits 0 (both with `-quitatend`)
- Related: #8

### The packaged replay with -nullrhi plays a different delve
- First seen: 2026-10-26
- Symptom: weaver seed 6 cleared in 44.6 s with 10 wards in the packaged game (the smoke test: 44.5 s, 10 wards) but in
  46.3 s with 11 wards when `-nullrhi` was added; seed 4 also diverged (39.5 s against 36.7 s)
- Root cause (2026-11-05, measured with `-tracedelve`, one line per frame): the runtime NavMesh builds its tiles on
  worker threads and the navigation system picks the finished ones up at the start of whichever frame they are done
  in, real time, while the orcs (and the weaver's path) already walk on it. The first frame that differed between a
  rendered and a `-nullrhi` run of weaver seed 6 was frame 5 (0.083 s): the two room-1 orcs were hunting from frame 3
  with the NavMesh still building, and by frame 5 they stood a few millimetres apart in the two runs (different partial
  tiles, different first paths). Two things kept the build going all delve long: the bolt's collision sphere and orb
  counted for navigation, so every frame of a bolt's flight dirtied its tile and started a rebuild (16 rebuilds in the
  first 45 frames); and a tile that happens to finish inside the navigation system's own tick is announced to the
  paths crossing it (`OnNavMeshTilesUpdated`, a repath that costs the orc a frame of speed), one that finishes
  elsewhere is not, so even with the tiles landing on a fixed frame the orcs could repath on random frames. With both
  gone, one divergence was left, rarer (6 of 16 delves in the editor pair, none in four `-game` pairs): on one random
  frame an orc's speed dropped from 420 to 273.9 and climbed back by 34.1 a frame. That is exactly one frame of
  `UCharacterMovementComponent` braking (ground friction 8 times the braking factor 2, deceleration 2048) followed by
  re-acceleration at 2048/60: the movement component ticked *before* the orc's `UPathFollowingComponent` that frame,
  so it had no move request, braked, and got the request a frame late. Both tick in `TG_PrePhysics` and the engine
  sets no order between them. The earlier guesses (2026-11-02: every bolt rebuilds the NavMesh in real time; the bolt
  alone, which made the editor pair vary between runs) were half right
- Fix: three changes. `ARDBolt` takes its sphere and orb off navigation (a flying bolt is not level geometry), so the
  NavMesh now rebuilds three times per delve: at the start and when each gate opens. Under `-fixedfps`,
  `ARDGameMode::FinishNavBuild` runs on `FWorldDelegates::OnWorldPreActorTick` (after the navigation system ticks,
  before any actor does) and calls `EnsureBuildCompletion` on the NavMesh whenever a build is in progress, so every
  tile a frame started is finished before the first actor of that frame paths on it. `ARDOrcController::OnPossess`
  makes the orc's movement component tick after its path following (`AddTickPrerequisiteComponent`), so the move
  request always lands before the move that uses it. Side effect worth knowing: the
  delves changed (no bolt holes for the orcs to path around, no random brakes). Alone, this fix measured weaver 61,
  masher 52 of 80, clears 2/8 against 0/8 (was 65/55 and 3/8), one point under both pillar thresholds; with #140 (an
  open gate joins two rooms for perception) the pair measures weaver 73, masher 47, clears 6/8 against 0/8 and passes.
  The thresholds are the pillar, not the measurement, and stayed as they are
- How to verify: `python tools/unreal/replay_check.py --seed 6` (and `--seed 4`, `--bot masher`) runs the seed
  rendered and under `-nullrhi` and diffs the two `[trace]` streams; `[ OK ] ... identical`. Before the fix it reported
  frame 5 for seed 6. Two `python tools/dev.py smoke --filter Pair` runs in a row print the same 16 `[test]` lines
- Related: #8
