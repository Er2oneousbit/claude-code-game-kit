# How Ghost Lantern was made

The kit's "only what is in the kit" example. One Claude Code session (Claude Opus 5.5) on Windows 11 with Node 26,
2026-10-21. The user picked the concept; Claude did the rest by following the kit's documents and tools, and recorded
every place the kit fell short. Those gaps were fixed **in the kit** during the run and pulled into the game with
`new_game.py --upgrade`, the same way any kit user gets updates.

## The rule
Allowed: what a kit user has after scaffolding (the docs, SOPs, skills, `tools/`, the overlay's pinned packages including
Phaser's bundled skills) plus the sources the kit's resource lists name. Not allowed: outside scripts or tools. The one
exception is listed at the end.

## 1. Scaffold and health check (FIRST_HOUR 0 to 5 min)
```
python scripts/new_game.py --name "Ghost Lantern" --engine web --dest ../ghost-lantern --git-init
python tools/dev.py setup
python tools/dev.py doctor
```
**Kit gap 1:** the scaffolder's next steps said "set the exact engine version", which does not apply to the web overlay
(versions are pinned in `package.json`). Fixed: engines can set a `setup_step` in their engine.json.

## 2. Brainstorm and GDD (5 to 25 min)
Claude offered four concepts, each built on a different classic game-AI technique; the user picked "Ghost Lantern"
(utility AI plus A*). The GDD identity block got the pitch, three pillars (readable ghosts, light is the resource, one more
run) and the core loop.

## 3. References and look (25 to 35 min)
No image generator: the look was locked to Kenney's Tiny Dungeon pack (`docs/resources/art.md` lists kenney.nl as the best
prototyping source). The license was read on the pack's own page (CC0), then:
```
python tools/fetch_asset.py --url <tiny-dungeon zip> --list
python tools/fetch_asset.py --url <zip> --page https://kenney.nl/assets/tiny-dungeon --author Kenney --license CC0 \
  --type tileset --to public/assets/art --take "Tilemap/tilemap_packed.png"
python tools/fetch_asset.py --url <zip> ... --type art --to docs/concepts/final --take "Preview.png"
python tools/fetch_asset.py --url <interface-sounds zip> ... --type sfx --to public/assets/audio \
  --take "Audio/glass_002.ogg" --take "Audio/confirmation_002.ogg" --take "Audio/open_001.ogg" --take "Audio/glitch_003.ogg"
```
The concept preview went in through the tool too, so it has an asset row: anything third-party in the repo gets logged.
Tile indices were confirmed by opening the pack's single-tile files (`Tiles/tile_NNNN.png`): two guesses were wrong
(index 29 is a banner, not a torch; 117 is a hammer, and the pack has no key at all, so the key lives in a chest).
**Kit gap 2 (minor, open):** no helper to print a sheet with its tile indices. Opening single tiles worked.

## 4. Slice brief and budget (35 to 50 min)
`docs/VERTICAL_SLICE.md`: three rooms, one ghost type, oil, key, exit, restart; debug flags and an autoplay bot in scope;
music, menus, saves out. A budget row in `docs/ROADMAP.md` (time was not measured precisely in this run; log yours).

## 5. Build (SOP-01, then SOP-14)
**Kit gap 3 (big):** the kit had no guidance for game AI at all. SOP-14 (perception, decision, movement; FSM, behavior
tree, utility, planners; per-engine navigation and debug tools; testing) and the `/game-ai` skill were written from
official engine docs and Game AI Pro (evidence E36 to E40), then pulled in with `--upgrade`. The build followed `/game-ai`:
- **Engine-free core first, with tests:** `rng.ts` (seeded), `grid.ts` (map and wall collision), `astar.ts`, `lantern.ts`,
  `ghostBrain.ts` (utility scores and inertia), later `separation.ts`. 40 Vitest tests.
- **ADR 0001** records why utility AI beat an FSM here (two continuous inputs: distance and light).
- **Phaser APIs verified** against `node_modules/phaser/skills/` and `node_modules/phaser/types/phaser.d.ts` before use (tilemap from an array,
  spritesheets, canvas texture for the darkness, camera follow and zoom).
- **Engine side:** `GameScene.ts` (perception, movement, darkness overlay, debug view, bot), `HudScene.ts` (UI outside the zoom).

## 6. Scenario checks (SOP-14 step 6)
**Kit gaps 4 and 5:** `smoke` could not open the game with URL flags, wait for a gameplay marker, or capture what happened.
Added to the web overlay: `smoke --query --until --fail-on --screenshot --record`, plus `tools/art/frames_to_gif.py` for
any engine. Then a scenario **pair**: `?autoplay` (brightens when a ghost is close) must escape, `?autoplay=dark` (never
brightens) must be caught. If the dark bot escapes, the lantern does not matter and pillar 2 is false.

## 7. What the kit's checks caught
| Caught by | Problem | Fix |
|---|---|---|
| `dev.py test` | An empty lantern still counted as bright for one frame | Decide "bright" after draining the oil |
| Scenario pair, round 1 | The bot with the lantern was caught; the dark bot escaped. Ghosts were slower than the player, so running beat the lantern | Ghosts chase faster than you walk |
| Scenario pair, round 2 | Still inverted: even dim light repelled ghosts at point-blank range | Lantern **power**: dim 0.35 (for seeing), bright 1.0 (for shielding) |
| `--debug` log of the run | A ghost decided every 0.25 s and covered a tile between decisions, catching the player inside the light | Think every 0.12 s, and a shield rule: a ghost in strong light cannot touch you |
| Scenario pair, round 3 | The bot ran dry: ghosts hover at the edge of the light, so holding it bright burns all the oil | Burst the light only when a ghost is within 2.2 tiles; bright burn 12 to 10 per second |
| `smoke --screenshot` | All three ghosts stacked into one sprite (same flee target) | Separation steering and a crowd penalty on flee targets |
| `--record` frames | A fleeing ghost passed through the wizard | Fleeing ghosts keep out of a small radius around the player |
Final result over 6 seeds: with the lantern the bot escapes every time (38 to 47 oil left, two oil pickups needed), without
it the bot is caught every time. Logged in `docs/VERTICAL_SLICE.md` as assumption 2 confirmed. Assumptions 1 (readable
ghosts) and 3 (one more run) need human players.

**Kit gap 6, found by `tools/publish_check.py` before anything was committed:** 431 files would have been published, 305 of
them recorded frames in `build/`. The web overlay did not ignore `build/`, and `--upgrade` never added new ignore rules to
an existing project. Fixed both: the overlay ignores `/build/`, and `--upgrade` now appends the kit rules a project is
missing (124 files after the fix).

## 8. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` | type check passed |
| `python tools/dev.py test` | 40/40 |
| `python tools/dev.py smoke` | boot in headless Chromium, no console errors, no failed requests |
| Scenario pair, seeds 1 to 6 | 6/6 escape with the lantern, 6/6 caught without |
| `python tools/doctor.py`, `python tools/check_links.py` | healthy, no broken references |

### Later: generated sound (ElevenLabs)
The user asked for API audio in the other example games (2026-10-23), after Graveyard Shift had it. The Kenney sounds
were replaced by sound effects generated with the kit's `tools/audio/eleven_audio.py`, plus an ambience loop the game
never had. Every file is a PLACEHOLDER (non-commercial terms) in `docs/ASSET_LOG.md` (credit in the README); the old
Kenney rows stay, marked removed. Every file was measured before use (peak, loudness, silence at the start, the jump at
a loop's seam, flat-topped samples), then peak-normalized: one-shots to -3 dBFS, loops to -6 (the log says Modified, the
evidence file keeps the shipped file's SHA-256, the `.gen.json` next to it the generated one).

| Event | File |
|---|---|
| oil picked up | `oil-refill.mp3` |
| the key from the chest | `key-found.mp3` |
| out of the door | `door-escape.mp3` |
| caught by a ghost | `ghost-caught.mp3` |
| always (Phaser starts it when the browser unlocks audio) | `haunted-ambience.wav` (10 s loop) |

- What the measurements caught: the oil pour came back nearly silent (-29.5 dBFS peak); a retake with a louder prompt
  ("a clear liquid glug glug, then a soft whoomp as the flame flares") reached -16.8 and was normalized.
- Verified: `check`, 40 tests, `smoke`, and every file decoded in headless Chromium.

## 9. Outside the kit (be honest)
- Before writing `src/game/level.ts`, the map was sanity-checked once with a few lines of throwaway Python (row lengths,
  start-to-key path). The same checks now live in `tests/level.test.ts`; the throwaway was not needed in the end.
- Everything else (assets, GIF, screenshots, checks) went through the kit's own commands.
