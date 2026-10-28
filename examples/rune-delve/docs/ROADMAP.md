# Roadmap

> Now is capped at 3 items (SOP-08); one at a time is best. Finishing beats starting. Anything new goes to the Parking lot.
> Claude reads the **Now** section at session start.

## Now (max 3 items)
- [x] **Slice: First Delve**  | Done when: three rooms, bolt/ward/dash, orcs that see and hear, a warden, gates, restart; check/test/smoke and the bot pair pass; a packaged build runs a delve  | Timebox: 1 session

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
| M0 Toy (v0.1.0) | Core mechanic playable | Done (2026-10-22) |
| M1 Vertical slice (v0.2.0) | One polished loop with art, audio, UI | Built and bot-verified; human playtest pending (2026-10-22) |
| M2 Alpha | Every MVP system in and playable | |
| M3 Beta (content complete) | All MVP content in, no known crash | |
| M4 Release candidate (v1.0.0-rc.N, then v1.0.0) | `/release-check` green | |

## Done (recent, newest first)
- 2026-10-26: review fixes (a ward stops one swing, a hit always wakes an orc, swing clip timed to the hit, warden off grunt tiles, dash length and dodge, own-bolt collision, bot room filter); 3 smoke tests; pair now weaver 65, masher 55 of 80, clears 3/8 against 0/8
- 2026-10-22: v0.2.0, slice built: content from a headless script, GAS spells in C++, AI Perception orcs on a runtime NavMesh, bot pair over 8 seeds, 5 core + 2 smoke tests, packaged build
- 2026-10-22: Project scaffolded

## Budget and cost log (SOP-12)
| Date | Job | Model and effort | Time | Cost or % of weekly limit | Result |
|---|---|---|---|---|---|
| 2026-10-22 | Plan and build: GDD, slice, assets, ADRs, content script, game, tests, package | Claude Opus 5.5, session default effort | not measured (one session interleaved with kit changes) | not measured | slice built |
