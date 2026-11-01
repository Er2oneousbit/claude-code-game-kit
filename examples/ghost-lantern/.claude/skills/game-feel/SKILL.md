---
name: game-feel
description: Add or tune game feel ("juice") - screen shake, hitstop, squash and stretch, easing, camera follow, input buffering, coyote time, hit flashes - so actions feel responsive and impactful. Use when the user says the game feels floaty, weak, stiff, flat or "not juicy", asks for screen shake or hit pause, or a playtest note says hits do not land. Follows SOP-18, including the accessibility rules (shake off switch, flash limit).
---

# Game feel

Follow `docs/sop/SOP-18-game-feel.md`.

1. **Check the mechanic first:** juice tunes a mechanic that already works (F4). If the core loop is not fun with plain
   shapes yet, say so and stop.
2. **Moments:** list the five to ten moments that matter (hit, land, jump, pick up, die) with the feeling each should
   give, and pick at most two or three effects per moment (SOP-18 step 1). Confirm the list with the user.
3. **Use the kit's juice module** (`docs/ENGINE.md` names the files; the spec is `tools/golden_vectors.py`). Do not write
   a second shake or tween system. If a needed behavior is missing, change the reference first, run
   `python tools/golden_vectors.py --write`, then the port, then its tests.
4. **Wire it:** game time in (`dt` after hitstop and game speed), the camera moves (never the world), every number in the
   constants block or a data file.
5. **Protect players (always):** shake intensity from `effective_shake(settings)`, reduce motion turns shake, bob and
   pulses off, every full-screen flash through the flash limiter (SOP-18 step 3, F33, F34).
6. **Prove it:** `check`, `test` (the juice tests against `data/golden/juice.json`), then record a burst of each key
   moment (`dev.py smoke --record`, a GIF with `tools/art/frames_to_gif.py`) and look at the frames before posting.
7. **Report:** moments and effects, where the tunables live, the GIF links, and one playtest question for the user.
