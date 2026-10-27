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
Playwright Chromium) for smoke. The boot marker is logged by `src/main.ts` after the first rendered frame.

## 3D assets: Blender to the game
1. Model or download (CC0 first, `docs/resources/art.md`), log it (`/asset-intake`, `tools/fetch_asset.py`).
2. `tools/blender/prep_export.py <source> --out public/assets/models/<name>.glb --class <class>`: transforms applied, pivot at
   the bottom center, one glTF preset, LODs if asked, validated (SOP-11).
3. Load: `new GLTFLoader().loadAsync("assets/models/<name>.glb")`; add `gltf.scene` to your scene.
   Animations: `THREE.AnimationMixer` on `gltf.animations`, `mixer.update(dt)` each frame.
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
- UI: plain HTML over the canvas is simplest; keep game state in TypeScript, not in the DOM.

## Testing
- Vitest for `src/core` (math, rules, AI decisions, spring follow). Nothing that needs a canvas.
- Smoke boots the real build; give the game an `?autoplay` or scripted mode for scenario checks (SOP-14 step 6).

## Profiling
- `renderer.info.render` (draw calls, triangles) and `renderer.info.memory` (geometries, textures) each frame in a debug
  overlay; Chrome DevTools Performance. Merge static meshes, use instancing (`InstancedMesh`) for repeats, keep textures
  power-of-two and compressed where possible. Measure in `vite preview`, not the dev server. SOP-10.

## Packaging (release)
Same as the 2D web overlay: `python tools/dev.py build`, zip the contents of `dist/` for itch.io (HTML game), or publish
`dist/` to GitHub Pages. Test the uploaded build in a second browser, with a low-end GPU if you can.

## Adopting an existing project
1. `new_game.py --adopt --engine web-3d`; merge `package.json.gold` (scripts and devDependencies).
2. Log `BOOT_OK <Game>` to the console after your first rendered frame.
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
