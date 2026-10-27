---
name: new-feature
description: Build a new gameplay feature or system following the prototype-first workflow. Use when the user asks to add, implement, or build something new (mechanic, enemy, UI screen, system). Enforces pillar check, pseudocode-first, tunables, tests, docs.
---

# New feature

Follow `docs/sop/SOP-01-feature-workflow.md`. Condensed:

1. **Frame:** restate the feature in one sentence and a "done when". Check ROADMAP Now. Not there? Offer to park it, ask if they want to swap.
2. **Pillar check:** name the GDD pillar it serves. If none, it goes to the ROADMAP Parking lot (SOP-01, SOP-08) unless the owner explicitly overrides; record the override in ROADMAP.
3. **Pseudocode and plan:** high-level pseudocode, modules and files touched, data needed, risks, and a short why. Wait for a nod unless the request was already precise. Architecture-level change: also draft an ADR (`/adr`).
4. **Engine facts:** read `docs/ENGINE.md` for conventions and gotchas. Verify any engine API you plan to use against the installed version or docs, label unverified items.
5. **Prototype:** smallest ugly version that proves it. Mark `PROTOTYPE:`. Run `check`.
6. **Tunables and debug:** move numbers to data or constants. Add a debug toggle or log channel.
7. **Refine:** modularize, add error handling, remove prototype hacks. One change at a time, `check` after each.
8. **Test:** unit tests for engine-free logic (`test`), `smoke` if boot or content loading changed.
9. **Docs:** update `ARCHITECTURE.md` system table, `GDD.md` if design moved.
10. **Close out:** tick the ROADMAP item, add a `docs/TROUBLESHOOTING.md` entry if a trap cost real time, and note anything the owner must try by hand in the running game.
11. **Report:** what was built, how to see it in the game, what is tunable where, what is left. Suggest `/end-session` if the session is wrapping up.

Style: file headers and footers per `docs/STYLE.md`. Comments for 6-months-later you.
New ideas that pop up mid-task go to the Parking lot, not into this feature.
