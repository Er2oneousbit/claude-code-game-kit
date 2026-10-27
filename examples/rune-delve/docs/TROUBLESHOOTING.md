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

### The packaged replay with -nullrhi plays a different delve
- First seen: 2026-10-26
- Symptom: weaver seed 6 cleared in 44.6 s with 10 wards in the packaged game (the smoke test: 44.5 s, 10 wards) but in
  46.3 s with 11 wards when `-nullrhi` was added; seed 4 also diverged (39.5 s against 36.7 s)
- Root cause: not known (verify); gameplay does not read animation or rendering on purpose
- Fix: none yet; compare replays with a renderer (a small window is enough: `-windowed -resx=640 -resy=360`)
- How to verify: run the same seed with and without `-nullrhi` and compare the `DELVE_COMPLETE` or `MAGE_DOWN` line
