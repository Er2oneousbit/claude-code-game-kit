# Roadmap

> Now is capped at 3 items (SOP-08); one at a time is best. Finishing beats starting. Anything new goes to the Parking lot.
> Claude reads the **Now** section at session start.

## Now (max 3 items)
- [ ] **First playtest of the toy**  | Done when: the user has played a few races and the notes are in PLAYTEST_LOG.md (`/playtest-report`)  | Timebox: 1 session

## Next
- [ ] Fix the top playtest item, one change at a time
- [ ] Use the drift (the bots never drift; check whether a drifting player gains too much)

## Later
- [ ] More change types (a ramp, a moving hazard); more items (GDD vertical slice)
- [ ] Unlocks for 1st place, menus, music (GDD MVP)

## Parking lot (ideas, no commitment)
- A minimap that shows where the next change is
- Sound: engine hum, zap, boost whoosh (`tools/audio/sfx_synth.py`)

## Milestones
Scope, not dates. `/next-tier` moves the game from one tier to the next; after the slice, `docs/PRODUCTION.md` holds the
detail.
| Milestone | Definition of done | Status |
|---|---|---|
| M0 Toy (v0.1.0) | Core mechanic playable | built, awaiting playtest (2026-10-28) |
| M1 Vertical slice (v0.2.0) | One polished loop with art, audio, UI | |
| M2 Alpha | Every MVP system in and playable | |
| M3 Beta (content complete) | All MVP content in, no known crash | |
| M4 Release candidate (v1.0.0-rc.N, then v1.0.0) | `/release-check` green | |

## Done (recent, newest first)
- 2026-10-28: Added to the kit as its Bevy example (`examples/crimson-nebula`), with HOW_IT_WAS_MADE.md and a GIF
- 2026-10-28: Toy playable: one neon loop, you vs 3 bots, 3 laps, lane closure on lap 2, any change on lap 3, boost item; 40 tests including the bot pair (reading wins 20 of 20 seeds)
- 2026-10-28: Project scaffolded

## Budget and cost log (SOP-12)
| Date | Job | Model and effort | Time | Cost or % of weekly limit | Result |
|---|---|---|---|---|---|
| 2026-10-28 | Toy build (logic, bots, view) | Claude Opus 5.5 | one session | not measured | toy playable |
