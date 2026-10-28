# Roadmap

> Now is capped at 3 items (SOP-08); one at a time is best. Finishing beats starting. Anything new goes to the Parking lot.
> Claude reads the **Now** section at session start.

## Now (max 3 items)
- [x] **Slice: One Town Block**  | Done when: start, carry 5 parcels, win, caught or time up, restart; check/test/smoke and both scenario runs pass  | Timebox: 1 session

## Next
- [ ] 

## Later
- [ ] 

## Parking lot (ideas, no commitment)
- 

## Milestones
Scope, not dates. `/next-tier` moves the game from one tier to the next; after the slice, `docs/PRODUCTION.md` holds the
detail.
| Milestone | Definition of done | Status |
|---|---|---|
| M0 Toy (v0.1.0) | Core mechanic playable | Done (2026-10-21) |
| M1 Vertical slice (v0.2.0) | One polished loop with art, audio, UI | Built and bot-verified; human playtest pending (2026-10-21) |
| M2 Alpha | Every MVP system in and playable | |
| M3 Beta (content complete) | All MVP content in, no known crash | |
| M4 Release candidate (v1.0.0-rc.N, then v1.0.0) | `/release-check` green | |

## Done (recent, newest first)
- 2026-10-26: review fixes (Fable): search always ends, chase stuck check, debug path line draws, exact 90 s clock with no last-step win, restart clears held keys, GDD pillar 1 matches the catch rule; 60 tests
- 2026-10-21: v0.2.0, slice built: courier, parcels, FSM robot with A* and a drawn sight cone, HUD, sound, gamepad, debug view, scenario pair, 53 tests
- 2026-10-21: Project scaffolded

## Budget and cost log (SOP-12)
| Date | Job | Model and effort | Time | Cost or % of weekly limit | Result |
|---|---|---|---|---|---|
| 2026-10-21 | Plan: GDD identity, concept lock, slice brief, assets | Claude Opus 5.5, session default effort | not measured (built in one long session interleaved with kit changes; log real numbers on your own runs) | not measured (kit example run inside a longer session) | docs filled, 6 asset rows |
