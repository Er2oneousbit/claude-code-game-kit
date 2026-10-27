---
name: gdd-sync
description: Reconcile the GDD, ROADMAP, and ARCHITECTURE docs with what the game actually is right now. Use at milestones, when scope feels fuzzy, when the user says "update the docs" or feels scope creep. Also the scope-control ritual from SOP-08.
---

# GDD sync

Follow `docs/sop/SOP-08-scope-control.md`.

1. Read `docs/GDD.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`. Skim the code layout for what exists (use an Explore-style search or the `design-critic` subagent for a read-only review).
2. Produce a **delta report**:
   - Built but not in the GDD
   - In the GDD but not built (and not on the roadmap)
   - GDD statements now contradicted by the game
   - ARCHITECTURE rows that are stale
3. Pillar audit: for each Now/Next item and each built system, which pillar does it serve? List the orphans.
4. Scope audit: current tier, content counts vs MVP list, Now column size (cap 3), timeboxes blown.
5. Propose edits as a short list. Apply them only after the user agrees (or if they asked you to just do it). After applying, set `> Last reviewed:` in `docs/GDD.md` and `docs/ARCHITECTURE.md` to today.
6. Move cut features to GDD "Out of scope" with a one-line reason. Move loose ideas to the ROADMAP Parking lot.

Tone: honest, not harsh. Point out creep plainly.
