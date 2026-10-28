# SOP-08: Scope Control

## Goal
Finish games. Ideas are cheap, shipped games are rare.

## Mechanics
- **Three pillars** in the GDD. Features that serve none get parked.
- **Parking lot** in ROADMAP. New idea appears: add one line there, return to the current task. No debate, no code.
- **Now column capped at 3.** Starting a fourth means finishing or explicitly dropping one.
- **Timeboxes.** Every Now item has a box (sessions or hours). Blowing the box triggers a decision: cut scope, extend once with a reason, or park.
- **Scope tiers** (Toy, Vertical slice, MVP / Release, Stretch) in the GDD. Do not start a tier until the previous one is done.
- **Vertical slice before content.** Prove the loop is fun and the pipeline works before making 20 levels.
- **No deadlines.** Milestones are defined by scope and exit criteria, and progress is counted in items and content.

## Tiers
The `Current tier:` line in `docs/GDD.md` is what every scope check reads. Move it with `/next-tier` when the tier's
"Done means" is met (the skill checks the evidence: a human playtest, the slice's "Done when", the assumptions tested).
A tier line that never moves makes Claude reject work that is already in scope, so move it as soon as the game does.

| Current tier | Scope comes from | A new idea that serves a pillar | Pushed back |
|---|---|---|---|
| Toy | The toy row of the GDD | Parking lot | Anything beyond the core mechanic |
| Vertical slice | `docs/VERTICAL_SLICE.md` | Parking lot | Anything the slice brief leaves out |
| MVP / Release (production) | `docs/PRODUCTION.md` Backlog and milestones, the GDD Content list | Backlog, with a size (S, M, L); the owner decides which milestone, or Stretch | Only ideas outside the pillars, or in GDD "Out of scope" |

Production keeps the fun loop: every milestone ends with a playtest, and a system that stops being fun goes "back to
prototyping" (a toy again) while the rest of the game carries on.

## Hyperfixation-friendly practice
- Capture the cool tangent in the Parking lot with one line of "why it excites me". It is saved, not lost.
- If interest has moved on from the current project, record the state in HANDOFF in a way that lets you pick it back up cold:
  what works, what is next, what is half-done. Mothballing cleanly beats abandoning messily.
- Prefer finishing a small complete thing over an ambitious unfinished one. A shipped jam-size game counts.

## `/gdd-sync` ritual
At each milestone: reconcile GDD against what exists, move cut features to "Out of scope", update content counts, update risks.
When the current tier looks done, run `/next-tier`.

## Warning signs
- Adding systems before the core loop is fun.
- More than 3 items in Now.
- Rewriting the engine layer instead of making levels.
- Content list growing faster than completed content.

## Done when
- ROADMAP Now matches what you are actually doing.
- The GDD's `Current tier:` matches where the game really is.
