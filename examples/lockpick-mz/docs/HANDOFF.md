# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-23
**Branch / commit:** (fill in)
**Engine version:** see `docs/ENGINE.md`

## Where we are
Built 2026-10-23 without RPG Maker MZ: rules and bots (16 Node tests), the MZ glue against stand-ins, smoke against a fake
MZ. Never run in real MZ (HOW_IT_WAS_MADE.md "What is not verified").

## What changed last session
- 

## Current task
- (copy from ROADMAP Now)

## Next step (specific, first action)
- On a machine with RPG Maker MZ: `python tools/dev.py setup --from <a new MZ project>`, then check, test,
  `smoke --query autoplay --until LOCK_OPEN`, and play it from the title. Fix what breaks, in the kit too.

## Open questions / decisions pending
- 

## Known broken or flaky
- Untested proof of concept: never run inside RPG Maker MZ, only against stand-ins of its core scripts.

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
```

## Context a fresh Claude needs
- 
