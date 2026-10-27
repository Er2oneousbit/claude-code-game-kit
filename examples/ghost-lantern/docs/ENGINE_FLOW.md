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
- Scene behavior is covered by `smoke` (boots the real build). For gameplay checks, give the scene an autoplay or
  scripted-input mode and assert on logged markers, the same way `smoke` waits for `BOOT_OK`.

## Assets and audio
- Put files in `public/assets/` (`art/`, `audio/sfx/`, `audio/music/`, `fonts/`, `maps/`) and load them by relative path.
- Bring third-party packs in with `python tools/fetch_asset.py ... --to public/assets/<kind>` (logs `ASSET_LOG.md` and the license).
- Audio: OGG plus an MP3 or M4A fallback covers every browser (Safari has had OGG gaps **(verify)**); Phaser picks the first
  the browser can play from `this.load.audio(key, [ogg, mp3])`. Music starts after the first input (autoplay policy).
- Naming: `spr_player_idle.png`, `sfx_jump_01.ogg`, `mus_level1.ogg`.

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

