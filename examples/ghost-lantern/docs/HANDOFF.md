# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-21
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
Vertical slice "Three Dark Rooms" done: lantern with oil, three utility-AI ghosts (chase, flee, wander) on A* with separation,
key chest, exit, HUD, `?debug` view with a live score table, `?autoplay` and `?autoplay=dark` scenario bots, 40 unit tests.
Bot-verified: escapes on 6/6 seeds with the lantern, caught on 6/6 without it. Not yet played by a human.

## What changed last session
- Built the slice per SOP-01 and SOP-14; fixed four AI and tuning problems the scenario runs and screenshots found (`docs/TROUBLESHOOTING.md`).
- 2026-10-23: the Kenney sounds became ElevenLabs sounds plus a haunted-house ambience loop (HOW_IT_WAS_MADE).
- 2026-10-24: planned, not started: the wizard and ghosts as animated PixelLab sprites (`tools/art/pixellab.py`). One 16 px
  test wizard exists outside the repo: clean, but its black outline and palette do not match the Kenney tiles. Next: a `--palette` option (the Kenney sheet as color
  reference, no outline), then a retake. **Every generation waits for the owner's yes.**

## Current task
- None. Next decision is the owner's: playtest by hand.

## Next step (specific, first action)
- `python tools/dev.py run`, play three runs, then `/playtest-report` with notes on readability (pillar 1) and "one more run" (pillar 3).

## Open questions / decisions pending
- 

## Known broken or flaky
- 

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
python tools/dev.py smoke --query autoplay --until ESCAPED --fail-on CAUGHT
python tools/dev.py smoke --query autoplay=dark --until CAUGHT
```

## Context a fresh Claude needs
- 
