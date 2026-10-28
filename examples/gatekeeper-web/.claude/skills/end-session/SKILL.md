---
name: end-session
description: Wrap up a work session. Use when the user says they are done, wants to switch tasks, is about to /clear, or asks for a handoff. Verifies checks pass, updates ROADMAP and HANDOFF, and flags uncommitted work.
---

# End session

1. Run `python tools/dev.py check` and `python tools/dev.py test`. Run `smoke` too if boot or scenes/levels changed. Record results honestly, including failures. Exit 2 "nothing ran" (no tests yet) is a gap to note in HANDOFF, not a pass.
2. `git status --short` and `git diff --stat`. List uncommitted work. Do not commit unless asked.
3. Update `docs/ROADMAP.md`: tick finished items, move new ideas into the Parking lot, add a line to Done (newest first).
   In production (GDD tier MVP / Release), also update the `docs/PRODUCTION.md` Backlog statuses and Content progress,
   and put new pillar-serving ideas in its Backlog with a size. If the current tier's "Done means" now looks met, say so
   and suggest `/next-tier`.
4. Rewrite `docs/HANDOFF.md` (keep it under ~60 lines). Update `**Last updated:**` (today) and `**Branch / commit:**`, then keep
   these exact headings, filling each:
   - `## Where we are`
   - `## What changed last session` (facts, file names; this session becomes "last session" for the next one)
   - `## Current task`
   - `## Next step (specific, first action)` (one a fresh Claude can start on immediately)
   - `## Open questions / decisions pending`
   - `## Known broken or flaky` (with how to reproduce)
   - `## Commands that matter right now`
   - `## Context a fresh Claude needs` (only what is not in other docs)
5. If a bug cost 30 or more minutes, add a `docs/TROUBLESHOOTING.md` entry.
6. If a technical decision was made, ensure an ADR exists (`/adr`).
7. Final message: 3 to 6 lines. What got done, what is next, anything uncommitted.

Rules:
- Never claim tests pass without having run them this session.
- Do not tell the user to stop, rest, or leave. Just wrap up the paperwork.
