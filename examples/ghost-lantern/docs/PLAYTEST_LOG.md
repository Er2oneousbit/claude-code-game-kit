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
### 2026-11-04  Build a27dfc1  Tester: the user (first human playtest)  Duration: not recorded
Question being tested: is the slice fun to play by hand (assumptions 1 and 3 in `VERTICAL_SLICE.md`)?
What happened (observations, not opinions):
- Runs ended with the lantern empty or a ghost catching up from behind.
Quotes (exact words):
- "ghosts are too fast or i run out of oil and they catch up to me"
Pain points (ranked):
1. The oil runs out before the exit (dim burn 3.5 per second).
2. Chasing ghosts (3.9 tiles per second) outrun the keeper (3.6) once the light is gone.
Delight moments:
- not recorded
Metrics (deaths per section, time to first success, quits):
- not recorded
Decisions / tuning changes:
- Dim burn 3.5 to 3.0 on Normal (the user's number).
- A difficulty choice on the main menu (the kit's shell, now wired in): Story, Easy, Normal, Hard change the oil
  burn and the ghost speeds; Easy brings the ghosts down to about the keeper's speed. Values and the bot results per
  difficulty: `src/game/tuning.ts` and HOW_IT_WAS_MADE.
Tasks created (ROADMAP):
- Play Easy and Normal by hand again: does Easy fix the complaint, and is Normal still tense?
