# Engine: Web 3D (Three.js + TypeScript + Vite)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Runtime:** Node.js 22.12 or newer (with npm). **Renderer:** Three.js 0.186.1 (r186), types from `@types/three` 0.186.0.
  **Language:** TypeScript 7 (strict). Same tooling as the 2D web overlay: Vite 8, Vitest 5, Playwright 1.64 for `smoke`.
- **First run:** `python tools/dev.py setup`, then `python tools/dev.py doctor`.
- **Three.js is a renderer, not an engine.** It draws scenes; you write the game loop, input, physics choice, audio and UI
  (or add libraries for them, each with an ADR).
- **API reference:** threejs.org/docs for r186, and the version-matched examples in `node_modules/three/examples/jsm/`
  (loaders, controls, post-processing, physics helpers). Three.js changes between releases: check
  `node_modules/three/build/three.core.js` warnings and the official migration notes before copying old tutorials.

## Layout
```
index.html          full-window page, loads src/main.ts
src/main.ts         renderer, the worlds, hands the host to the shell after the first rendered frame
src/core/           engine-free logic: Log, juice (shake, hitstop, ease, follow camera, follow spring, buffer, coyote,
                    spring, flash limiter, hold toggle, auto repeat), settings, bindings, saves, i18n, user data, dialogue,
                    audio director, music director, audio access, analog (stick deadzone and trigger shaping for
                    navigator.getGamepads values). No three import. Unit tested (golden vectors).
src/shell/          the front end: HTML screens over the canvas, input, subtitles, smoke driver (no three import; the
                    same files as the 2D web overlay's, host.ts is all it knows of the renderer)
src/game/           threeHost.ts (frame loop, worlds, pause, frame cap, screenshot), Game.ts (play), JuiceWorld.ts
                    (the juice demo), Backdrop.ts (behind the menus), dotwork/ (the Dotwork asset manifest importer),
                    character.ts (a rigged glTF character: load, play a clip on a loop)
data/               i18n/<locale>.json strings, dialogue/*.built.json subtitles, access/colours.json, golden/ vectors
tests/              Vitest tests for src/core, the pure parts of src/shell and the Dotwork importer (*.test.ts)
public/assets/      models (.glb), textures, audio, fonts: served as-is at assets/... (docs/ASSET_LOG.md);
                    Dotwork writes here (art/, dotwork/<pack>.assets.json, ui/glyphs/: art_src/dotwork/dotwork.config.json)
src/shaders/        the kit's shader recipes (kit/ generated from tools/shaders/) and their glue
tools/              dev.py, smoke.mjs and helpers
dist/               production build (git-ignored)
```

## Conventions
- Units are meters, +Y is up, right-handed (Three.js defaults; Blender's glTF export already converts).
- Models: glTF binary (`.glb`) prepared by `tools/blender/prep_export.py` or made by `tools/bozzetto/bozzetto.py` (its
  default folder here is `public/assets/models/`; a Bozzetto model loaded in the smoke run, K01), loaded with `import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js"`.
  A vertex-coloured model (`--material vertex`, glTF `COLOR_0`) needs nothing extra: GLTFLoader turns `vertexColors` on
  by itself when a mesh has colours (three r186 source).
- **Rigged characters (glTF with clips, #290):** a `.glb` with a skin and animations (a Bozzetto `rig make` result:
  Mixamo bone names, clips `idle`, `walk` ...) goes in `public/assets/models/`. `src/game/character.ts` wraps the
  AnimationMixer: `const hero = await loadCharacter("assets/models/hero_rigged.glb")` in a world's `load()`,
  `scene.add(hero.root)`, `hero.play("walk")` (loops; `{ loop: false }` plays once and holds; 0.2 s crossfade), and
  `hero.update(dt)` every frame. Three.js strips `:` from node names: `mixamorig:Hips` is `mixamorigHips`
  (`boneName()` converts). No root motion: the clips play in place and the game moves `hero.root`. Metres, +Y up;
  glTF's front is +Z and `Object3D.lookAt()` turns a model's +Z toward its target, so `hero.root.lookAt(x, y, z)`
  faces where it walks. `hero.play(name)` restarts the clip from its start (`AnimationAction.reset()`): call it when
  the clip changes, not every frame. Tested 2026-11-11 (three r186): `tests/character.test.ts` (6 Vitest tests, in
  Node: the golden character has no textures) loads `data/golden/character/character.glb`, finds `idle` and `walk` at
  their lengths, plays `walk` 30 frames and checks `mixamorigLeftUpLeg` swings as far as `expected.json` says and no
  further, loops with the clip's length as its period at 1x, plays once, height 1.8 m; `check`, `test` (184) and
  `smoke` passed on a fresh scaffold. Drawing it in the browser is not in a test yet **(verify: the smoke run loads
  a static Bozzetto model, K01, not a skinned one)**.
- One `update(dt)` per frame; dt in seconds from `THREE.Timer`, clamped. Never assume 60 fps.
- Input: read it through `shell.input` (`import { shell } from "../shell/app"`): `isDown(action)` / `takePress(action)`
  for the player's bindings, `stick()` (the left stick with the player's radial deadzone and invert_y, up is -y),
  `triggers()` (0 to 1) and `heldActions()`. Settings: `shell.settings` (`access.game_speed` scales dt in Game.ts).
- A new world (level, minigame): a class with `scene`, `camera`, `update(dt)`, `resize(aspect)` (and `load(progress)`
  for models) registered in src/main.ts; the shell starts, pauses and stops it, and a throw in `update` shows the
  crash screen with a crash file.
- Tunables in one module or JSON in public/assets/data, never literals inside logic.
- Load assets with relative paths (`assets/models/<name>.glb`), never `/assets/...` (breaks itch.io and GitHub Pages subfolders).
- **Version:** one source, the `version` field of package.json (SOP-06). Show it in game with
  `import { version } from "../package.json"` (adjust the relative path; `resolveJsonModule` is on, Vite keeps only that field).
- **Rules in `src/core`, stepped at a fixed rate,** make the whole game playable in a unit test: a scenario run in the browser
  (`?autoplay`) then replays exactly in Vitest (the kit repo's Courier Dash example does this).

- **Dotwork art** (`public/assets/dotwork/<pack>.assets.json`, spec `tools/art/dotwork/ASSET_MANIFEST.md`): in a world's
  `load()`, `const lib = await DotworkLibrary.load(DOTWORK_MANIFESTS, progress)` (src/game/dotwork/), then
  `lib.animated("hero", { ppu })` (`playDirection("walk", "e")`), `lib.sprite`, `lib.map`, `lib.text`, `lib.icon`,
  `lib.portrait`, `lib.nineSlice`; call `update(dt, camera)` on each every frame. The diorama look: one world unit per
  map tile, tiles flat on the ground (map y is +Z), sprites as billboards turning around y, nearest filtering, alphaTest.
  `dev.py test` checks every manifest's files (tests/dotwork.manifests.test.ts) and `smoke` loads them all in the
  browser before BOOT_OK. Restart `dev.py run` after Dotwork writes a new pack (the list is made at build time).

- **Shaders:** `kitMaterial("toon_rim", { albedo: [0.2, 0.6, 0.9] }, texture)` (src/shaders/kitMaterial.ts) returns a
  ShaderMaterial for any UV-mapped mesh (a sprite plane, a full-screen quad for post effects, a model); set
  `material.uniforms.u_<name>.value` each frame to animate it (`u_time` for `scroll_water`). `kitTexture()` sets
  nearest filtering for pixel art. `check` compiles every recipe and `smoke --shaders` renders each in headless
  Chromium and compares it with its golden image.

## Gotchas (Claude: read before editing)
1. **Old tutorials break.** Three.js renames and deprecates often (for example `THREE.Clock` is deprecated since r183, use
   `THREE.Timer`; legacy lighting modes were removed). Verify against the installed version, never memory.
2. **Import add-ons from `three/addons/...`** (the package export map), not from deep `examples/jsm` paths with copied files.
3. **Dispose what you remove:** `geometry.dispose()`, `material.dispose()`, `texture.dispose()` when objects leave for good.
   Removing from the scene does not free GPU memory; long sessions leak otherwise.
4. **Color:** set `texture.colorSpace = THREE.SRGBColorSpace` on color (albedo) textures you create yourself; GLTFLoader does
   it for you. Wrong color space looks washed out or too dark.
5. **No physics built in.** Pick one with an ADR (for example Rapier or cannon-es, **verify licenses and versions**), or keep
   simple collision in `src/core` where it is testable.
6. **WebGL by default.** `three/webgpu` exists, but WebGL reaches more players and runs in the headless smoke browser
   (software rendering). Smoke proves boot and logic, not frame rate (SOP-10). For `smoke --record` (GIFs, trailers) add
   `--headed`: software WebGL captured 38 frames of a one-minute run, the real GPU 425.
7. **Never put secrets in client code** (everything in src/ and public/ ships to players).
8. **Do not edit** `node_modules/` or `dist/`. No `npm install <pkg>` without an ADR: every dependency ships to players.

## Generated (do not hand-edit)
`node_modules/`, `dist/`, `package-lock.json` (written by npm; commit it, never edit it),
`src/shaders/kit/` (edit `tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).
