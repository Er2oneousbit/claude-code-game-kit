# Troubleshooting Log

> Known issues and verified fixes. Future-you and testers should not need to ask how to fix these.
> Add an entry whenever a bug cost more than ~30 minutes or is likely to come back.

## Template (copy)
```
### <Short symptom>
- First seen: YYYY-MM-DD
- Environment: OS, engine version, build type
- Symptom: exact error text or behavior
- Root cause: 
- Fix: 
- How to verify: 
- Related: commit / ADR / issue
```

## Entries
### The robot caught a courier who had not moved yet
- First seen: 2026-10-21
- Environment: Windows 11, headless Chromium (Playwright), Three.js r186
- Symptom: first smoke screenshot showed the "!" and a chase toward the depot before any input
- Root cause: the patrol passes close enough to the depot to see it; the unit-test bots move from the first step, so tests never idled
- Fix: the robot perceives nothing until the run starts (`robot.step(dt, pos, awake)`, `awake = sim.started`), matching the clock rule
- How to verify: `tests/robot.test.ts` "asleep until the run starts"; `python tools/dev.py smoke --screenshot build/start.png`

### The careful bot kept getting spotted while it waited
- First seen: 2026-10-21
- Symptom: careful bot caught or out of time from every robot start; logs showed `SPOTTED`/`LOST` every second
- Root cause: it waited for a gap while standing inside the cone, and walked back into view while the robot searched
- Fix: three moves in `src/core/bot.ts`: wait only when unseen, sidestep out of the cone, and run for the best hidden spot when spotted
- How to verify: `python tools/dev.py test` (scenario pair, 4 robot starts each)

### Headless `--record` captured only a few dozen frames
- First seen: 2026-10-21
- Symptom: `smoke --record` of a full run saved 38 frames
- Root cause: headless Chromium renders WebGL in software; every screenshot waits for a slow frame
- Fix: record with `--headed` (real GPU): 425 frames for the same run
- How to verify: `python tools/dev.py smoke --headed --query autoplay --until RUN_WON --record build/frames`
