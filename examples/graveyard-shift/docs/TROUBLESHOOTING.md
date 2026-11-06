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
### Tuning changes did nothing in the game (but tests saw them)
- First seen: 2026-10-21
- Environment: Unity 6000.6.6f1
- Symptom: a ghost noticed the lit keeper at 12.9 m with SightLit set to 11 in `GameTuning.cs`
- Root cause: C# field defaults only seed a NEW ScriptableObject; the existing `SO_GraveyardSetup.asset` kept 14. EditMode
  tests used `new GameTuning()`, so tests and game disagreed silently
- Fix: tests load the asset (`TestTuning.Load`); `dev.py exec SceneBuilder.ResetTuning` copies code defaults into the asset
- How to verify: change a default, run ResetTuning, check `Assets/Config/SO_GraveyardSetup.asset`

### Every bot path was PathInvalid
- First seen: 2026-10-21
- Symptom: bots walked in straight lines into gravestones; the trace showed `path PathInvalid corners=0`
- Root cause: `NavMesh.CalculatePath` does not snap its ends to the NavMesh (`NavMeshAgent.SetDestination` does)
- Fix: `NavMesh.SamplePosition` both ends first (`KeeperBot.Steer`)
- How to verify: `GRAVEYARD_TRACE=1 python tools/dev.py smoke --filter Smoke_C`

### The scene lost its reference to the setup asset
- First seen: 2026-10-21
- Symptom: `Bootstrap has no SO_GraveyardSetup` at boot although SceneBuilder assigned it
- Root cause: `EditorSceneManager.NewScene(..., Single)` unloads unused assets; the reference held from before was dead
- Fix: load the asset again after NewScene; SceneBuilder now fails loudly if the reference is missing
- How to verify: `python tools/dev.py exec SceneBuilder.Build`, then `grep "setup:" Assets/Scenes/Graveyard.unity`

### Screenshots landed in the built player's folder
- First seen: 2026-10-21
- Symptom: capture PNGs inside `Build/` next to `game.exe`
- Root cause: `build/` and `Build/` are the same folder on Windows
- Fix: capture into `Logs/` (`--screenshot Logs/shot.png`, `--record Logs/frames`)
- How to verify: `Build/` holds only the player

### A bot night that does not replay (the always-lit bot's catches read 12 or 14)
- First seen: 2026-11-02 (issue #160), looked into 2026-11-05
- Environment: Windows 11, Unity 6000.6.6f1, AI Navigation 2.0.16, `dev.py smoke` (batchmode, with and without `-nographics`)
- Symptom: the same hand-made night gave a different catch count between runs; two ghosts that passed close were a millimeter apart
- Root cause: not reproduced. Eleven process runs of `Smoke_A` on the current code (alone, in parallel, with a
  graphics device, inside the full smoke, the same night three times in one process) and three on the code of 11-02
  gave the same positions on every one of 144,000 frames per run, physics-clock phase or not; a head-on pass of two
  ghosts (the agents' avoidance at work, 0.901 m apart) replays too. Which of the ten runs of 11-02 read 12 is not
  recorded; six of them ran with physics settings changed
- Fix: none to make. `Smoke_R10` (the always-lit night twice, every frame compared) and `Smoke_R11` (the head-on
  pass) fail the moment a night stops replaying
- How to verify: `GRAVEYARD_FRAMETRACE=Logs/trace python tools/dev.py smoke --filter Smoke_A` twice into two folders,
  then diff the files (`FrameTrace.cs` writes one line a frame; the first three columns are the clocks and differ with
  the load, compare from `K` on)
- Related: issue #160, issue #9 (the keeper's late first step, which was a real cause), HOW_IT_WAS_MADE "Later: the night that replays after all"
