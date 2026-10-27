# Handoff

> Rewritten at the end of every session by `/end-session`. Read first by `/start-session`.
> Keep under ~60 lines. It is a baton, not a diary.

**Last updated:** 2026-10-21
**Branch / commit:** main (example in the kit repo)
**Engine version:** see `docs/ENGINE.md`

## Where we are
Done as a kit example: talk-past-the-guard with a local language model (two constrained calls per turn) and a scripted fallback. Verified with the real model; see HOW_IT_WAS_MADE.md.

## What changed last session
- 

## Current task
- None: finished example. Next is a human playtest.

## Next step (specific, first action)
- Play it with the AI guard and note odd lines; add real bad outputs to tests/fixtures/recorded.json.

## Open questions / decisions pending
- 

## Known broken or flaky
- 12 review findings from 2026-10-26 are not fixed yet (the web twin has its fixes): the full list is in KNOWN_ISSUES at the kit's root. The main ones:
  picking the scripted guard during the model load doubles the intro; "Start over" reloads the 1.1 GB model;
  a line typed while the guard thinks is lost; engine errors show as "too slow" with no hand-over; one bad voice reply
  poisons the cache; `--llm --autoplay` passes on the fallback; one rule test cannot fail.
- Scripted `--autoplay` ends with `ERROR: 1 resources still in use at exit` (exit 0; no fix found; `dev.py smoke` unaffected).

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
```

## Context a fresh Claude needs
- 
