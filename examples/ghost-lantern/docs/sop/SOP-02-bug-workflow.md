# SOP-02: Bug Workflow and Systematic Troubleshooting

## Goal
Find root causes with minimal thrash. One change at a time, with evidence.

## Steps
1. **Reproduce.** Exact steps, expected vs actual, frequency (always, sometimes, once). Get a seed or replay if randomness is involved.
   Cannot reproduce? Add logging first, do not guess a fix.
2. **Capture facts.** Error text verbatim, engine version, build type, platform, recent commits (`git log -5`).
3. **Shrink.** Find the smallest scene, level, or test that still fails.
4. **Hypothesize.** Write the hypothesis in one sentence and what evidence would confirm or refute it.
5. **Change exactly one thing.** Run the repro. Record the result (worked, no change, new symptom).
6. **Bisect when the cause is unclear.** `git bisect` or disable half the systems. Binary search beats intuition.
7. **Fix the cause, not the symptom.** Ask why the bug was possible, not just why it happened.
8. **Lock it in.** Add a test that fails without the fix when feasible. If the bug cost over 30 minutes, add a `TROUBLESHOOTING.md` entry.

## Stuck protocol (after 3 failed hypotheses)
Run `/stuck`. It forces a change of angle:
- List every assumption made so far and attack the one you trust most.
- Check the boring stuff: wrong file loaded, stale build, cached import, wrong branch, wrong engine version.
- Explain the system out loud from first principles (rubber duck, written).
- Look at it from the other side: input data, timing, order of initialization, threading, platform differences.
- Search the engine's issue tracker and docs for the exact error text. Label findings **verified** or **unverified**.
- Delegate a read-only investigation to the `researcher` or `build-doctor` subagent for a fresh context.

## Severity, priority and the release bar (standard practice)
Every bug gets a severity (how bad) and a priority (how soon); severity does not change with the schedule, priority does.

| Severity | Means | Examples |
|---|---|---|
| S1 Blocker | The game cannot be finished, data is lost, or players are harmed | Crash on start, save corruption, a soft lock on the main path, a flash that breaks the SOP-20 rule |
| S2 Major | A main feature is broken, with a workaround | A boss that sometimes does not spawn, rebinding that does not save |
| S3 Minor | Wrong but playable | A wrong sound, a clipped label, a sprite drawn behind a wall |
| S4 Cosmetic | Polish | A pixel off, a slightly late animation |

Priority P1 to P3 says when: P1 now (this build), P2 before the next release, P3 when there is time.
**Release candidate bar:** no open S1; every open S2 has a written workaround in the known issues and is planned for the
first patch; S3 and S4 are listed. A bug that reaches players at S1 gets a hotfix (SOP-06 "After launch").

## Done when
- Repro no longer fails; a test that fails without the fix covers it (where no test is feasible: the smoke run or a
  written manual check in `TROUBLESHOOTING.md`); notes recorded.

## Common mistakes
- Changing three things at once, then not knowing which fixed it.
- Trusting memory of engine APIs. Verify against installed version.
- Fixing in the wrong layer (patching the game when Core is the bug).
- Not writing it down, so the same bug returns in six months.
