# Playtest Log

> One entry per session. Newest on top. Use `/playtest-report` to add entries and turn them into tasks.
> Playtest = anyone who is not you playing, or you playing with a specific question.

## Template (copy)
```
### YYYY-MM-DD  Build <version/commit>  Tester: <name or "self">  Duration: <min>
Question being tested: 
What happened (observations, not opinions):
- 
Quotes (exact words):
- 
Pain points (ranked):
1. 
Delight moments:
- 
Metrics (deaths per section, time to first success, quits):
- 
Decisions / tuning changes:
- 
Tasks created (ROADMAP):
- 
```

## Entries
### 2026-10-23  Build 0.2.0 (the 4x yards, before the playtest fixes)  Tester: the user  Duration: not recorded
Question being tested: do the big yards, the gate and the difficulties work as built?
What happened (observations, not opinions):
- The title text was clipped and the window small (a saved 1280x720 window from screenshot runs).
- The narrator spoke over the title screen.
- Every difficulty looked the same (the scene's Skybox ambient ignored the difficulty's light).
- Lantern out, the keeper's legs froze; the lantern was not in his hands.
- Caught with every soul, a soul went back but the gate stayed open; walking out then fell out of the world.
Quotes (exact words):
- "diff levels dont actually change the global light, they are all the same"
- "if you get caught on the way to an open gate you lose a soul but the gate remains open"
- "the lantern is not in his hands"
Pain points (ranked):
1. Difficulty not visible. 2. The gate after a catch. 3. The keeper's animation and lantern.
Delight moments:
- (none recorded)
Metrics (deaths per section, time to first success, quits):
- Player.log: one generated night (seed 93922, Easy) with three catches, the gate opened, then two falls outside it.
Decisions / tuning changes:
- Nine fixes, one at a time with a test each: HOW_IT_WAS_MADE "Later: the first playtest of the big yards". Then the
  lantern 10% brighter (the user's ask).
Tasks created (ROADMAP):
- The user replays the fixed build; then an outside playtest.
