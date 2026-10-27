---
name: perf-pass
description: Investigate and fix performance problems (low FPS, hitches, memory growth, slow loads). Use when the user mentions lag, stutter, frame drops, or high memory. Measures first, fixes the top offender, remeasures.
---

# Performance pass

Follow `docs/sop/SOP-10-performance.md`. Engine profiler instructions are in `docs/ENGINE_FLOW.md`.

1. Confirm the budget in `docs/ARCHITECTURE.md` (target FPS, min spec). Missing? Ask, then record it.
2. Get a **baseline**: which scene or level, build type, hardware, numbers (avg and worst frame time). Ask the user to run the profiler if it needs the editor UI. Tell them exactly which panel and which numbers to capture.
3. Identify the single biggest contributor. Do not guess. If the data is not available, add instrumentation (frame-time log, counters) first.
4. Propose one fix and the expected effect. Make that one change.
5. Remeasure with the same scene and hardware. Record before and after.
6. Repeat until the budget is met. Then stop. No speculative optimization.
7. Add a guard: a stress scene or frame-time check in `smoke` where feasible.
8. Record the result in the `docs/ARCHITECTURE.md` Budgets table ("Measured on" and "Last measured"), in the commit message when a commit is requested, and, if it was a trap, in `docs/TROUBLESHOOTING.md`.

Warn when measurements come from an editor or debug build. Those are not release truth.
