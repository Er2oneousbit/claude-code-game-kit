# How Scrap Tanks was made

The kit's C++ / SDL2 example, and its third "only what is in the kit" run (after ghost-lantern and courier-dash). One
Claude Code session (Claude Opus 5.5) on Windows 11 with Visual Studio 2022 Build Tools (MSVC 14.44, bundled CMake and
vcpkg), 2026-10-21. The user picked the concept; Claude did the rest by following the kit's documents and tools, and
recorded every place the kit fell short. Each gap was fixed **in the kit** and pulled in with `new_game.py --upgrade`.

## The rule
Allowed: what a kit user has after scaffolding (docs, SOPs, skills, `tools/`, the overlay's vcpkg manifest) plus the
sources the kit's resource lists name. Not allowed: outside scripts or tools. Exceptions are listed at the end.

## 1. Scaffold and toolchain (FIRST_HOUR 0 to 5 min)
```
python scripts/new_game.py --name "Scrap Tanks" --engine cpp-sdl2 --dest ../scrap-tanks --git-init
python tools/dev.py doctor && python tools/dev.py check && python tools/dev.py test && python tools/dev.py smoke
```
A short path on purpose (vcpkg breaks on deep Windows paths, `docs/ENGINE.md`). The untouched skeleton built, tested and
smoked before any game code existed.
**Kit gap C1:** the scaffolder's next step said "set the exact engine version", which does not apply to C++ (vcpkg's
baseline pins the libraries). Fixed: the overlay's `setup_step` names `VCPKG_ROOT`, CMake and the first build.

## 2. Concept and GDD (5 to 25 min)
Claude offered three C++ concepts, each built around kit parts no example had used yet; the user picked "Scrap Tanks"
(3D models rendered to sprites, a behavior tree). The GDD got three pillars: **cover is life**, **read the raiders**,
**short and replayable**.

## 3. Assets: fetch, validate, render (25 to 60 min)
Kenney has 2D tank packs but no 3D tank, so a tank became two parts, as top-down tank games draw them anyway: a Car Kit
tractor as the hull, a Tower Defense Kit cannon as the turret.
```
python tools/fetch_asset.py --url <car-kit zip> --page https://kenney.nl/assets/car-kit --author Kenney --license CC0 \
  --type 3d --base "Models/GLB format" --to assets_src/car-kit --take "Models/GLB format/tractor.glb" ... --take "Models/GLB format/Textures/colormap.png"
(the same for the Tower Defense Kit; Sci-fi Sounds into assets/audio; Kenney Future into assets/fonts)
python tools/blender/validate_asset.py assets_src/<kit>/<model>.glb      # every model: sizes, palette texturing, no failures
python tools/make_sprites.py                                            # the project's table of render jobs
```
`tools/make_sprites.py` is one table of render jobs that calls the kit's `render_sprites.py`, as SOP-11 asks ("asset
scripts call that tool instead of exporting ad hoc"). 32 directions for hulls and turrets, a 55 degree camera.
**Kit gap C2:** `render_sprites.py` fitted every model to its own cell and centered it on its own bounds: fine for one
character, useless for a hull and a turret that must stack, or units that must share a scale. Fixed: `--world-size`
(meters per cell) and `--pivot origin`; the JSON records `pixels_per_meter` and the pivot pixel. Its fit warning first
used a bounding sphere and cried wolf; it now projects the model's vertices for every camera direction.
**Kit gap C3:** the ground tile and rocks rendered **black** in Cycles (fine in Eevee). A probe inside Blender ruled out the
texture, the filter and the normals one at a time; the cause was in the files: Kenney's Tower Defense Kit stores every
face twice, back to back, and Cycles' shadow rays hit the twin. Fixed: `render_sprites.py` removes the inner twin after
import, `validate_asset.py` warns about such meshes (twice the triangles in any engine). Exams: sprites 24/24, validate 23/23.

## 4. Slice brief, ADRs and budget (60 to 75 min)
`docs/VERTICAL_SLICE.md`: one arena, three waves, two raider types, scrap repairs; menus, saves and music out. Two ADRs:
**0001** SDL2_image, SDL2_ttf and SDL2_mixer (the overlay asks for one per library; versions recorded from the first
build) and **0002** a behavior tree over an FSM (SOP-14 asks for one when moving up the table: four prioritized behaviors
that interrupt each other would be twelve FSM transitions).

## 5. Build (SOP-01, then SOP-14 through `/game-ai`)
**Kit gap C4:** SOP-06 says a C++ game's version lives in `project(... VERSION)`, but nothing passed it into the code.
Fixed in the skeleton: `GAME_VERSION`, `--version`, and the BOOT_OK line carries it.
**Kit gap C5:** the C++ `dev.py smoke` could only boot N frames: no scenario markers, no screenshots, no way to pass game
options. Fixed to match the web overlays: game options after `--` go to `Game::configure()` (so games never edit
`main.cpp`), plus `--until`, `--fail-on`, `--timeout`, `--screenshot` and `--record` (BMP frames; `frames_to_gif.py` now reads BMP).
- **Engine-free core first, with tests:** math, a seeded xorshift RNG (portable across compilers, unlike the standard
  distributions), circle geometry, grid A* (a port of courier-dash's), a 100-line behavior-tree library, the arena,
  tactics (cover and firing spots, aim leading), the fight, the raiders' tree, two bots, and the camera math. Nothing in
  `src/core` includes SDL; the whole fight runs in doctest.
- **SDL side:** sprite rows chosen by direction (`src/core/View.hpp`, tested), depth-sorted drawing, intent labels with
  hp bars, HUD, five sounds, keyboard, mouse and gamepad, fading wrecks, a `--debug-ai` overlay with paths, spots, sight
  lines and the tree.

## 6. The scenario pair, and how it refuted the pillar
`tests/test_scenario.cpp` plays a `skilled` bot (fights from cover) and a `reckless` bot (charges) over many seeds.
| Round | Result | What it showed | Change |
|---|---|---|---|
| 1 | both lose; fights last 30 s | every hit logged with the bot's state: it walked into the open to "peek" | hold cover, let flankers come |
| 2 | stand-offs | a raider retreating, healing, returning forever | one retreat per life; the bot hunts a lone raider |
| 3 | reckless 9/12, skilled 1/12 | kills dropped +30 hp scrap right where the charger drove | numbers alone did not fix it (several tries) |
| 4 | skilled seen 54% of the time, reckless 55% | raiders aimed at the player while flanking, so whoever rounded a corner fired first | **raider guns point where they drive until FIRE** (also a visible tell) |
| 5 | stand-offs at flank spots | "sees" (center to center) is not "can hit" (room for a shell) | pick spots by the shot; threats are raiders that can hit |
| 6 | skilled 11/12, reckless 7/12; then a symmetry test failed | wall positions drifted when crates grew: one side had better cover | walls defined by their center; mirror test in `test_arena.cpp` |
| 7 | 12 seeds swung by 5 wins after a 1 m change | 12 seeds is too few to judge | **40 seeds**: skilled 25/40, reckless 10/40; the test asserts a gap (25/40 and 11/40 after the later review fixes) |
Two ideas that sounded right made things worse and were reverted: shooting the raider labelled FIRE first (it switched
targets mid-duel), and pre-aiming at the nearest flanker. **Kit gap C6:** SOP-14 said "run a scenario" but not how many
seeds or what to assert, and nothing about always-aimed AI. Its "Test it" step and a new "Worked examples" table now carry
these lessons from all three AI examples.

## 7. What the kit's checks caught
| Caught by | Problem | Fix |
|---|---|---|
| The scenario pair | Pillar 1 false as built (rounds above) | Gun-forward raiders, exposure-based cover, numbers |
| `test_arena.cpp` mirror test | Cover no longer symmetric after a size change | Walls placed by center |
| `test_arena.cpp` reachability | A spawn inside a rock's clearance after grid rounding | Spawns moved half a meter |
| `smoke --screenshot` | A dark grid over the ground (1 px gaps from fractional tiles) | Integer tile edges |
| `smoke --screenshot` | Labels hard to read; wrecks cluttering the yard | Label plates; wrecks fade after 3 s |
| `render_sprites` fit warning | The crate clipped in a 1.29 m cell | 1.4 m cell (drawn 1.84 m against a 2 m collision circle) |
| `/W4` | none: the code compiled without warnings throughout | |

## 8. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` / `test` | compiled without warnings / 41 test cases (geometry, A*, BT, arena, rules, each raider branch, camera, the pair over 40 seeds); 46 after the review fixes |
| `python tools/dev.py smoke` | boot, sprites, font and the sounds load headless (Kenney Ogg files then, WAV now) |
| Scenario pair in the game, seed 4 (seed 7 since the review fixes) | `--autoplay skilled` reaches RUN_WON, `--autoplay reckless` reaches PLAYER_DESTROYED |
| `python tools/dev.py --preset release build` | compiles; vcpkg copies the SDL, image, font and sound DLLs |
| The README steps in a fresh copy inside the kit repo | build, tests and both scenario runs pass. One `smoke` right after `test` failed once at "configure failed"; three reruns passed and the message was not captured (rerun with `--debug` if you see it) |
| `python tools/doctor.py`, `tools/check_links.py`, `tools/publish_check.py` | healthy, no broken references; the only FAIL is the license file, which lives one level up for examples |

### Later: generated sound (ElevenLabs)
The user asked for API audio in the other example games (2026-10-23), after Graveyard Shift had it. The Kenney sounds
were replaced by sound effects generated with the kit's `tools/audio/eleven_audio.py`, plus an ambience loop the game
never had. Every file is a PLACEHOLDER (non-commercial terms) in `docs/ASSET_LOG.md` (credit in the README); the old
Kenney rows stay, marked removed. Every file was measured before use (peak, loudness, silence at the start, the jump at
a loop's seam, flat-topped samples), then peak-normalized: one-shots to -3 dBFS, loops to -6 (the log says Modified, the
evidence file keeps the shipped file's SHA-256, the `.gen.json` next to it the generated one).

| Event | File |
|---|---|
| you fire / a raider fires | `tank-fire.wav` / `raider-fire.wav` |
| a shell hits / a tank is destroyed | `shell-hit.wav` / `tank-explode.wav` |
| scrap picked up | `scrap-pickup.wav` |
| always, from the first frame | `scrapyard-ambience.wav` (SDL_mixer loops it: `Mix_PlayChannel(-1, chunk, -1)`) |

- What the measurements caught: the raider's shot came back at -30 dBFS peak; retaken ("close by, a sharp loud crack")
  and normalized.
- The smoke runs with SDL's dummy audio driver, so a passing smoke does not prove the files load. A run with one file
  hidden printed `cannot load assets/audio/tank-fire.wav`; with all of them present it prints nothing.
- Verified: `check`, `test`, `smoke`.

### Later: review fixes (2026-10-26)
A review by Claude (Fable 5.1) wrote failing proof tests for each suspect; the fixed ones are now in
`tests/test_regressions.cpp` and `tests/test_arena.cpp`.
| Defect | Fix |
|---|---|
| Raiders could stand still for seconds: the spot pickers score by straight-line distance, and three spots near (19, 6.25) sit on a nav-grid island (the 0.5 m grid and the 1 m clearance seal it between the upper crates and the center rock, though a tank fits through), so `find_path` returned nothing and the tank never moved | `NavGrid` floods the cells reachable from the player start once; `find_cover` and `find_firing_spot` skip the rest; a tank with no path drives straight at its goal and slides along cover |
| A shell whose path entered a crate before the tank behind it, within one step, still hit the tank | the hit counts only when the tank comes before the first cover or edge on the step's segment |
| `--seed -1` wrapped to 2^64-1 and too-large numbers saturated | rejected with the usual usage error |
| `Mix_Init(MIX_INIT_OGG)` without `Mix_Quit`, though every sound is WAV | removed |

The pillar still holds, debug and release alike: cover 25 of 40 seeds, charging 11 of 40 (was 25 and 10). The skilled
bot now loses seed 4, so the smoke seed moved to 7 (the first where skilled wins and reckless is destroyed).

**Known limit (left as is, it would change the balance):** sight and hiding test one line between tank centers, but a
tank is 1.9 m wide, so a raider counted as hidden can still show a flank to a shell that grazes its edge, and one counted
as seen may have only its edge in view. Regeneration counts "unseen" with the 22 m sight range, so a retreating raider
heals in the open once it is more than 22 m from the player, even though a shell could still reach it.

## 9. Outside the kit (be honest)
- Three throwaway Blender probes found the black-render cause (texture samples, a Cycles variant per suspect, a count of
  back-to-back faces). The fix and an exam case went into the kit; the probes were not needed after that.
- Throwaway doctest probes printed hit logs and win counts while tuning; they became `tests/test_scenario.cpp`.
- No human playtest yet: pillars 2 and 3 are open in `docs/VERTICAL_SLICE.md`.
