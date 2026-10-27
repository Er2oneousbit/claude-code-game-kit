---
name: bug-hunt
description: Diagnose and fix a bug, crash, or weird behavior systematically. Use when the user reports something broken, pastes an error, or says "it doesn't work". Reproduce first, one hypothesis and one change at a time, add a regression test.
---

# Bug hunt

Follow `docs/sop/SOP-02-bug-workflow.md`.

1. **Intake:** get exact error text, steps, expected vs actual, frequency, engine/build type. Ask for what is missing. Do not guess a fix yet.
2. **Reproduce:** find a command, test, scene, or seed that reproduces it. No repro? Propose logging to add, add it, collect.
3. **Facts:** `git log --oneline -10` and `git diff` since last known good. If unclear, propose `git bisect`.
4. **Hypotheses:** list up to 3, ranked, each with what evidence would confirm or refute it. Show the user.
5. **Test one hypothesis at a time:** change exactly one thing, run the repro, record the outcome in a running list (hypothesis, change, result).
6. **Root cause:** state it in one or two sentences, including why the bug was possible.
7. **Fix and lock in:** smallest correct fix, plus a regression test when feasible. Run `check`, `test`, and `smoke` if relevant.
8. **Record:** if it cost 30+ minutes or is likely to recur, add a `docs/TROUBLESHOOTING.md` entry.

After 3 failed hypotheses, switch to `/stuck`.

Label any claim about engine behavior as **verified** or **unverified**. Verify before relying on it.
