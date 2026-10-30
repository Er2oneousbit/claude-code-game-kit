# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-22
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
v0.2.0. Vertical slice "First Delve" done: content made by `tools/unreal/build_content.py`, rooms built at runtime,
GAS spells (bolt, ward, dash) in C++, orcs with AI Perception on a runtime NavMesh, a warden, gates, HUD, sounds,
keyboard/mouse and gamepad. 5 core test groups, 3 smoke tests (boot, the review regressions, the bot pair over 8 seeds).
Packaged build verified (2026-10-26, after the review fixes).
Not yet played by a human.

## What changed last session
- 

## Current task
- None. Next decision is the user's: playtest by hand.

## Next step (specific, first action)
- `python tools/dev.py run`, press Play, three delves, then `/playtest-report`: is the 0.45 s ward window fair by eye?

## Open questions / decisions pending
- 

## Known broken or flaky
- Balance at its limit: weaver clears 3/8 against the masher's 0/8, and the pair test passes exactly on its thresholds. Tuning on hold.
- `-quitatend` exits 0 even when the mage dies (Unreal 5.8 needs a forced exit for a non-zero code).
- `-nullrhi` replays differ from rendered runs; cause unknown (`docs/TROUBLESHOOTING.md`).

## Commands that matter right now
```
python tools/dev.py check                                 # first: the editor cannot load the project until it compiles
python tools/dev.py exec tools/unreal/build_content.py   # then, and after adding a model or sound
python tools/dev.py test
python tools/dev.py smoke                                 # boot, regressions, 16 bot delves, about 3.5 minutes
python tools/dev.py package && Packaged/Windows/RuneDelve.exe -autoplay=weaver -seed=6 -fixedfps -quitatend
```

## Context a fresh Claude needs
- Every number is in `Config/DefaultGame.ini` (`URDTuning` has no C++ defaults); tests read the same values.
- `Content/` is generated: never edit it, re-run `tools/unreal/build_content.py`.
- Close any Unreal editor on this engine before `check` (Live Coding blocks command-line builds).
- 
