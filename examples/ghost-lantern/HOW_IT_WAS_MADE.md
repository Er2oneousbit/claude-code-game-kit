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
were replaced by sound effects generated with the kit's `tools/audio/wavesmith/eleven_audio.py`, plus an ambience loop the game
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

### Later: PixelLab sprites for the keeper and the ghosts
The keeper and the ghosts were single Kenney tiles (84 and 121, flipped to face left). The user asked for real sprites
(2026-11-04, kit issue #17); they were made with the kit's `tools/art/pixellab.py` the way SOP-16 says: one anchor per
character, every animation made from it. Kenney's tiles, chest and oil stay. 44 generations in all, logged as A-0009 to
A-0013 in `docs/ASSET_LOG.md` (prompts and SHA-256 in `docs/licenses/`).

| Sprite | How | In the game |
|---|---|---|
| Keeper | v3 `character` at 32 px, 8 directions (2 generations), then `animate-character --mode skeleton-v3` with the `walk` and `breathing-idle` templates on 4 directions (12 each) | walk 6 frames, idle 4, for south, west and north in 48x48 cells; east is west mirrored |
| Ghost | `image` 32x32, four takes (1 each), the third kept as the anchor; three `animate` runs from it, 8 frames each (1 each) | wander bobs (all 9 frames), chase wails and flee cowers (frames 3 to 7 looped) |

`src/game/sprites.ts` holds the clips and the facing rule; `tests/sprites.test.ts` checks that every frame the game loads
is a real PNG of its size, so a renamed file fails `test` instead of showing Phaser's missing-texture box. The ghosts keep
their tint and transparency per action; each action now also has its own pose, which serves pillar 1 (readable ghosts).

What did not work first:
- **16 px, the Kenney size.** The older 4-direction endpoint (`character --legacy --size 16`) drew a face on every north
  view: 8 takes over two prompts and two camera views (8 generations). v3 at 32 px gave real back views. The keeper is
  therefore about 1.5 tiles tall, bigger than Kenney's figures but at the same pixel size (1:1 at 2x zoom).
- **No palette option.** `pixellab.py` has no colour reference, so the look was matched by prompt and style settings
  (black outline, low detail, low top-down, "retro 16-bit"). The frames use more colours than the Kenney sheet (105
  against 27); a shared 16-colour reduction was tried and made the faces worse, so the frames ship as generated.
- **East view.** PixelLab's east keeper hid the lantern behind his body and its idle turned the lantern into a stick;
  mirroring the west art fixed both (SOP-16: animate the side where the prop is in front, then mirror).
- **Two kit bugs, fixed in the kit (CHANGELOG 0.8.3):** `animate` came back with a flat grey background (1 generation
  retaken), and a v3 `character` was refused by PixelLab for `--directions 4` and for `--shading` (no charge). The fixed
  tool asks for transparent frames and refuses both before sending.

Verified: `check`, 160 tests, `smoke`, the scenario pair (`?autoplay` escapes, `?autoplay=dark` is caught) and
`smoke --screenshot` shots looked at by eye: the keeper and the ghosts read against the tiles. The README GIF was then remade from the autoplay escape with the kit's own commands
(README "Remake the GIF"); at 64 colours the wizard's purple turned brown, so it uses 128.

### Later: the first human playtest, and a difficulty menu
The first person to play the slice by hand was the user (2026-11-04), after the sprites: "ghosts are too fast or i run
out of oil and they catch up to me". The bots had never said so: the lantern bot escapes with oil to spare because it
plays every run perfectly and fast. The ask: dim burn down to 3, and a difficulty menu built with the kit that changes
the burn rate and the ghost speed. Logged in `docs/PLAYTEST_LOG.md` (the first entry) and `docs/VERTICAL_SLICE.md`
(round 2).

- **Normal:** dim burn 3.5 to 3.0 (the user's number). Everything else stays: chase 3.9 is still faster than the keeper's
  3.6, which is pillar 2 ("only the light saves you").
- **The table** (`src/game/tuning.ts`, DIFFICULTY): only the oil burn and the ghost speeds change, so every difficulty is
  the same game. A full lantern lasts 67 s dim on Story, 45 on Easy, 33 on Normal, 25 on Hard (29 before the playtest).

| Difficulty | Dim / bright burn | Chase / flee / wander | Lantern bot (seeds 1 to 8) | Dark bot |
|---|---|---|---|---|
| Story | 1.5 / 5.0 | 3.0 / 3.2 / 0.9 | escapes 8/8, 19 to 22 s, 35 to 70 oil left | caught 8/8 (about 11 s) |
| Easy | 2.2 / 7.5 | 3.5 / 3.2 / 1.0 | escapes 8/8, 20 to 24 s, 46 to 55 oil | caught 7/8 (seed 8 gets through) |
| Normal | 3.0 / 10.0 | 3.9 / 3.2 / 1.1 | escapes 8/8, 21 to 25 s, 37 to 59 oil | caught 8/8 (6 to 13 s) |
| Hard | 4.0 / 12.0 | 3.9 / 3.2 / 1.1 | escapes 8/8, 21 to 22 s, 45 to 55 oil | caught 8/8 (6 to 13 s) |

Easy answers both halves of the complaint: a third more oil time than Normal (half again as much as before the
playtest), and chasers at 3.5, just under the keeper's speed
(running in the dark can work, sometimes: the dark bot got through once). Even on Story the dark bot is caught: slow ghosts
still cut corners. What the bots caught while tuning Hard (the lantern bot must escape every seed, SOP-22 section 5):
- **Faster ghosts beat the bot, not just the player:** chase 4.3 escaped 3 of 6 seeds, 4.1 5 of 6 (7 of 8 with wander back
  at 1.1), 4.0 7 of 8. The bot brightens only when a ghost is within 2.2 tiles, a fixed reaction that faster ghosts
  outrun. Hard keeps Normal's ghost speed.
- **Oil has a cliff:** burn 4.5 / 13.5 escaped only 2 of 8. Below 35 % oil the bot detours for a pickup, and that detour
  walks past the ghosts (every catch came at 15 to 16 s, right after it). 4.0 / 12.0 escaped 8 of 8. Oil left at the exit
  is a poor yardstick for this: a thirstier lantern sends the bot to more pickups, so Hard ends with as much oil as Normal.

**The menu, with the kit's shell.** The example already carried the kit's whole web shell (`src/shell/`: title, menus,
settings, pause, credits, crash screen, the smoke driver) and its tests, but nothing started it: when kit 0.8.0 was
merged into the examples, `src/main.ts` was the game's own and was kept as it was ("boot flows unchanged"), so the shell
sat unused and `smoke --drive` could not run. Wiring it in was smaller than any new menu: `main.ts` hands the game to the
shell, GameScene became the shell's "main" scene, and the kit's settings file already had a `difficulty` field (Story,
Easy, Normal, Hard) in Settings > Accessibility. Changes on the game's side:
- The main menu got a Difficulty row under Play (left/right, with a one-line hint), saved to the settings file when you
  leave the menu. `src/game/difficulty.ts` picks the run's difficulty: `?difficulty=<name>` for tests, else the setting.
- Changed from the pause menu's settings, it applies on Resume and keeps the oil you have (SOP-20: changeable during play).
- `?autoplay` skips the shell (GameScene starts at once and logs BOOT_OK itself), so the bot pair and the README GIF run
  exactly as before. Phaser's keyboard stays on for the game's own keys; the shell reads the menus and Esc (pause).
- The HUD scene now stops with the game scene (quit to title left it on screen), the shell's pause prompt moved to the
  bottom centre (it covered the oil bar), and the menu backdrop is the game's night instead of the kit's blue stripes.
- The kit's `--drive show:` list got `menu` (the main menu with the difficulty row focused).

Verified: `check`, 172 tests (12 new in `tests/difficulty.test.ts`: the table's order and pillar, Easy against the
complaint, the URL flag against the saved setting), `smoke`, the scenario pair on Normal and on Hard, `smoke --drive
menus`, `--drive pseudo --locale pseudo` (23 screens, nothing truncated, through a real run and its pause menu), `--drive
crash`, and screenshots of the title, the menu, settings and pause looked at by eye.

## 9. Outside the kit (be honest)
- Before writing `src/game/level.ts`, the map was sanity-checked once with a few lines of throwaway Python (row lengths,
  start-to-key path). The same checks now live in `tests/level.test.ts`; the throwaway was not needed in the end.
- The PixelLab sprites: two throwaway Pillow scripts, one for contact sheets (every frame at 4x on a floor tile, to
  review the takes) and one for the five ASSET_LOG rows and evidence files in the tool's `--log` format (each row covers
  an anchor plus an animation, two requests, which `--log` writes as separate rows). The ghost animations ran on a copy
  of the tool with the transparent-frames fix before it was committed to the kit.
- The difficulty measurements (4 difficulties x 8 seeds x 2 bots, then the Hard retunes): a throwaway Playwright script
  that runs many pages against one build, because `dev.py smoke` runs one URL per build and waits for one marker. A seed
  and difficulty sweep in the kit would have replaced it. A second throwaway script pressed real keys (title, menu,
  Play, hold D, R, Esc, quit) to check movement, restart and quit to title under the shell.
- Everything else (assets, GIF, screenshots, checks) went through the kit's own commands.
