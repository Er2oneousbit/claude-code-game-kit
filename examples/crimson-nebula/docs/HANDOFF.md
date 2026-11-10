# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-11-10 (kit 0.14.3 upgrade: the shell)
**Branch / commit:** kept in the kit repo as `examples/crimson-nebula` (kit 0.14.3)
**Engine version:** see `docs/ENGINE.md` (Bevy 0.20.0, Rust 1.99.1)

## Where we are
The toy is playable (M0): one neon loop, you vs Vex (reader), Nova (late) and Rook (ignorer), 3 laps, a lane closes on
lap 2, any change on lap 3, item boxes give a boost. Waiting for the user's first playtest.

## What changed last session
- Kit 0.14.3: the game boots to the kit's shell (`src/shell/`, kit files): title, menu, settings with rebinding,
  Esc pauses. The race ticks only in Play (`GameActive`); input comes through the kit's `Intent` (W/S/A/D or
  d-pad and stick as `move_*`, Space/A held = drift, J/X = item, any of jump/attack/interact on the results = race
  again, also under `--autoplay`); `src/game/mod.rs` maps it. Lost on the way: analog triggers and stick (the kit's
  `Intent.dir` is digital), Shift as drift, arrows for driving (arrows are the menu keys now). A bump rattles the
  chase camera (`ScreenShake`, off with reduce motion); the closing and opening tells take the colour-blind palette.
- Race logic in `src/logic/` (track, kart, race, bots, tuning) with 36 unit tests and 4 headless race tests.
- 3D view in `src/game/present.rs`: shapes only, neon via emissive + bloom, chase camera, HUD, results, a press restarts.
- Tuning found by bot runs: barriers taper in and zap (speed x0.45), shortcuts peel off the loop (no 90 degree
  corners), bots brake for bends and pass each other. Reading the changes wins 20 of 20 seeds by 0.6 to 1.9 s.
- Became the kit's Bevy example: README, `HOW_IT_WAS_MADE.md`, `docs/crimson-nebula.gif`, ASSET_LOG row for Bevy's
  built-in font. Checked before it landed: `check`, 40 tests, `smoke --until RACE_OVER`, `doctor`, `publish_check`.

## Current task
- First playtest of the toy (ROADMAP Now).

## Next step (specific, first action)
- The user plays (`python tools/dev.py run`), writes notes; then `/playtest-report` and fix the top item first.

## Open questions / decisions pending
- Is a zap (speed x0.45) the right sting for missing a closure, or should it hurt more?
- Is a 2 s warning readable from the chase camera at speed?

## Known broken or flaky
- Bots never drift; the player can, untested for balance.
- No sound yet (on purpose: crude first build).

## Commands that matter right now
```
python tools/dev.py run                                   # play (W/S or stick, A/D, Space drift, J boost, Esc pause)
python tools/dev.py test
python tools/dev.py smoke --frames 9000 --until RACE_OVER -- --autoplay reader --seed 3
cargo test --lib balance_report -- --ignored --nocapture  # how much reading the changes gains, per seed
```

## Context a fresh Claude needs
- Bevy 0.20 APIs differ from older examples: grep `~/.cargo/registry/src/*/bevy_*-0.20.0/` before using one.
- The first Bevy build takes 5 to 15 minutes. Several Bevy projects on one machine can share one `CARGO_TARGET_DIR`
  so Bevy compiles once.
