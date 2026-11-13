# Web 3D Flow (Three.js + TypeScript + Vite)

Engine-specific workflow for 3D browser games. Universal process lives in `docs/sop/`. The tooling is the same as the 2D web
overlay (Phaser); only the starter files and these notes differ.

> **Status:** see the kit README "What was tested". Anything marked **(verify)** is the likeliest to need tweaks.

## One-time setup
1. Install Node.js 22 LTS or newer, Git, Python 3.8+.
2. In the project: `python tools/dev.py setup` (npm install, plus the headless Chromium that `smoke` uses).
3. `python tools/dev.py doctor`. Commit `package-lock.json` after the first install.

## Daily loop
```
python tools/dev.py run       # dev server with hot reload, opens the browser
python tools/dev.py check     # type check
python tools/dev.py test      # unit tests (src/core)
python tools/dev.py smoke     # production build in headless Chromium: boots, renders frames, fails on any console error
python tools/dev.py build     # dist/ for upload
```
`smoke` options for scenario runs (the same tool as the web overlay; this project has no copy of that overlay's docs):
- `--query "autoplay=careful&seed=3"` is appended to the page URL, so the game reads its options from `location.search`.
- `--until MARKER` passes only if the console logs that marker; `--fail-on A,B` fails if it logs any of them;
  `--timeout S` is the wait for each marker (default 30) and also lengthens the whole run.
- `--screenshot FILE` saves the last frame; `--record DIR` saves PNG frames every `--record-every` milliseconds (default 66)
  for `tools/art/frames_to_gif.py`. Headless software rendering is slow, so record 3D scenes with `--headed`.
- `--headed` uses a visible browser with the real GPU; `--gpu` adds headless WebGPU flags.

## Mapped to the tools
Same as the 2D web overlay: `tsc` for check, Vitest for test, Vite for build and run, `tools/smoke.mjs` (Vite preview +
Playwright Chromium) for smoke. The boot marker is logged by the shell (`src/shell/app.ts`) once the title screen is up,
and `src/main.ts` starts the shell only after the first rendered frame, so `BOOT_OK` also proves the renderer draws.

## 3D assets: Blender to the game
1. Model or download (CC0 first, `docs/resources/art.md`), log it (`/asset-intake`, `tools/fetch_asset.py`).
2. `tools/blender/prep_export.py <source> --out public/assets/models/<name>.glb --class <class>`: transforms applied, pivot at
   the bottom center, one glTF preset, LODs if asked, validated (SOP-11).
3. Load: `new GLTFLoader().loadAsync("assets/models/<name>.glb")`; add `gltf.scene` to your scene.
   Animations: `THREE.AnimationMixer` on `gltf.animations`, `mixer.update(dt)` each frame.
   A model from a picture or a prompt instead of step 2: `python tools/bozzetto/bozzetto.py make <name> --image <ref.png>`
   writes it to `public/assets/models/` already cleaned, exported and validated (`tools/bozzetto/README.md`).
4. Compressed models (Draco, Meshopt) need their decoders copied into `public/` **(verify the current loader setup)**.

## Assets and audio
- Everything the game loads lives under `public/assets/` (Vite serves it as-is). Names lowercase, words joined by hyphens or
  underscores, matching `docs/ASSET_LOG.md`; 3D naming and budgets follow SOP-11, 2D follows SOP-16.
- Models: `.glb` from Blender, see "3D assets" above. Sounds and music: `.ogg` (add `.mp3` only if a target browser needs it),
  loaded with three.js `AudioLoader` and played through one `AudioListener` on the camera.
- Log every third-party file with `tools/fetch_asset.py` or `/asset-intake` before it goes in (SOP-04).

## Scene basics that save time
- Lighting: a `HemisphereLight` for ambient plus one `DirectionalLight` (shadows on only where they matter; each shadow map
  costs a render pass). Environment maps (`RoomEnvironment` in the add-ons) make PBR materials look right quickly.
- Camera follow: `src/core/follow.ts` (critically damped spring, unit tested) instead of copying positions.
- Picking and interaction: `THREE.Raycaster` from the pointer.
- UI: plain HTML over the canvas, as the shell does (`src/shell/`); keep game state in TypeScript, not in the DOM.

## Testing
- Vitest for `src/core` (math, rules, AI decisions, spring follow) and the pure parts of `src/shell` (input names, the
  drives' slider steps, the string tables, the colour palettes). Nothing that needs a canvas.
- `tests/juice.golden.test.ts` and `tests/shell.golden.test.ts` run every case of `data/golden/juice.json` and
  `shell.json` (written by `tools/golden_vectors.py`, the reference for every engine) through `src/core/`. Never copy
  expected values into a test; an unknown case type fails. After the kit changes the reference, the vectors change
  and these tests say which module to fix.
- `telemetry.golden.test.ts` checks the `telemetry.csv` columns and row format (`userData.ts`) against
  `data/golden/telemetry.json`, so every engine writes the same file.
- `credits.test.ts` checks the credits screen's text (`credits.ts` in the shell: HTML comments, heading marks, list
  markers and emphasis stars out of CREDITS.md, the same rule on every engine) against `data/golden/credits.json`.
- `dialogue.golden.test.ts` checks the subtitle typewriter (`revealCount` in `dialogue.ts`) against
  `data/golden/dialogue.json` (written by `python tools/audio/wavesmith/wavesmith.py dialogue vectors --write`).
- `tests/atomicFile.test.ts` proves the crash-safe write on the real filesystem (a temp folder).
- Smoke boots the real build; give the game an `?autoplay` or scripted mode for scenario checks (SOP-14 step 6).

## The front end (shell)
The skeleton ships the same front end as the 2D web overlay, file for file (`src/shell/`): boot, title ("press any
key or button"), main menu (Play, Settings, Credits, Quit, plus "Juice demo" in debug builds: the dev server or
`?debug`), settings, credits (scrolls `CREDITS.md` from the project root when it exists), a loading bar, the game, a
pause menu (the `pause` action, and automatically when the window loses focus; it also opens "What now?": the goal
from `shell.setObjective()`, the last line and the controls, and "Dialogue history" from `shell.history`), quit and
crash screens. Settings > Controls offers one-handed layouts (`data/input/presets.json`); `readable_font`,
`line_spacing`, `subtitle_hold`, `timing_scale` and `auto_repeat` work as SOP-20 says.
- **How it meets Three.js:** the shell imports no `three`. It talks to the renderer through `src/shell/host.ts`
  (start, pause, resume and stop a world, the backdrop, the frame cap, volume and mono, a screenshot), which
  `src/game/threeHost.ts` implements: one `setAnimationLoop`, the running world (`main` = Play in `Game.ts`, `juice`
  = `JuiceWorld.ts`, each built fresh on every start) or the still `Backdrop.ts` behind the menus. A throw in a
  world's `update` goes to the crash screen. Keep `src/shell/` free of `three` imports: then a shell fix from the web
  overlay (or to it) carries across by copying the file.
- **Narration:** `narrator.ts` puts a line for every focus change, value change and screen into an ARIA live region
  (always) and speaks it with `speechSynthesis` when `access.narration` is on.
- **Screens are HTML over the canvas**, built in code: real text layout, so text size, wrapping and the pseudo-locale
  check behave like any web page. A theme: a file named `theme_default.css` in the `public/assets/ui` folder (loaded
  after the built-in `src/shell/shell.css`). Prompt glyphs: `public/assets/ui/glyphs/<glyph_name>.png` (key_space,
  xbox_a, ps_cross ...); a missing glyph shows a text keycap. Restart `run` after adding files there.
- **Navigation:** keyboard and gamepad (the browser's standard mapping) through one input layer
  (`src/shell/input.ts`); worlds read the same layer (`shell.input.isDown`, `takePress`, `stick`, `triggers`).
- **Settings** apply live and save on Back (`settings.json`, atomic, with `.bak`). A browser cannot apply
  `display.vsync` or `display.resolution`: they stay in the file but are not shown. The frame cap skips animation
  frames in `threeHost.ts`. Three.js has no sound system of its own: `host.sound` holds the master volume and mono
  setting, and `game.setListener(listener)` (the exported host in `src/main.ts`) applies them to your
  `THREE.AudioListener`. The colorblind option recolours the juice demo's palette only (`palettes.ts`, from
  `data/access/colours.json`, which `tools/access/colour_check.py` checks; the demo draws it unlit, so what is on
  screen is what was checked).
- **User data** lives in localStorage under one key prefix (`<slug>/`, or `?data-dir=`): `settings.json`,
  `save_<slot>.json` (+ `.bak`), the game log, `crashes/crash_<time>.txt`, `telemetry.csv`. Language > "Download my
  data" gives the player all of it as one file. **Crashes** write a crash file, log `CRASH_WRITTEN` and show the crash
  screen. **Telemetry** is off until the player says yes and stays on the device. **F8** (debug builds) saves a bug
  report (`bug_<time>/`: log tail, settings, a screenshot of the canvas) plus a download.
- **Localization:** every visible string goes through `shell.i18n.t(key)`; a new language is a new
  `data/i18n/<id>.json` (`python tools/check_i18n.py` names missing keys). The `pseudo` locale makes every string
  accented, 40 % longer and bracketed; with `?locale=pseudo` every screen is checked as it appears.

## The juice demo
`src/game/JuiceWorld.ts` is the web overlay's juice demo on a side-on 3D stage, in meters (the 2D numbers at 40 px per
meter): walk and jump with a follow camera (`followCamera.ts` on the x/y plane, the camera on +z), an input buffer and
coyote time; attack the box for trauma shake (the camera moves and rolls), hitstop, a spring squash (x and z scale
together) and a white flash quad in front of the camera; hold interact to guard. `src/core/` holds the modules, the
same as the web overlay's and checked against `data/golden/juice.json`; `follow.ts` is a 3D spring for a
third-person camera. The FlashLimiter is always on; `access.flash_limit` only makes flashes gentler. Hitstop and the
FlashLimiter take real time; shake, follow, buffer, coyote and spring take game time (after hitstop and game_speed).

## Scenario runs (smoke options)
`python tools/dev.py smoke` builds, boots the production build in headless Chromium and fails on errors.
- `--query "autoplay=careful&seed=3"` is appended to the page URL, so the game reads its options from `location.search`.
- `--until MARKER` passes only if the console logs that marker; `--fail-on A,B` fails if it logs any of them.
- `--screenshot FILE` saves the last frame; `--record DIR` saves PNG frames every `--record-every` milliseconds
  (record 3D with `--headed`: headless software rendering is slow).
- `--drive SCENARIO` lets the game play a scripted run (`src/shell/drive.ts`) and waits for `DRIVE_DONE`
  (`DRIVE_ABORT` fails at once). The shell runs a scenario only with its own data dir (without `--data-dir`, smoke
  uses `build/smoke-data`) and only in a dev server or an automated browser, so a `?drive=` link to the hosted game
  logs `DRIVE_IGNORED` and never touches the player's settings. While a drive runs, the real keyboard, mouse and
  pads are ignored:
  - `menus`: title, settings, master volume to 0.5, reduce motion on, Back, quit; prints `SETTINGS_WRITTEN <path>`
    and checks the file holds the new values.
  - `crash`: plays, then the play world throws a planted error; prints `CRASH_WRITTEN <path>`. Exit 1 is the
    expected result.
  - `pseudo` (with `--locale pseudo`): visits every screen and settings section; exit 0 when nothing is truncated,
    clipped or untranslated. `pseudo-plant` adds one label that is too small: it must exit 1 naming
    `plant.too_small`.
  - `show:title|settings|pause|subtitle|juice|credits` (with `--screenshot`): opens that screen, freezes the world,
    captures it (credits: the first lines, standing still).
  - `access[:res=WxH][,scale=N][,pad][,read]`: every screen reported as `ACCESS_*` lines for
    `python tools/access/sweep.py` (five runs: 1080p, 200 % text, the readable font, and the Steam Deck size with
    the gamepad only).
- `--data-dir DIR` maps the game's user-data folder (localStorage) onto a real folder: its files are loaded under
  the key prefix `DIR/` (`?data-dir=DIR`) before the page starts and written back afterwards, so a test reads
  `settings.json`, the game log, the crash files and `telemetry.csv` as files (and can seed a damaged `settings.json`
  first). A console line `<NAME>_WRITTEN <file>` is printed again with the real path. A folder inside `dist/` is
  refused before the build (exit 2), and smoke.mjs refuses the project's own folders (`src/`, `public/`, ...).
- `--locale ID` sets `?locale=ID` (overrides the language setting; `pseudo` for the layout check).
- `--compare BASELINE.png [--tolerance N]` runs `tools/image_diff.py` on the `--screenshot` and fails on a
  difference (N = per-channel difference allowed, 0-255). Make a baseline by copying a good screenshot.

## Profiling
- `renderer.info.render` (draw calls, triangles) and `renderer.info.memory` (geometries, textures) each frame in a debug
  overlay; Chrome DevTools Performance. Merge static meshes, use instancing (`InstancedMesh`) for repeats, keep textures
  power-of-two and compressed where possible. Measure in `vite preview`, not the dev server. SOP-10.

## Packaging (release)
Same as the 2D web overlay: `python tools/dev.py build`, zip the contents of `dist/` for itch.io (HTML game), or publish
`dist/` to GitHub Pages. Test the uploaded build in a second browser, with a low-end GPU if you can.

## Adopting an existing project
1. `new_game.py --adopt --engine web-3d`; merge `package.json.gold` (scripts and devDependencies).
2. Log `BOOT_OK <Game>` to the console after your first rendered frame (or keep the kit's shell: hand your renderer
   to it through a `GameHost`, as `src/game/threeHost.ts` does, and it logs `BOOT_OK` for you).
3. `python tools/dev.py setup`, then `check`, `test`, `smoke`.

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| Black screen, no errors | camera inside an object, no lights for a lit material, or not rendering each frame | Check camera position and `lookAt`, add a light, confirm `setAnimationLoop` runs |
| Model invisible or huge | units (cm vs m) or no pivot fix | Re-export with `prep_export.py`; check with `validate_asset.py` |
| Colors washed out | texture color space | `texture.colorSpace = THREE.SRGBColorSpace` for color maps |
| Memory grows over time | removed objects never disposed | Dispose geometries, materials and textures (Gotcha 3) |
| `'X' is deprecated` warnings | tutorial code from an older Three.js | Use the replacement named in the warning |
| `smoke`: WebGL context fails | headless GPU blocked on this machine | `dev.py smoke --headed`, or `--gpu` **(verify)** |

## Field notes (reported, unverified)
None recorded yet. Add notes with an `E##` id in `docs/EVIDENCE.md`.
