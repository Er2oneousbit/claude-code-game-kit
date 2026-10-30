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
- Possible next step: animated sprites for the wizard and ghosts from a generation service (`tools/art/pixellab.py`),
  palette-matched to the Kenney tiles; a paid generation needs the user's go-ahead.

## Current task
- None. Next decision is the user's: playtest by hand.

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
