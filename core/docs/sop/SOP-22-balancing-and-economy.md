# SOP-22: Balancing and economy

## Goal
The numbers make the game's choices interesting: no option is always right, nothing is useless, the difficulty rises the
way the GDD intends, and the economy neither floods nor starves the player. Balance is mostly choosing numbers (E92); this
SOP is how to choose them on evidence instead of by feel alone.

## 1. Put every number where you can see it (standard practice)
- All balance numbers in data files (`data/`) or one constants module, never in logic (`docs/STYLE.md`). One table per
  system: units, weapons, enemies, shop prices, drop rates, XP curve.
- A balance sheet next to the data (`docs/balance.csv` or a spreadsheet): one row per item with its inputs and the
  derived numbers (damage per second, cost per damage, time to kill, gold per minute). The sheet is where you compare;
  the data file is what the game reads. Generate one from the other so they cannot drift.

## 2. Model the economy as sources and sinks (standard practice)
1. List every **source** (where a resource comes from: kills, chests, quests, time) and every **sink** (where it goes:
   shops, upgrades, repairs, deaths) for each resource.
2. Estimate the flow per minute of play at three points (early, middle, late). If sources outgrow sinks the currency
   floods and stops meaning anything; if sinks outgrow sources the player stalls.
3. Give every sink a reason to exist beyond draining money (a choice, a trade-off), and every source a cost (time, risk).

## 3. Curves for progression (standard practice)
- Pick the shape on purpose: linear (steady), polynomial (`a * level^p`, gentle at first), exponential (`a * r^level`,
  explodes; usually needs a cap). Plot the player's power and the challenge on the same chart: the gap between them is the
  difficulty the player feels.
- Plan where the player should struggle (a boss, a new mechanic) and where they should feel strong (just after an
  upgrade). A flat gap is boring; a widening gap is a wall.
- Intransitive choices (rock, paper, scissors) are balanced by the frequencies they make optimal (E92, tip): change a
  cost or a counter, then check that the mix players pick moves the way you wanted.

## 4. Measure, do not guess
1. **Bots** (`SOP-14` step 6): run the game's bots over many seeds and difficulty settings and log time to clear, deaths,
   resources at each checkpoint. A change that should help one strategy must not help all of them (F32).
2. **Playtests** (`SOP-03`): one question per session; write down the numbers players hit (wave reached, gold at the
   shop, time to the boss).
3. **Telemetry with consent** (`SOP-19` step 8): the same counters from real players, local CSV first.
4. Change one number at a time, write the before and after with the reason in the balance sheet, re-run the bots.
5. When something is too strong, find why before cutting it (E92, tip): the cause is often another number (a cheap cost,
   a missing counter), and a nerf to the symptom moves the problem.

## 5. Difficulty and assist
Difficulty settings scale numbers, not rules (enemy damage, health, timers), and the player can change them during play
(`SOP-20`, E69). Story or assist modes are part of balance, not a cheat: test them with the bots too.

## Done when
- Every balance number is in data, mirrored in the balance sheet with derived values.
- Sources and sinks are listed with estimated flow for each resource.
- The bots' numbers per checkpoint are recorded for the current build and match the intended curve within a margin the
  GDD states.

## Common mistakes
- Tuning by feel in the code, with no record of what changed and why.
- An exponential curve without a cap, found at hour ten.
- One dominant strategy that the bots would have found in minutes.
- Catch-up mechanics that hide an imbalance instead of fixing it (E92, tip).
