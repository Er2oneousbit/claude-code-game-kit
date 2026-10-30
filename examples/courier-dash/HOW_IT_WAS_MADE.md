# How Courier Dash was made

The kit's Web 3D example, and its second "only what is in the kit" run (after ghost-lantern). One Claude Code session
(Claude Opus 5.5) on Windows 11 with Node 26, 2026-10-21. The user picked the concept; Claude did the rest by following the
kit's documents and tools, and recorded every place the kit fell short. Each gap was fixed **in the kit** during the run and
pulled into the game with `new_game.py --upgrade`, the same way any kit user gets updates.

## The rule
Allowed: what a kit user has after scaffolding (docs, SOPs, skills, `tools/`, the overlay's pinned packages) plus the
sources the kit's resource lists name. Not allowed: outside scripts or tools. Exceptions are listed at the end.

## 1. Scaffold and health check (FIRST_HOUR 0 to 5 min)
```
python scripts/new_game.py --name "Courier Dash" --engine web-3d --dest ../courier-dash --git-init
python tools/dev.py setup
python tools/dev.py doctor
```

## 2. Concept and GDD (5 to 25 min)
Claude offered four 3D concepts that each exercise a different part of the kit; the user picked "Courier Dash" (animated
character, glTF pipeline, follow camera, SOP-14 robot). The GDD got the pitch, three pillars (read the robot, every second
counts, one more run), the core loop, controls and the tunables file.

## 3. Assets: fetch, validate, prepare (25 to 50 min)
`docs/resources/art.md` names kenney.nl for prototyping. Each pack's license was read on its own page (CC0), the zip listed
with `--list`, then only the needed files taken:
```
B=https://kenney.nl/media/pages/assets; G="Models/GLB format"
python tools/fetch_asset.py --url "$B/<mini-characters zip>" --page https://kenney.nl/assets/mini-characters --author Kenney \
  --license CC0 --type 3d --base "$G" --to public/assets/models/characters --take "$G/character-female-c.glb" --take "$G/Textures/colormap.png"
(the same for City Kit Suburban, City Kit Roads, Platformer Kit and Space Kit, whose rover sits in "Models/GLTF format")
python tools/fetch_asset.py --url "$B/<interface-sounds zip>" ... --type sfx --to public/assets/audio --take "Audio/select_002.ogg" ...
```
**Kit gap 1:** Kenney models point to a colormap image in a Textures folder beside them, and `fetch_asset.py` flattened every file into
one folder, which broke that link. Fixed: `--base DIR` keeps paths below DIR.

Every model then went through `tools/blender/validate_asset.py`:
**Kit gap 2:** every Kenney model failed on UV coverage and overlap. They are palette-textured (each face samples one
swatch of a small colormap), so UV layout rules do not apply. Fixed: the validator detects palette and color-only
texturing and reports an `[info]` line instead.
**Kit gap 3:** names like `character-female-c` were flagged; hyphens are fine in glTF and every engine. Fixed in the name
rule and in `prep_export.py`'s name cleaning.
**Kit gap 5 (with a correction):** the rigged character failed on a huge `Icosphere`. Claude first blamed the Kenney file
and added `--ignore NAME` to `prep_export.py` (**kit gap 4**, still useful for real helper meshes). The real cause: Blender's
glTF importer adds that sphere as the bones' display shape. The shared import now removes it, and the earlier notes in the
kit were corrected.

The character was then prepared with the kit's one export preset:
```
python tools/blender/prep_export.py assets_src/character-female-c.glb --out public/assets/models/characters/courier.glb --pivot keep --class npc
```
(812 triangles, 32 animations, texture embedded; `--pivot keep` because a skinned model's origin is the feet already.)
**Kit gap 9:** the first export came out without its texture, and validated anyway: the source had been moved into
`assets_src/` without its `Textures/` folder, and the exporter dropped the missing image without a word. Fixed: both tools
read the glTF's own file references; `prep_export.py` refuses such a source before exporting. Exams 22/22 and 17/17.

## 4. Slice brief and budget (50 to 60 min)
`docs/VERTICAL_SLICE.md`: one town block, five parcels carried one at a time, one robot (patrol, alert, chase, search,
return), a 90 s clock, HUD, four sounds, debug flags and an autoplay bot pair; menus, saves and music out. A budget row in
`docs/ROADMAP.md` (time not measured precisely in this run; log yours). The color bible in `docs/CONCEPTS.md`.

## 5. Build (SOP-01, then SOP-14 through `/game-ai`)
**Kit gap 6:** SOP-14 had navigation, decision and debug rows for every engine except Web 3D. Added from the libraries'
npm and repo pages (E40): grid A* in `src/core` for flat levels, `@recast-navigation/three` or `three-pathfinding` for
navmeshes, `yuka` for steering and FSMs, and how to draw the AI's view in Three.js.
- **Technique:** an FSM (SOP-14 starts there; five clear modes, nothing that needs scores or plans). No ADR needed.
- **Engine-free core first, with tests:** `geom.ts` (line of sight, sight-cone rays, move and slide), `nav.ts` (grid A*
  with string pulling), `level.ts` (the town as data), `robot.ts` (perception, FSM, tank drive), `sim.ts` (the whole run,
  fixed step), `bot.ts` (two autoplay drivers), `tuning.ts`. Nothing in `src/core` imports three.
- **Fairness built in (pillar 1):** the robot only sees inside its cone, buildings block it, it always pauses in "alert" with
  a "!" before chasing, and it must turn before it drives. The cone on the ground is cut by the same ray test the AI uses.
- **Three.js side:** `GLTFLoader` and `AnimationMixer` crossfades (idle, walk, sprint, pick-up, die, emotes), each model
  fitted at runtime into its collision box from `level.ts` (Kenney's town kit is mini scale), the kit's spring follow camera,
  an HTML HUD, keyboard and gamepad. Every API was checked by `dev.py check` against `@types/three` 0.186, not memory.
- **Version (SOP-06):** 0.2.0 for the slice, read from package.json and shown in the HUD. **Kit gap 7:** the web overlays
  could not import JSON, so "the version lives in package.json" had no working example. Fixed: `resolveJsonModule` in both
  web tsconfigs, the one-line import in both ENGINE.md files.

## 6. Scenario checks (SOP-14 step 6)
Because the whole run is engine-free and fixed-step, the scenario pair is a unit test: `tests/scenario.test.ts` plays the
`careful` bot (must deliver all five with time to spare) and the `reckless` bot (must be caught) from all four robot
starts. The same runs in the browser:
```
python tools/dev.py smoke --query "autoplay&speed=4" --until RUN_WON --fail-on CAUGHT,TIME_UP --timeout 240
python tools/dev.py smoke --query "autoplay=reckless&speed=4" --until CAUGHT --fail-on RUN_WON,TIME_UP --timeout 240
```
The browser run ended with 24.7 s left, the same as the unit test for that start.

## 7. What the kit's checks caught
| Caught by | Problem | Fix |
|---|---|---|
| Scenario probe in Vitest | Careful bot caught or out of time from every start: it waited inside the cone and walked back into view during searches | Wait only when unseen, sidestep out of the cone, run for the best hidden spot when spotted. Now 4/4 wins (18 to 35 s to spare); reckless 4/4 caught |
| `smoke --screenshot` | The robot spotted and chased a courier who had not moved yet | The robot perceives nothing until the run starts, like the clock (regression test added) |
| `smoke --screenshot` | Trees twice too big; the state light floated above the rover; the red chase cone read olive over grass | Smaller canopy factor; the rover's own materials glow in the state color; cone opacity per state |
| `&top` debug camera | Needed to confirm road tiles and buildings match the collision boxes | Matches; kept as a debug flag |
| `&close` debug camera | `render_sprites.py` views of the rover were ambiguous about its front | Close-ups in the game: courier and rover both face where they move |
| `smoke --record` | Headless capture saved 38 frames of a one-minute run | `--headed` (real GPU): 425 frames. **Kit gap 8**, noted in the web-3d ENGINE.md |
| `frames_to_gif.py` | First GIF 4.5 MB | `--every 4 --width 360 --colors 32`: 1.2 MB |

## 8. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` / `test` | type check passed / 53 tests (geometry, A*, robot FSM, rules, level data, scenario pair); 60 since the review fixes below |
| `python tools/dev.py smoke` | boot in headless Chromium, real frames, no console errors, no failed requests |
| Scenario pair, browser and Vitest | careful wins, reckless caught; 4 robot starts each in Vitest |
| `python tools/doctor.py`, `python tools/check_links.py`, `python tools/publish_check.py` | healthy, no broken references, nothing that should not be published |

### Later: generated sound (ElevenLabs)
The user asked for API audio in the other example games (2026-10-23), after Graveyard Shift had it. The Kenney sounds
were replaced by sound effects generated with the kit's `tools/audio/eleven_audio.py`, plus an ambience loop the game
never had. Every file is a PLACEHOLDER (non-commercial terms) in `docs/ASSET_LOG.md` (credit in the README); the old
Kenney rows stay, marked removed. Every file was measured before use (peak, loudness, silence at the start, the jump at
a loop's seam, flat-topped samples), then peak-normalized: one-shots to -3 dBFS, loops to -6 (the log says Modified, the
evidence file keeps the shipped file's SHA-256, the `.gen.json` next to it the generated one).

| Event | File |
|---|---|
| parcel picked up / delivered | `parcel-pickup.mp3` / `parcel-delivered.mp3` |
| caught by the robot | `robot-caught.mp3` |
| the last 10 seconds | `clock-tick.mp3` |
| always, from the first key press | `town-ambience.wav` (10 s loop, HTMLAudioElement with `loop`) |

- What the measurements caught: the town ambience came back at -34 dBFS peak, too quiet to hear under anything;
  normalized. MP3 for one-shots (small), WAV for the loop (MP3 padding clicks at the seam).
- Verified: `check`, 53 tests, `smoke` (boot, no errors), and every file decoded in the smoke's own
  headless Chromium.

### Later: review fixes (2026-10-26)
A Fable code review proved six bugs with probe tests; each probe that failed is now in `tests/regressions.test.ts`
(6 of its 7 tests fail on the old code, the seventh is a control). Fixed in the game, not the kit:

| Severity | Bug | Fix |
|---|---|---|
| Medium | The robot searched forever when it last saw the courier in a gap it does not fit in (0.9 m between tree-small and the north fence): A* stopped at the nearest reachable cell, the arrival test used the unreachable spot | The search drives to `searchSpot` (the last seen spot moved to the nearest cell the robot fits in), and the approach gives up after `searchApproachSeconds` (8 s) |
| Medium | `?debug` never drew the robot's path and Three r186 warned every frame (`setFromPoints` cannot grow an empty attribute) | One position buffer of 64 points, `setXYZ` plus `setDrawRange`, frustum culling off |
| Low | A chasing robot pinned on a tree corner stayed in chase while it saw the courier | Moved less than `stuckDistance` (0.1 m) in `stuckSeconds` (0.5 s): chase follows A*; stuck again: search |
| Low | The fifth delivery in the step the clock hit zero won; the 90 s clock ran 5401 steps (float accumulation) | Clock from an integer step count (exactly 5400 steps); the step that reaches 0.0 s ends as time up first |
| Low | GDD pillar 1 said the robot "only catches what it saw coming", but touching it from behind ends the run too | Pillar reworded to match the game (the catch rule is unchanged) |
| Low | Held keys and a queued restart survived R (hold W, press R: the new run started at once) | `controls.clear()` on every reset; a key or stick held through it counts again only after release |

Scenario margins did not move: careful wins with 24.683 / 35.450 / 21.750 / 18.167 s left (robot starts 0 to 3),
reckless is caught at 13.48 / 10.70 / 1.87 / 15.47 s, in Vitest and in the browser for every start (`&start=N`:
24.7 / 35.5 / 21.8 / 18.2 s left, caught after 13.5 / 10.7 / 1.9 / 15.5 s). Verified: `check`, 60 tests, both smoke scenarios, and a `?debug&top` recording
that shows the path line.

## 9. Outside the kit (be honest)
- Model sizes for the level layout came from a throwaway Blender script that printed every model's bounds at once.
  `validate_asset.py` reports the same size per file; the batch was just faster.
- SOP-14's new Web 3D row used `npm view` for license and version facts (kit work, not game work).
- A process slip, not a kit gap: mid-run, a kit tool was copied into the game by hand instead of `--upgrade`, and the next
  upgrade rightly wrote a `.gold` conflict copy. Pull kit changes with `--upgrade`, always.
- No human playtest yet: assumptions 1 (readable robot) and 3 (one more run) are open in `docs/VERTICAL_SLICE.md`.
