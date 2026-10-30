# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-26
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
v0.2.0. Vertical slice "One Town Block" done: courier with walk, sprint and animations, five parcels carried one at a time,
a patrol robot with an FSM (patrol, alert, chase, search, return), grid A*, a sight cone drawn as far as it sees, HUD, sounds,
keyboard and gamepad, `?debug` view, `?autoplay` and `?autoplay=reckless` bots, 60 unit tests including the scenario pair.
Bot-verified: the careful bot wins from all 4 robot starts, the reckless one is caught from all 4. Not yet played by a human.

## What changed last session
- 2026-10-26: fixed six bugs from a Fable review (`HOW_IT_WAS_MADE.md` "Later: review fixes"), regression tests in
  `tests/regressions.test.ts`; scenario margins unchanged.
- Before that: built the slice per SOP-01 and SOP-14; fixed the problems screenshots and scenario runs found (`docs/TROUBLESHOOTING.md`).

## Current task
- None. Next decision is the user's: playtest by hand.

## Next step (specific, first action)
- `python tools/dev.py run`, play three runs, then `/playtest-report` with notes on reading the robot (pillar 1) and "one more run" (pillar 3).

## Open questions / decisions pending
- 

## Known broken or flaky
- 

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
python tools/dev.py smoke --query "autoplay&speed=4" --until RUN_WON --fail-on CAUGHT,TIME_UP --timeout 240
python tools/dev.py smoke --query "autoplay=reckless&speed=4" --until CAUGHT --fail-on RUN_WON,TIME_UP --timeout 240
```

## Context a fresh Claude needs
- All rules and AI are in `src/core/` (no three import); change tunables in `src/core/tuning.ts`, then `test` tells you
  whether the careful bot still wins and the reckless one is still caught.
- Debug URL flags: `?debug`, `&god`, `&top`, `&close` / `&close=robot`, `&speed=N`, `&start=N` (robot start).
