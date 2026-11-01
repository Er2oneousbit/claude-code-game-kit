# LÖVE Flow

Engine-specific workflow for a LÖVE 11 / Lua project. Universal process lives in `docs/sop/`.

> **Tested.** Every command below ran against LÖVE 11.5 on Windows (2026-11-01), including planted syntax and runtime
> errors. macOS and Linux packaging is not run by the kit yet: marked **(verify)**.

## Daily loop
```
python tools/dev.py check      # compile every .lua with LÖVE's LuaJIT (tools/lovecheck), nothing runs
python tools/dev.py test       # tests/test_*.lua inside LÖVE, no window
python tools/dev.py smoke      # 120 frames in a small off-screen window; fails on errors, missing BOOT_OK
python tools/dev.py run        # the game window
```
Edit in VS Code with the "Lua" extension (sumneko) and add `love` to its `Lua.workspace.library` or the "Love2D
Support" extension for completions. LÖVE has no editor: assets come from Aseprite, Tiled, LDtk and the kit's tools.

## The universal commands, mapped to LÖVE
| dev.py | What it runs |
|---|---|
| `check` | `lovec tools/lovecheck <every .lua>`: a separate tiny LÖVE program compiles each file with `loadstring` (the game's own LuaJIT) and prints `CHECK_FAIL <file> <message>` |
| `test` | `lovec . --test [--filter name]`: `tests/runner.lua` runs every `test_*` function and prints `TESTS <run> passed <p> failed <f> files <n>`; 0 tests is exit 2 |
| `smoke` | compiles conf.lua and main.lua first, then `lovec . --smoke N`: passes on `BOOT_OK` and `SMOKE_DONE` with no `[ERROR]` / `[error]` lines and exit 0. `--headless` runs with no window. `--screenshot`, `--record`, `--compare`, `--drive`, `--data-dir`, `--locale` as in `dev.py smoke -h` |
| `run` | `love .` (the GUI build) |
| `build` | zips `main.lua`, `conf.lua`, `src/`, `assets/`, `data/` (not `data/golden/`) into `build/<game>.love`; on Windows fuses `love.exe` + the .love into `build/windows/<game>.exe` and copies LÖVE's DLLs and its license file (license.txt) next to it |
| `clean` | removes `build/` (`--yes` accepted, never asks) |
| `doctor` | LÖVE found, 11.4 or newer (warns on 12), the boot files present, then `tools/doctor.py` |

Game options go after `--`: `python tools/dev.py smoke -- --seed 7` reaches the game as `KIT.rest`.

## Writing tests
```lua
-- tests/test_score.lua
local A = require("tests.assert")
local Score = require("src.core.score")
local T = {}
function T.test_combo_doubles() A.eq(Score.combo(2, 10), 40) end
return T
```
`A.eq`, `A.near(got, want, tol)`, `A.truthy`, `A.falsy`, `A.same(got, want, tol)` (deep, numbers within tol),
`A.raises(fn)`. Tests run with no window: keep `love.graphics` out of the code under test.

## Assets and audio
- Images: `love.graphics.newImage("assets/art/hero.png")` after `love.graphics.setDefaultFilter("nearest",
  "nearest")`. Sprite sheets: `love.graphics.newQuad`. Dotwork's non-Godot output (PNGs, sheets and a manifest)
  loads directly.
- Audio: `love.audio.newSource(path, "static")` for short sounds, `"stream"` for music. WAV and OGG are safe; MP3
  works through mpg123. Log every asset in `docs/ASSET_LOG.md`.
- Fonts: `love.graphics.newFont(path, size)` (TTF) or `love.graphics.newImageFont` for bitmap fonts; BMFont `.fnt`
  files load with `love.graphics.newFont("font.fnt")`.

## Profiling
- `love.timer.getFPS()` and `love.timer.getDelta()` on screen in debug builds; `collectgarbage("count")` for Lua
  memory (KB). Watch for garbage from tables created every frame.
- LuaJIT's profiler: `require("jit.p").start("Fl", "build/profile.txt")` in love.load, `.stop()` on quit (verify).

## Packaging
- **Windows:** `python tools/dev.py build` gives `build/windows/` with `<game>.exe` and the DLLs; zip that folder.
  The exe is `love.exe` with the game appended (LÖVE's documented fusing); LÖVE's zlib license file, license.txt, must ship with it.
  Change the exe's icon with a resource editor (rcedit) if you want your own (verify).
- **macOS:** copy `love.app`, put the .love in `Contents/Resources/`, edit `Info.plist` (bundle id, name); signing
  and notarization: docs/sop/SOP-21 (verify).
- **Linux:** the .love runs with an installed `love`; for a single file use an AppImage of LÖVE with the game
  fused in (verify).
- **Web:** love.js (a community port) can run 11.x games in a browser with limits (verify; no threads by default).

## Adopting an existing project
1. Run `new_game.py --adopt` into the project. Your `conf.lua` and `main.lua` stay; the kit's land as `.gold` files.
2. Copy the `KIT` parsing and `love.errorhandler` from `conf.lua.gold` into your conf.lua (without the handler a smoke
   or test error hangs).
3. Make `love.update` count frames and quit after `KIT.frames` in smoke mode, printing `BOOT_OK` once and
   `SMOKE_DONE` at the end (see `main.lua.gold`), or move your game into `src/game/game.lua` and take the kit's
   main.lua.

## Common errors
| Symptom | Cause | Fix |
|---|---|---|
| `smoke` reports "no exit after N s" | an error screen is waiting for a key | conf.lua lost its `love.errorhandler`, or an error happened in conf.lua itself |
| "love.graphics cannot function without a window!" | graphics created in a headless run (tests, `--headless`) | create graphics only when there is a window, or drop `--headless` |
| `module 'src/core/x' not found` | `require` with slashes, or a typo in the case | `require("src.core.x")`, check the file name's case |
| The fused exe closes at once | DLLs missing next to it | ship the whole `build/windows/` folder |
