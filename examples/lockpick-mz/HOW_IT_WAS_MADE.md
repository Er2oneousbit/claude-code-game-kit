# How Lockpick MZ was made

The kit's RPG Maker MZ example, made in one session (2026-10-23) right after the `rpgmaker-mz` overlay, on a machine
**without RPG Maker MZ**. The owner asked to "add in rpg maker" and chose: MZ (not MV, VX Ace or Unite), build it
unverified for now, and an overlay plus a small example.

## 1. What could and could not be checked
RPG Maker MZ's core scripts carry no open-source license (the header of `rmmz_core.js` 1.1.0 names no license, unlike
MV's MIT core), so the kit ships none of MZ and the example only its own two plugins. Everything that needs MZ itself is
marked **(verify)** in the overlay's docs. What was checked instead:

| Layer | How | Result |
|---|---|---|
| Rules and bots (`GameCore.js`) | Node's test runner, 40 seeds | 8 tests; careful 40/40, sloppy 40/40, sloppier 37/40, masher 1/40 |
| MZ glue (`GameMain.js`) | Node, with stand-ins for `Scene_Base`, `Sprite`, `Bitmap`, `SceneManager`, the title window, input and switches | 8 tests: the command clamps its string arguments, both bots play the scene to the end, the switch and the pop, the title command, `?autoplay` |
| The overlay's commands | A scaffolded game plus a fake MZ project (stand-in core scripts, scratch only) | `setup --from` copies and registers, `check` catches five planted faults, `smoke` boots in headless Chromium, `build` leaves out `save/` and the project file |
| The scene in a browser | The fake MZ with a scene loop, `dev.py smoke --query autoplay --until LOCK_OPEN --fail-on LOCK_JAMMED` | The careful bot reached `LOCK_OPEN`, the masher `LOCK_JAMMED`, no console errors |

## 2. The scenario pair, and the sloppy copies
The pillar: *timing beats mashing*. The first careful bot opened **0 of 40** locks: it reacted 6 frames late (like a
person), and by then the pick had moved 0.09 of the bar, more than half the 0.16 sweet spot. A person does not react to
where the pick was; they read its motion and press early. The bot now predicts the same way (where it saw the pick plus
the pick's visible speed over its lag) and opens 40 of 40. Then, after a reader's post on a level validator (kit
evidence E60): the right answer played sloppily must still win, or the lock is too tight for a human hand. A sloppier
copy (10 frames late, pressing anywhere in 90% of the spot) opens 40 of 40 and a sloppier one (14 frames, the whole
spot) 37; the masher opens 1. The test asserts careful at least 36, sloppy at least 34, masher at most 4.

## 3. What the checks caught
| # | Caught by | Problem | Fix |
|---|---|---|---|
| 1 | The pair, first run | The careful bot never opened a lock (above) | It predicts from the pick's motion |
| 2 | `gameMain.test.js` | Seed 7, the demo's first seed, is the one lock of 40 the masher opens: the masher test and `?autoplay=masher` would have "opened" | Seed 8 for the demo and the tests |
| 3 | `node --test tests/` in the overlay's package.json | Node 26 reads a folder argument as a module path | A glob: `node --test "tests/**/*.test.js"` (dev.py passes files) |
| 4 | The kit's doctor on a fresh scaffold | Docs named files that only exist after `setup --from` (game.rmmzproject, js/plugins.js), nine warnings | Added to the link checker's list of files made later (as for Unity and Unreal) |
| 5 | Adopting a fake MZ project kept at the root | `check` reported the game's plugins missing without saying why | A hint: the kit put them in `game/js/plugins/`, move the project into `game/` |
| 6 | Reading MZ's `module`/`window` situation | Under NW.js (MZ's desktop test play) `module` may exist, and an either/or export would hide the plugin from the game | The rules plugin sets the global and, when present, `module.exports` |

## 4. What is not verified
- That RPG Maker MZ runs these plugins: `Scene_Base`'s lifecycle, `SceneManager.prepareNextScene`, `Bitmap.drawText`'s
  arguments, a fourth title command in a three-row window, and `this` in a plugin command were written from MZ's
  conventions, not run.
- The editor's side: the `/*:` annotation as the Plugin Manager reads it (`@base`, `@orderAfter`, `@type switch`), the
  `js/plugins.js` format `setup` writes, `RPGMZ.exe <project>` for `run --editor`.
- Smoke against real MZ (WebGL in software, loading the real database).
The first run on a machine with MZ: `setup --from`, `check`, `test`, `smoke --query autoplay --until LOCK_OPEN`, then
play it from the title screen. Whatever breaks becomes a kit fix and a line in this file.
