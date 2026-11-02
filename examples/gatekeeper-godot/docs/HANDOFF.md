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
- 2 review findings from 2026-10-26 are not fixed yet (the web twin has its fixes): the exit leak and the exported
  build's developer hint, both in KNOWN_ISSUES at the kit's root.
  Fixed 2026-11-02: the double intro and the model reload on "Start over" (#1), the line typed while the guard thinks
  (#2), both in `tests/test_main_flow.gd`; model errors told apart from timeouts, with a hand-over to the scripted
  guard and bounded history calls (#3, `tests/test_guard_brain.gd` with a stand-in chat; the load path and
  `stop_generation()` on a restart still want a run with the real model); the voice cache written before the reply
  was checked (#4, `tests/test_guard_voice.gd`); the checks that could not fail (#5: `--llm --autoplay` exits 1 with
  MODEL_MISSING on the scripted guard, the rule test snapshots, the eval's `tally()` counts model labels only; the
  eval itself and the `--llm` pass still want a run with the real model).
- Scripted `--autoplay` ends with `ERROR: 1 resources still in use at exit` (exit 0; no fix found; `dev.py smoke` unaffected).

## Commands that matter right now
```
python tools/dev.py check
python tools/dev.py test
```

## Context a fresh Claude needs
- 
