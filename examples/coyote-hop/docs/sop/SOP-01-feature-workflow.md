# SOP-01: Feature Workflow

## Goal
Ship small, working slices of the game with a trail a stranger can follow.

## Steps
1. **Frame it.** Write the feature in one sentence plus "done when" (observable behavior). Confirm it is in ROADMAP Now.
   If it is not, add it to the Parking lot and stop. See SOP-08.
2. **Pillar check.** Which GDD pillar does it serve? None means Parking lot.
3. **Pseudocode and plan.** High-level pseudocode, modules touched, data needed, risks. Short why. For anything that changes
   architecture, write an ADR (`/adr`).
4. **Prototype.** Ugliest thing that proves the idea works in the running game. Gray boxes for levels, placeholder pixel-art sprites (`tools/art/pixel_sprite.py`, never dots) for characters and key objects: art comes
   after the loop is fun (F4). Mark with `PROTOTYPE:`. Hardcode first.
5. **Make it tunable.** Move numbers to data or constants. Add a debug toggle or log channel.
6. **Refine.** Split into modules, add error handling, remove prototype hacks. One change at a time, run `check` after each.
7. **Test.** Unit tests for pure logic, `smoke` for boot, a manual playtest note for feel.
8. **Document.** Update `ARCHITECTURE.md` (system table), `GDD.md` if design shifted, `TROUBLESHOOTING.md` if you hit a trap.
9. **Close out.** Tick the ROADMAP item, update HANDOFF.

## Done when
- The behavior in "done when" is visible in the running game.
- `check` and `test` pass. `smoke` passes if boot or scenes/levels changed.
- No `PROTOTYPE:` markers left unless the roadmap says the prototype phase is the task.
- Docs reflect reality.

## Common mistakes
- Polishing before the feature is fun. Prototype first.
- Hiding magic numbers in code. Tune from data.
- Adding "just one more" sub-feature mid-task. Park it.
- Skipping the pillar check, then wondering why the game has no identity.
