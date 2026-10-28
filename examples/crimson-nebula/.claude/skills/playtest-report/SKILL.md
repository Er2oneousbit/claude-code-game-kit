---
name: playtest-report
description: Turn playtest notes, quotes, or telemetry into a structured log entry and concrete tasks. Use when the user pastes tester feedback, describes a playtest, or says "people said...". Separates observations from opinions and maps pain points to tunables and roadmap items.
---

# Playtest report

Follow `docs/sop/SOP-03-playtest-and-tuning.md`.

1. Ask for anything missing: build or commit, tester, duration, the question being tested. Do not invent it.
   The owner's own notes after playing ("I like X, Y bugs me") need no interview: the tester is the owner, the build is
   the current commit, the question is "is it fun yet?". Log them and go straight to the ranked list.
2. Add an entry to the top of `docs/PLAYTEST_LOG.md` using its template. Keep **observations** (what happened) apart from **opinions** (what they said they felt). Keep exact quotes verbatim.
3. Rank pain points by severity and by how many testers hit them. Blockers first.
4. For each top pain point propose:
   - the likely underlying cause (hypothesis, not fact)
   - which **tunables** could change it (name the actual data or constant if known)
   - the cheapest experiment to test it
5. Create ROADMAP items for anything bigger than a tuning change. Park low-value suggestions with a reason.
6. If telemetry files exist, delegate summarizing to the `playtest-analyst` subagent and fold the summary in.
7. Output: the log entry, the ranked list, and the proposed first experiment.

Do not treat a tester's proposed solution as the requirement. Dig for the problem they are reacting to.
