# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-11-05
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
v0.2.0. Vertical slice "First Delve" done: content made by `tools/unreal/build_content.py`, rooms built at runtime,
GAS spells (bolt, ward, dash) in C++, orcs with AI Perception on a runtime NavMesh, a warden, gates, HUD, sounds,
keyboard/mouse and gamepad. 5 core test groups, 3 smoke tests (boot, the review regressions, the bot pair over 8 seeds).
Packaged build verified (2026-10-26, after the review fixes).
Not yet played by a human.

## What changed last session
- `-nullrhi` replays match rendered runs (#8): the bolt is off the NavMesh, under `-fixedfps` the game mode finishes
  every pending NavMesh tile before the actors tick (`ARDGameMode::FinishNavBuild`), and an orc's movement ticks after
  its path following (it braked for a frame on a random frame). `-tracedelve` logs one line per
  frame; `tools/unreal/replay_check.py` runs a seed both ways and diffs them. Two `smoke` runs now print the same 16
  delves. On its own this fix left the pair one under both thresholds (weaver 61, masher 52, clears 2/8); together
  with #140 (an open gate joins two rooms for sight and hearing, so a doorway shot wakes the whole room) the pair
  measures weaver 73, masher 47 of 80, clears 6/8 against 0/8 and passes

## Current task
- None. Next decision is the user's: playtest by hand.

## Next step (specific, first action)
- `python tools/dev.py run`, press Play, three delves, then `/playtest-report`: is the 0.45 s ward window fair by eye?

## Open questions / decisions pending
- 

## Known broken or flaky
- Nothing known. The ward window (0.45 s) is still tuned by bots only: is it fair by eye? A human playtest decides (#7).

## Commands that matter right now
```
python tools/dev.py check                                 # first: the editor cannot load the project until it compiles
python tools/dev.py exec tools/unreal/build_content.py   # then, and after adding a model or sound
python tools/dev.py test
python tools/dev.py smoke                                 # boot, regressions, 16 bot delves, about 3.5 minutes
python tools/dev.py package && Packaged/Windows/RuneDelve.exe -autoplay=weaver -seed=6 -fixedfps -quitatend
python tools/unreal/replay_check.py --seed 6             # the same seed rendered and under -nullrhi, diffed per frame
```

## Context a fresh Claude needs
- Every number is in `Config/DefaultGame.ini` (`URDTuning` has no C++ defaults); tests read the same values.
- `Content/` is generated: never edit it, re-run `tools/unreal/build_content.py`.
- Close any Unreal editor on this engine before `check` (Live Coding blocks command-line builds).
- 
