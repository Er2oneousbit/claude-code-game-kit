# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-11-10
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
v0.2.0. Vertical slice "Scrapyard, three waves" done: tank controls and a free turret, raiders on a behavior tree
(RETREAT, which only the heavy reaches, COVER, FIRE, FLANK) shown over each raider, shells stopped by cover, scrap repairs, three waves, HUD, five
sounds, keyboard, mouse and gamepad, `-- --debug-ai` overlay, autoplay bots, 110 test cases (72 of them the kit's)
including the scenario pair.
Bot-verified: fighting from cover wins 30 of 40 seeds, charging 13 of 40. Not yet played by a human.

## What changed last session
- 2026-11-10 (kit 0.14.4): crash files (`smoke --drive crash`), F8 bug reports in debug builds, the pseudo locale
  (`smoke --drive pseudo --locale pseudo`: 21 screens pass), the juice demo on the debug main menu, data/ copied next
  to the exe on every build. Fire now honours the motor-access settings: a tap while reloading is buffered
  (0.12 s times Timing windows) and Hold actions toggle turns fire into auto-fire. The left stick and right trigger
  go through the shell's analog input (the player's deadzone and invert_y); `shell_->stick()` returns the kit's
  `core::analog::Vec2`, and `Game::read_controls` reads its x and y (`core::Vec2` stays the game's, `Math.hpp`).
  The run's seed is in crash files.
  110 test cases. The HUD (SDL3_ttf, English) is outside the pseudo check, which reads the shell's labels only.
- 2026-11-10 (kit 0.14.3): the game now runs inside the kit's shell (title, menus, settings, pause with "What now?",
  subtitles and captions; `smoke --drive menus` and `tools/access/sweep.py` pass). Escape and Start pause instead of
  quitting or restarting; R and the pad's Back restart; HUD and message panel moved for the shell's hint and
  subtitles. `HOW_IT_WAS_MADE.md` and the README gif still show the layout from before the shell.
- Built the slice per SOP-01 and SOP-14; the scenario pair refuted pillar 1 three times before it held (`docs/TROUBLESHOOTING.md`).
- 2026-10-26 review fixes (`HOW_IT_WAS_MADE.md` "Later: review fixes"): spot pickers skip nav islands, a tank with no
  path drives straight at its goal, cover hit first stops a shell, `--seed` rejects negatives. Smoke seed is now 7.

## Current task
- None. Next decision is the user's: playtest by hand.

## Next step (specific, first action)
- `python tools/dev.py run`, play three runs, then `/playtest-report`: can you tell what each raider will do (pillar 2), does cover feel like it matters (pillar 1).

## Open questions / decisions pending
- 

## Known broken or flaky
- Hiding spots are still judged by one line to the spot's center (with a 0.35 m margin); sight itself counts hull edges since #11.

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
- Set `VCPKG_ROOT` and put CMake on PATH (docs/ENGINE.md). The first configure builds SDL3_image/ttf/mixer (about 2 minutes).
