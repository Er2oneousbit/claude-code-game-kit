---
name: next-tier
description: Move the game to its next scope tier (Toy -> Vertical slice -> MVP / Release) once the current tier is done. Use when the user says the toy or slice is done, "it's fun, let's develop it", "greenlight", "next tier", "move on to production", or when Claude keeps pushing back with "that is not part of the toy/slice" on work the owner wants. Checks the tier's evidence, then updates the GDD tier line, ROADMAP and, at the greenlight, writes docs/PRODUCTION.md.
---

# Next tier

Follow `docs/sop/SOP-08-scope-control.md` "Tiers". The `Current tier:` line in `docs/GDD.md` is what every scope
check in this project reads, so it must move when the game does. No dates anywhere: tiers and milestones are scope.

1. **Read** `docs/GDD.md` (Scope tiers, Current tier, Assumptions to test, Content list), `docs/ROADMAP.md`,
   `docs/PLAYTEST_LOG.md`, and for the slice `docs/VERTICAL_SLICE.md`.
2. **Check the current tier's evidence.** For each item give **MET**, **NOT MET** or **UNKNOWN** with the file or
   command that shows it. Never MET from assumption.
   | Leaving | Evidence |
   |---|---|
   | Toy | The core mechanic runs (`python tools/dev.py check`, `test`, `smoke` pass this session); a human played it and a PLAYTEST_LOG entry says they wanted to keep going (the tier's "Done means") |
   | Vertical slice | VERTICAL_SLICE.md "Done when" holds in the running game; a PLAYTEST_LOG entry on the slice; every GDD "Assumptions to test" row has a result (held, failed, changed); the pillar's bot or scenario check passes if the game has one; the GDD Content list has target counts |
   | MVP / Release | Not this skill: run `/release-check` |
3. **Report** the table, then one line: ready, or what is missing. A missing playtest is the usual gap: offer
   `/playtest-report` once the owner has played. The owner may move on anyway: then record "Moved on without: <items>,
   reason: <their words>" in the ROADMAP Done line. It is their game; the gate advises, it does not lock.
4. **On a yes, update the docs:**
   - `docs/GDD.md`: set `Current tier: **<next tier>**`, and `> Last reviewed:` to today.
   - `docs/ROADMAP.md`: mark the milestone row done, add a Done line ("<date>: <tier> done, now <next tier>"), and move
     Parking lot items that now fit the new tier into Next (ask about any that are unclear; ideas outside the pillars
     stay parked).
   - **Toy -> Vertical slice:** if `docs/VERTICAL_SLICE.md` is still the blank template, offer to fill it from the GDD
     (systems marked "yes" for the slice, the assumptions to test).
   - **Vertical slice -> MVP / Release (the greenlight):** fill `docs/PRODUCTION.md` from the GDD: the backlog (every
     system and feature still to build, each with its pillar and a size S, M or L), content progress (one row per
     Content list line), the risks, an empty cut list. Put the first Alpha items into ROADMAP Now (max 3).
5. **Say what changes** in two or three lines: in production, ideas that serve a pillar get a size and go to the
   PRODUCTION.md backlog instead of the Parking lot; only work outside the pillars or in GDD "Out of scope" is pushed
   back; each milestone still ends with a playtest.

Rules:
- One tier per run. Never skip a tier without the owner saying so (some games stay a toy on purpose: record that in
  the GDD tier line instead).
- Going back is allowed: if a system is not fun in production, mark it "back to prototyping" in PRODUCTION.md and
  treat that one system as a toy until it is.
- No deadlines, target dates or "days left". Progress is counted in items and content, never time.
