# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-26
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
Done as an example: one level with Kenney tiles, coins, flag, parallax background, music and sound effects; player with coyote time and jump buffer; timer, falls, respawn, F1 debug overlay, autoplay bot.
`check`, `test` (38 tests) and `smoke` pass on Godot 4.7.2 with GUT 9.7.1; the bot finishes in 8.52 s with 11/11 coins and 0 falls. Full story: `HOW_IT_WAS_MADE.md`.

## What changed last session
- 2026-10-26 review fixes: the fox stops at the flag (no endless fall, no coins after it), a buffered or repeated tap cuts the jump once, respawn and R snap the camera, the clock starts on the first input, R stops the jingle and faces the fox right, `JumpMath` includes the physics step. Scene tests in `tests/test_player_jump.gd` and `tests/test_run_flow.gd`; details in `HOW_IT_WAS_MADE.md` ("Later: review fixes").
- Earlier: built the game from the scaffolded skeleton, fetched CC0 art, swapped in the Sunny Land fox, made the sound and music with `tools/audio/`.

## Current task
- None. The example is finished on purpose.

## Next step (specific, first action)
- If you extend it: add a platform to `LevelData.PLATFORMS`, run `python tools/dev.py test` (the reachability test checks the gap), then `godot --path . -- --autoplay`.

## Open questions / decisions pending
- 

## Known broken or flaky
- 

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
```

## Context a fresh Claude needs
- GUT is not committed: copy a GUT 9.x `addons/gut/` in before `test`.
- The level is built in code from `LevelData`; `scenes/main.tscn` is one node on purpose.
