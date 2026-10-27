# Engine: Web (Phaser 4 + TypeScript + Vite)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Runtime:** Node.js 22.12 or newer (with npm). **Framework:** Phaser 4.2.1. **Language:** TypeScript 7 (strict).
- **Tooling:** Vite 8 (dev server, build), Vitest 5 (unit tests), Playwright 1.64 (headless Chromium for `smoke`). Versions are pinned exactly in `package.json`; `package-lock.json` is committed after the first install.
- **First run:** `python tools/dev.py setup` (npm install + the headless browser), then `python tools/dev.py doctor`.
- **Phaser API reference:** the installed package ships official agent skills, version-matched: `node_modules/phaser/skills/<topic>/SKILL.md` (scenes, sprites-and-images, physics-arcade, tilemaps, input-keyboard-mouse-touch, audio-and-sound, cameras, animations, loading-assets, ...). **Read the matching one before using an API you have not used in this project.** Most tutorials online are Phaser 3: check `node_modules/phaser/skills/v3-to-v4-migration/SKILL.md` before copying one.

## Layout
```
index.html          page shell, loads src/main.ts
src/main.ts         creates the Phaser.Game (size, scale mode, scene list)
src/core/           engine-free logic: Log, timers, math, RNG, state machines. No Phaser import. Unit tested.
src/game/           scenes and game objects (Phaser lives here)
tests/              Vitest tests for src/core and pure parts of src/game (*.test.ts)
public/assets/      images, audio, fonts, tilemaps: served as-is at assets/... (see docs/ASSET_LOG.md)
tools/              dev.py, smoke.mjs and helpers
dist/               production build (git-ignored): what you upload
```

## Conventions
- `PascalCase` classes and scene files (`MainScene.ts`), `camelCase` functions, variables and other files, `UPPER_SNAKE` constants.
- One scene per file. Scene keys are short lowercase strings (`"main"`, `"hud"`).
- **Version:** one source, the `version` field of package.json (SOP-06). Show it in game with
  `import { version } from "../package.json"` (adjust the relative path; `resolveJsonModule` is on, Vite keeps only that field).
- Load assets in `preload()` with paths relative to the page (`this.load.image("player", "assets/art/player.png")`), never `/assets/...` (breaks itch.io and GitHub Pages subfolders).
- Tunables in one module (for example `tuning.ts` in src/game) or JSON in public/assets/data, never literals inside logic.
- Use the `dt` from `update(time, delta)` (milliseconds, convert to seconds and clamp), never assume 60 fps.
- Errors: `Log.error` for anything wrong at runtime. It reaches the console, and `smoke` fails on console errors.

## Gotchas (Claude: read before editing)
1. **Phaser 4, not 3.** Many APIs moved or changed (pipelines became render nodes, FX and masks became filters, some game objects were removed, the Canvas renderer is deprecated). Verify against `node_modules/phaser/skills/` or `node_modules/phaser/types/phaser.d.ts`, never memory.
2. **Import style:** `import * as Phaser from "phaser"` (the package exports a namespace).
3. **Audio is locked until the first click or key** (browser autoplay policy). Start music after a user gesture; Phaser's sound manager unlocks on the first input.
4. **Never put secrets in client code.** Everything in `src/` and `public/` is downloaded by every player, including API keys and `.env` values prefixed `VITE_`. Anything that needs a key goes behind a server you run.
5. **`public/` vs `src/`:** files in `public/` are copied untouched and referenced by path. Files imported from `src/` are bundled and renamed with a hash.
6. **Arcade physics bodies** need `this.physics.add...` (or `this.physics.add.existing(obj)`); a plain `this.add.sprite` has no body. Enable arcade physics in the game config first.
7. **Headless smoke uses software rendering** (SwiftShader). It proves boot and logic, not frame rate. Measure performance in a real browser (SOP-10).
8. **Do not edit** `node_modules/` or `dist/`. Do not run `npm install <pkg>` without an ADR (`/adr`): every dependency ships to players.

## Generated (do not hand-edit)
`node_modules/`, `dist/`, `package-lock.json` (written by npm; commit it, never edit it).
