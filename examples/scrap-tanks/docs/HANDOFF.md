# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-26
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
v0.2.0. Vertical slice "Scrapyard, three waves" done: tank controls and a free turret, raiders on a behavior tree
(RETREAT, COVER, FIRE, FLANK) shown over each raider, shells stopped by cover, scrap repairs, three waves, HUD, five
sounds, keyboard, mouse and gamepad, `-- --debug-ai` overlay, autoplay bots, 46 test cases including the scenario pair.
Bot-verified: fighting from cover wins 25 of 40 seeds, charging 11 of 40. Not yet played by a human.

## What changed last session
- Built the slice per SOP-01 and SOP-14; the scenario pair refuted pillar 1 three times before it held (`docs/TROUBLESHOOTING.md`).
- 2026-10-26 review fixes (`HOW_IT_WAS_MADE.md` "Later: review fixes"): spot pickers skip nav islands, a tank with no
  path drives straight at its goal, cover hit first stops a shell, `--seed` rejects negatives. Smoke seed is now 7.

## Current task
- None. Next decision is the owner's: playtest by hand.

## Next step (specific, first action)
- `python tools/dev.py run`, play three runs, then `/playtest-report`: can you tell what each raider will do (pillar 2), does cover feel like it matters (pillar 1).

## Open questions / decisions pending
- 

## Known broken or flaky
- Sight is checked center to center: a 1.9 m tank with its center hidden is not seen even when its edge shows (known limit).

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
python tools/dev.py smoke --frames 30000 --timeout 900 --until RUN_WON --fail-on PLAYER_DESTROYED -- --autoplay skilled --seed 7
python tools/dev.py smoke --frames 30000 --timeout 900 --until PLAYER_DESTROYED --fail-on RUN_WON -- --autoplay reckless --seed 7
python tools/make_sprites.py         # after changing a model or a scale (needs the bpy module, see the script)
```

## Context a fresh Claude needs
- Rules, AI and bots are engine-free in `src/core/`; numbers in `src/core/Tuning.hpp`. After a change, `test` says whether
  cover still beats charging (the pillar check runs 80 fights in a few seconds).
- Set `VCPKG_ROOT` and put CMake on PATH (docs/ENGINE.md). The first configure builds SDL2_image/ttf/mixer (about 2 minutes).
