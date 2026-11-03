# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-21
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
v0.2.0. Vertical slice "One Night" done: the scene is built by `SceneBuilder.Build`, the level and NavMesh at runtime,
ghosts on a tested FSM (one per patrol loop plus the difficulty's extras), lantern stealth, souls, gate, saves with a migration, HUD, sounds, keyboard and gamepad.
Every night after the first is a generated yard (`Assets/Scripts/Core/LevelGenerator.cs`, SOP-17; HOW_IT_WAS_MADE "Later: a new graveyard
every night"). 112 EditMode tests (a 250-seed property test among them); 21 PlayMode smoke tests (boot, no way out of the yard and the gate shutting, the keeper's lantern and legs, the bot trio on
the hand-made yard and on 8 generated nights, the NavMesh check, a yard from above, six review-fix regressions).
Review fixes 2026-10-26 (HOW_IT_WAS_MADE "Later: review fixes"). `Smoke_D`'s careful >= always-dark sits at the 104
cap; its one failure was a night starting a frame late, fixed 2026-11-02 (issue #9, "Later: a night that started a
frame late"). The built player replays a test night. Played once by the user (docs/PLAYTEST_LOG.md).

## What changed last session
- Built the slice; the bot trio refuted pillar 1 several times before it held, weakly (`docs/VERTICAL_SLICE.md`).

## Current task
- None. Next: the user plays the fixed build (difficulty light, lantern in hand, gate shutting on a catch),
  then someone who is not the user plays it (pillars 2 and 3).

## Next step (specific, first action)
- `python tools/dev.py run` (opens the editor; press Play), three nights, then `/playtest-report`: is lighting up ever worth it?

## Open questions / decisions pending
- 

## Known broken or flaky
- Two ghosts close together can part by a millimeter between runs: always-lit's hand-made catches read 12 or 14.
  Careful and always-dark replay exactly since issue #9, so `Smoke_D` (both at the 104 cap) no longer flakes.
- Generated nights are easier than the hand-made yard (dark bot escapes 6/8 against 2/8): a playtest question.
- A low rock the ghosts' NavMesh climbs (0.75 m) blocks the keeper (CharacterController 0.3 m); the fix moved the balance and was reverted.
- Built with Mono only; IL2CPP not built or compared.

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
python tools/dev.py smoke                      # boot + bot trio, about 2 minutes
python tools/dev.py exec SceneBuilder.Build    # after adding a model or changing the version
python tools/dev.py exec SceneBuilder.ResetTuning   # after changing a default in Core/GameTuning.cs
python tools/dev.py build && Build/game.exe -batchmode -nographics -- --autoplay careful --handmade --seed 6 --fixed-fps
```

## Context a fresh Claude needs
- The game reads tunables from `Assets/Config/SO_GraveyardSetup.asset`. Changing a C# default does nothing until
  `SceneBuilder.ResetTuning` runs; EditMode tests read the asset too, so tests and game cannot disagree.
- Close the Unity editor before any batchmode command.
