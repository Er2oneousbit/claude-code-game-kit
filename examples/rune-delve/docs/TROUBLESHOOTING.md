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
- Root cause (2026-11-02): the runtime NavMesh. A bolt's collision sphere counts for navigation, so every cast
  dirties the NavMesh and starts a rebuild on worker threads (logged: a build every 0.4 s, the bolt cooldown). The
  rebuild takes real time, so how many fixed 1/60 s frames the bots and orcs path on the old NavMesh depends on how
  fast frames run; without a renderer they run faster. Two `-nullrhi` runs of seed 6 differed from each other too
  (43.0 s and 44.6 s)
- Tried: `SetCanEverAffectNavigation(false)` on the bolt's sphere. Packaged rendered and `-nullrhi` runs then
  matched on all 8 weaver seeds, but the editor's bot pair varied between runs (67/53, 68/51, 71/53 of 80) where
  the old code repeats 65/55: the rebuilds at the start and at each gate still run in real time. Pausing the world
  while the NavMesh builds stalled the regression test. Neither is in; the next try is a NavMesh that never
  rebuilds during a delve (gates off the NavMesh, the start held until the first build is done)
- Fix: none yet; compare replays with a renderer (a small window is enough: `-windowed -resx=640 -resy=360`)
- How to verify: run the same seed with and without `-nullrhi` and compare the `DELVE_COMPLETE` or `MAGE_DOWN` line
- Related: #8
