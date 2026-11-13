# Web Flow (Phaser 4 + TypeScript + Vite)

Engine-specific workflow for browser games. Universal process lives in `docs/sop/`.

> **Status:** see the kit README "What was tested". Anything marked **(verify)** is the likeliest to need tweaks.
> Paste errors to Claude verbatim.

## One-time setup
1. Install Node.js 22 LTS or newer (nodejs.org; it includes npm), Git, Python 3.8+.
2. In the project: `python tools/dev.py setup`. It runs `npm install` (or `npm ci` once `package-lock.json` exists) and
   downloads the headless Chromium that `smoke` uses (Playwright, about 150 MB, once per machine).
3. `python tools/dev.py doctor`. Commit `package-lock.json` after the first install.

## Daily loop
```
python tools/dev.py run       # dev server with hot reload, opens the browser (Ctrl+C to stop)
python tools/dev.py check     # type check
python tools/dev.py test      # unit tests
python tools/dev.py smoke     # production build, boot it in headless Chromium, fail on any console error
python tools/dev.py build     # dist/ for upload
```
Add `?debug` to the page URL for debug log channels.

## Mapped to the tools
| dev.py | What it runs |
|---|---|
| `setup` | `npm ci` or `npm install`, then `node node_modules/playwright/cli.js install chromium` |
| `check` | `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json` |
| `test` | `node node_modules/vitest/vitest.mjs run` (needs at least one `tests/**/*.test.ts`) |
| `build` | `node node_modules/vite/bin/vite.js build` into `dist/` |
| `smoke` | `build`, then `node tools/smoke.mjs`: Vite preview server + headless Chromium, waits for `BOOT_OK`, runs 120 animation frames, fails on `console.error`, uncaught errors, unhandled promise rejections, failed requests and HTTP 4xx/5xx responses (a missing asset fails smoke) |
| `run` | `node node_modules/vite/bin/vite.js --open` |
| `clean` | removes `dist/` and Vite caches; `--deep` also `node_modules/` |

Every command installs dependencies first when `node_modules/` is missing or older than `package.json`.

## Adding a scene or system
1. Pure logic first in `src/core/` (no Phaser import) with a Vitest test in `tests/`.
2. The scene in `src/game/<Name>Scene.ts`, registered in the `scene` list in `src/main.ts`.
3. `python tools/dev.py check` and `test`, then `smoke` before calling it done.

## Physics
- Arcade physics (AABB, fast, fine for platformers and top-down): add `physics: { default: "arcade", arcade: { gravity: { x: 0, y: 900 }, debug: false } }`
  to the game config. Read `node_modules/phaser/skills/physics-arcade/SKILL.md`.
- Set `arcade.debug: true` while tuning: it draws every body and velocity.
- Matter.js is available for real rigid bodies (`physics-matter` skill). Record the choice in an ADR.

## Tilemaps
Tiled (mapeditor.org, free) exports JSON that Phaser loads with `this.load.tilemapTiledJSON`. Read the `tilemaps` skill. Keep
`.tmx` sources in `assets_src/` and exported `.json` in `public/assets/maps/`.

## Testing
- Vitest tests in `tests/`, named `<unit>.test.ts`, one behavior per `it`. Only engine-free code is unit tested.
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
- Scene behavior is covered by `smoke` (boots the real build). For gameplay checks, give the scene an autoplay or
  scripted-input mode and assert on logged markers, the same way `smoke` waits for `BOOT_OK`.

## The front end (shell)
The skeleton ships a complete front end around the game: boot, title ("press any key or button"), main menu (Play,
Settings, Credits, Quit, plus "Juice demo" in debug builds: the dev server or `?debug`), settings, credits (scrolls
`CREDITS.md` from the project root when it exists), a loading bar, the game, a pause menu (the `pause` action, and
automatically when the window loses focus; it also opens "What now?": the goal from `shell.setObjective()`, the last
line and the controls, and "Dialogue history" from `shell.history`, #167), quit and crash screens. Settings > Controls
offers one-handed layouts (`data/input/presets.json`, #166); `readable_font`, `line_spacing`, `subtitle_hold`,
`timing_scale` and `auto_repeat` work as SOP-20 says.
- **Narration** (#165): the shell's `narrator.ts` puts a line for every focus change, value change and screen into
  an ARIA live region (always) and speaks it with `speechSynthesis` when `access.narration` is on.
- **Where:** `src/shell/` (screens, input, subtitles, the smoke driver), `src/core/` (the engine-free logic: settings,
  bindings and glyphs, saves, i18n, juice), `data/i18n/<locale>.json` (strings), `data/dialogue/*.built.json`
  (subtitles in the dialogue format v0 of Wavesmith's dialogue subcommand). Scenes read `shell.settings`,
  `shell.input` (`isDown`, `takePress`) and `shell.volume("sfx")` from `src/shell/app.ts`. The shell imports no
  Phaser: it starts, pauses and stops scenes through `src/shell/host.ts`, which `src/game/phaserHost.ts` implements,
  so the same `src/shell/` runs over Three.js in the web-3d overlay. Keep Phaser out of `src/shell/`.
- **Screens are HTML over the canvas**, built in code: real text layout, so text size, wrapping and the
  pseudo-locale check behave like any web page. A theme: a file named `theme_default.css` in the
  `public/assets/ui` folder (loaded after the built-in `src/shell/shell.css`). Prompt glyphs:
  `public/assets/ui/glyphs/<glyph_name>.png` (key_space, xbox_a, ps_cross ...), drawn at a whole-number scale with
  nearest filtering; a missing glyph shows a text keycap.
  Dotwork's uikit lane writes the glyphs there (this game's `art_src/dotwork/dotwork.config.json` points Dotwork at
  `public/assets`). It does not write the theme: Dotwork's theme is a Godot `.tres`, so write `theme_default.css` by
  hand from the same colours. Restart `run` after adding files there.
- **Navigation:** keyboard and gamepad (the browser's standard mapping) through one input layer; `ui_accept` /
  `ui_cancel` everywhere, cancel goes back one screen, the focused item has an outline and a marker.
- **Settings** apply live and save on Back (`settings.json`, atomic, with `.bak`). A browser cannot apply
  `display.vsync` (it always syncs) or `display.resolution` (the canvas follows the window): they are kept in the
  file but not shown. Fullscreen and borderless both use the browser's Fullscreen API. The colorblind option recolors
  the juice demo's palette only (the shell's `palettes.ts`, from `data/access/colours.json`, which
  `tools/access/colour_check.py` checks; a real game declares its own pairs there). Mono audio downmixes Web Audio output.
- **Juice timing:** the FlashLimiter is always on (at most 3 full-screen flashes per real second); the
  `access.flash_limit` setting only makes each flash gentler. Hitstop and the FlashLimiter take real time; shake,
  follow, input buffer, coyote and spring take game time (after hitstop and `game_speed`).
- **User data** lives in localStorage under one key prefix (`<slug>/`, or `?data-dir=`): `settings.json`,
  `save_<slot>.json` (+ `.bak`), the game log (`game.log` in a `logs` folder: version and time on the first line, 5 older logs kept),
  `crashes/crash_<time>.txt`, `telemetry.csv`. Language > "Download my data" gives the player all of it as one file.
- **Crashes:** an uncaught error or rejected promise writes a crash file (version, seed, error, stack, log tail),
  logs `CRASH_WRITTEN` and shows the crash screen; in `smoke` it is also a console error, so the run fails.
- **Telemetry** is off until the player says yes (asked once per launch on the title screen while undecided; Later
  keeps it undecided). Events go to `telemetry.csv` on the device only (the last 2000 rows); nothing is sent anywhere. Sending it
  needs a server you run, a privacy policy that says what is collected, and an opt-out (SOP-19).
- **F8** (debug builds) saves a bug report: `bug_<time>/` with the log tail, settings and a screenshot, plus a download.
- **Localization:** every visible string goes through `shell.i18n.t(key)`; a new language is a new
  `data/i18n/<id>.json` (missing keys fall back to English). The `pseudo` locale makes every string accented, 40 %
  longer and bracketed; with `?locale=pseudo` every screen is checked as it appears and problems are console errors.

## Assets and audio
- Put files in `public/assets/` (`art/`, `audio/sfx/`, `audio/music/`, `fonts/`, `maps/`) and load them by relative path.
- Bring third-party packs in with `python tools/fetch_asset.py ... --to public/assets/<kind>` (logs `ASSET_LOG.md` and the license).
- Audio: OGG plus an MP3 or M4A fallback covers every browser (Safari has had OGG gaps **(verify)**); Phaser picks the first
  the browser can play from `this.load.audio(key, [ogg, mp3])`. Music starts after the first input (autoplay policy).
- Naming: `spr_player_idle.png`, `sfx_jump_01.ogg`, `mus_level1.ogg`.

## Dotwork art (the asset manifest importer)
Dotwork (`tools/art/dotwork/`, `/dotwork`) makes pixel art on your GPU. A web game has no Godot, so the game's
`art_src/dotwork/dotwork.config.json` sets `"engine": "none"` and `"assets_dir": "public/assets"`: every pack writes
its PNGs under `public/assets/art/` and one manifest, `public/assets/dotwork/<pack>.assets.json` (the format:
`tools/art/dotwork/ASSET_MANIFEST.md`). A pack spec that names a font by path (`tools/art/dotwork/examples/uikit.json`)
gives it relative to the assets folder ("art/ui/fonts/font_dialogue.fnt"), so the same spec works here.
- **Loader:** `src/game/dotworkPlan.ts` (no Phaser: the plan, the terrain rules, the variant pick, where every tile
  lands, bitmap font data) and `src/game/dotwork.ts` (Phaser). In a scene: `queueDotwork(this)` in `preload()`, then
  in `create()` with `const pack = dotworkPack()`: `addAnimatedSprite(this, pack, "hero", x, y, "walk_s")`,
  `playDirection(sprite, pack, "hero", "walk", "e")`, `addSprite` (a prop, its pivot on x, y, its collision rects in
  world pixels), `addMap` (a tilemap: terrain layers resolved, stamps expanded, animated tiles, flips, objects),
  `addCollisionBodies` (static Arcade bodies; the scene needs `physics: { arcade: {} }`), `addText` (a bitmap font
  label), `addNineSlice` (a UI kit part), `addBackground` (its layers; call its `update(delta)` from the scene's
  `update` to scroll them), `addParticles` (an emitter from the `particles` asset's texture and emitter JSON),
  `addImage` (a plain `image`).
- **Maps (spec 1.1.0):** a `terrain` layer resolves every cell with the spec's rule (`blob47`, `sides4` and
  `corners4` keys from `cellMask`; among the tiles with that key, the variant is picked by probability with
  `cellRoll(x, y, layer index)`, so every engine draws the same variant), a `stamps` layer places every tile of each
  stamp, and a cell with no tile for its key stays empty with one warning per layer. Every tile's image lands at the
  spec's point, the cell centre less the tile's origin: Phaser's own layouts, rows for `square` and
  `((x - y) w / 2, (x + y) h / 2)` for `isometric`, are the spec's diamond-down layout for a cell-sized tile, and
  the importer writes the plan's top-left into each tile's `pixelX`, `pixelY` so a taller iso block (an atlas with
  a bigger `tile_size`, or a tile with its own `origin`) stands on its cell too (`dotworkVerify.ts` checks Phaser's
  `tileToWorldXY` agrees with the plan where it should). Phaser draws a layer's tiles by row then column, the spec's
  order for terrain layers; a `tiles` layer that lists its cells in another order draws in row order here.
- **What Phaser gets:** frames named `<pack>/<asset>/<clip>/<i>` with the pivot as their origin, animations keyed
  `<pack>/<asset>/<clip>` with each frame's own duration (Phaser 4 lets a frame's duration replace the clip's rate;
  Phaser 3 added it, so tutorials disagree), nearest filtering. Fonts and UI kit images are already drawn at their
  `scale`: draw them at 1 (on a camera without zoom), not zoomed with the world.
- **The extra kinds** are loaded and exposed by name on the pack (`backgrounds`, `particles`, `transitions`,
  `normalMaps`, `images`): a background layer with `repeat` becomes a `TileSprite` that scrolls by its `velocity`
  (whole pixels), the others images, drawn at the layer's `scale`; a `normal_map` loads with its target
  (`load.image(key, [url, normal])`), so `this.lights.enable()` plus `setLighting(true)` on any object drawn with
  the target's texture lights it (the shader recipes under `tools/shaders/` cover the rest); a `transition` and an
  `image` are textures (`plan.transitions.get(name).texture`, `addImage`). Glyphs on a font's second page are left
  out (Phaser draws a bitmap font from one texture).
- **Checks:** `tests/dotwork.golden.test.ts` compares the importer with `data/golden/dotwork/expected.json` (the
  reference every engine matches: clips, sprites, the three maps' `terrain`, `placed` and `centres`) and holds the
  spec's hash and roll vectors; `tests/dotwork.assets.test.ts` checks every manifest of the game on disk (missing
  files, rects outside their PNGs, terrain cells with no tile, a normal map not its target's size); in a dev server
  and in `smoke`, every manifest is loaded in Phaser before the title screen (`src/game/dotworkVerify.ts`): a broken
  asset is a console error, and `smoke --until DOTWORK_VERIFY_OK` proves it ran.
- **The starter scene** (`MainScene.ts`) shows the first map, a character walking (it turns at the prop's box), the
  first prop, a 9-slice window and a label in the first font when the game has Dotwork art, and the bouncing box
  otherwise.

## Profiling
- Chrome DevTools Performance panel, and Phaser's `game.loop.actualFps`. Measure in `vite preview` (production build), not the dev server.
- Watch draw calls and texture size: pack sprites into atlases (TexturePacker or free-tex-packer) once you have more than a handful. See SOP-10.

## Packaging (release)
1. `python tools/dev.py build`. `dist/` uses relative paths, so it runs from any folder.
2. **itch.io:** zip the *contents* of `dist/` (index.html at the zip root), upload as an HTML game, set the viewport to 640x360
   (or larger, the game scales), tick "fullscreen button".
3. **GitHub Pages:** publish `dist/` (a GitHub Actions workflow that runs `npm ci && npx vite build` and deploys the folder) **(verify the current Pages action names)**.
4. Test the uploaded build in a private window on a second browser (Firefox or Safari), with sound on.

## Adopting an existing project
1. `new_game.py --adopt --engine web`: your `package.json` and `index.html` stay, the kit's versions land as `.gold` files.
2. Merge the `devDependencies` (typescript, vite, vitest, playwright) and `scripts` from `package.json.gold`.
3. Log `BOOT_OK <Game>` to the console once your first scene is running (`smoke` waits for it).
4. Keep your folder layout if it differs; tell Claude in `docs/ENGINE.md` where scenes and assets live.
5. `python tools/dev.py setup`, then `check`, `test`, `smoke`.

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| `node ... is too old` | Node below 22.12 | Install Node 22 LTS or newer |
| `smoke`: cannot start headless Chromium | Playwright browser not installed | `python tools/dev.py setup` |
| `smoke`: `[requestfailed] .../assets/...` | wrong asset path, or a leading `/` | Load with `assets/...` (relative), check the file is under `public/assets/` |
| Works in `run`, blank page from `dist/` | absolute paths, or opened as `file://` | Keep `base: "./"`, serve `dist/` (`vite preview`, itch.io), do not double-click `index.html` |
| No sound until clicking | browser autoplay policy | Expected. Start music after input |
| `Property 'x' does not exist on type ...` after copying a tutorial | Phaser 3 API in a Phaser 4 project | Check `node_modules/phaser/skills/v3-to-v4-migration/SKILL.md` |
| `No test files found` | no `tests/**/*.test.ts` | Add a test; `test` exits 2 when nothing ran |

## Field notes (reported, unverified)
None recorded yet. Add notes from videos, forums or your own runs here, with an `E##` id in `docs/EVIDENCE.md`.

## Scenario runs (smoke options)
`python tools/dev.py smoke` builds, boots the production build in headless Chromium and fails on errors. For scenario runs:
- `--query "autoplay=careful&seed=3"` is appended to the page URL, so the game reads its options from `location.search`.
- `--until MARKER` passes only if the console logs that marker; `--fail-on A,B` fails if it logs any of them.
- `--screenshot FILE` saves the last frame; `--record DIR` saves PNG frames every `--record-every` milliseconds (default 66)
  for `tools/art/frames_to_gif.py`. Headless software rendering is slow, so record 3D or WebGPU games with `--headed`.
- `--headed` uses a visible browser with the real GPU; `--gpu` adds headless WebGPU flags.
- `--drive SCENARIO` lets the game play a scripted run (`src/shell/drive.ts`) and waits for `DRIVE_DONE`
  (`DRIVE_ABORT` fails at once). The shell runs a scenario only with its own data dir (without `--data-dir`, smoke
  uses `build/smoke-data`) and only in a dev server or an automated browser, so a `?drive=` link to the hosted
  game logs `DRIVE_IGNORED` (smoke fails at once on it) and never touches the player's settings:
  - `menus`: title, settings, master volume to 0.5 (left or right from whatever the data dir held), reduce motion
    on, Back, quit; prints `SETTINGS_WRITTEN <path>` and checks the file holds the new values (and that
    `telemetry.csv` was not written without consent).
  - `crash`: plays, then throws a planted error; prints `CRASH_WRITTEN <path>`. Exit 1 is the expected result.
  - `pseudo` (with `--locale pseudo`): visits every screen and settings section; exit 0 when nothing is truncated,
    clipped or untranslated. Subtitles stand still during the tour, so the label count is the same on a slow
    machine. `pseudo-plant` adds one label that is too small: it must exit 1 naming it.
  - `show:title|settings|pause|subtitle|juice|credits` (with `--screenshot`): opens that screen, freezes it, captures it
    (credits: the first lines, standing still).
  - `access[:res=WxH][,scale=N][,pad]`: every screen reported as `ACCESS_*` lines for `tools/access/sweep.py`
    (computed colours, font sizes, text boxes and what covers them, `accessAudit.ts`); `smoke.mjs` opens the page at
    the `res=` size, `pad` presses with gamepad bindings only.
- `--data-dir DIR` maps the game's user-data folder (localStorage) onto a real folder: its files are loaded under
  the key prefix `DIR/` (`?data-dir=DIR`) before the page starts and written back afterwards, so a test reads
  `settings.json`, the game log, the crash files and `telemetry.csv` as files (and can seed a damaged `settings.json`
  first). A console line `<NAME>_WRITTEN <file>` is printed again with the real path. A folder inside `dist/` is
  refused before the build (exit 2), and smoke.mjs refuses the project's own folders (`src/`, `public/`, ...).
- `--locale ID` sets `?locale=ID` (overrides the language setting; `pseudo` for the layout check).
- `--compare BASELINE.png [--tolerance N]` runs `tools/image_diff.py` on the `--screenshot` and fails on a
  difference (N = per-channel difference allowed, 0-255). Make a baseline by copying a good screenshot.

