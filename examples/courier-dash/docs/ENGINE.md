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
src/main.ts         renderer, frame loop (setAnimationLoop + THREE.Timer), resize, BOOT_OK after the first frame
src/core/           engine-free logic: Log, follow spring, timers, math, RNG, state machines. No three import. Unit tested.
src/game/           the world: scene, camera, lights, objects, update(dt)
tests/              Vitest tests for src/core (*.test.ts)
public/assets/      models (.glb), textures, audio, fonts: served as-is at assets/... (docs/ASSET_LOG.md)
tools/              dev.py, smoke.mjs and helpers
dist/               production build (git-ignored)
```

## Conventions
- Units are meters, +Y is up, right-handed (Three.js defaults; Blender's glTF export already converts).
- Models: glTF binary (`.glb`) prepared by `tools/blender/prep_export.py`, loaded with `import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js"`.
- One `update(dt)` per frame; dt in seconds from `THREE.Timer`, clamped. Never assume 60 fps.
- Tunables in one module or JSON in public/assets/data, never literals inside logic.
- Load assets with relative paths (`assets/models/<name>.glb`), never `/assets/...` (breaks itch.io and GitHub Pages subfolders).
- **Version:** one source, the `version` field of package.json (SOP-06). Show it in game with
  `import { version } from "../package.json"` (adjust the relative path; `resolveJsonModule` is on, Vite keeps only that field).
- **Rules in `src/core`, stepped at a fixed rate,** make the whole game playable in a unit test: a scenario run in the browser
  (`?autoplay`) then replays exactly in Vitest (the kit repo's Courier Dash example does this).

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
`node_modules/`, `dist/`, `package-lock.json` (written by npm; commit it, never edit it).
