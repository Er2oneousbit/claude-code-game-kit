# Engine: LÖVE 11 (Lua)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **LÖVE version:** SET EXACT VERSION HERE. The kit is tested on LÖVE 11.5 (LuaJIT, Lua 5.1 syntax); 11.4 is the
  floor. LÖVE 12 changes APIs: move only with an ADR. `conf.lua` sets `t.version = "11.4"`, the oldest LÖVE the
  game supports: a LÖVE that does not list that version as compatible shows a modal warning box, which hangs
  automated runs. Raise it only together with `MIN_LOVE` in `tools/dev.py`.
- **Binary:** set env var `LOVE_BIN` to `love.exe` (Windows; the console build `lovec.exe` next to it is used for
  check, test and smoke) or put `love` on PATH. On Windows the official zip is enough, no installer needed.
  `python tools/dev.py doctor` verifies.
- **Language:** Lua 5.1 as LuaJIT runs it (no `goto` in 5.1 style code, no integer division `//`, no `utf8` library:
  use LÖVE's `utf8` module, `require("utf8")`).
- **Tests:** the project's own runner, `tests/runner.lua`, runs inside LÖVE with no window: files `tests/test_*.lua`
  return a table of `test_*` functions; assertions in `tests/assert.lua`. No LuaRocks or busted needed.

## Layout
```
conf.lua            window, identity, the command line (KIT) and the error handler (read before main.lua)
main.lua            boot only: run modes (smoke, capture, test) around the shell
src/version.lua     the game's name and version (title screen, log, crash files read it)
src/core/           engine-free logic (juice, settings, saves, i18n, JSON, atomic files, ...): no love.graphics,
                    so tests load them; checked against data/golden/*.json
src/shell/          the runtime front end: app.lua (screen stack, settings applied, user data), screens/, drive.lua
                    (smoke scenarios), ui.lua + widgets.lua (menus, focus, the pseudo-locale layout check)
src/game/           gameplay; game.lua is what the play screen runs
assets/             art, audio, fonts (see docs/ASSET_LOG.md); assets/ui/glyphs/<name>.png = button prompts
data/               tunables and tables; i18n/<locale>.json strings, dialogue/*.built.json subtitles;
                    data/golden/ is test data, not packaged
shaders/kit/        the kit's shader recipes as LÖVE pixel shaders, *.glsl + params.lua (generated)
tests/              runner.lua, assert.lua, helpers/, test_*.lua
tools/              dev.py, lovecheck/ (the syntax checker), shadercheck/ (compiles and draws the shader recipes)
build/              .love and the fused Windows exe (git-ignored)
```

## Conventions
- Files `snake_case.lua`; a module returns one table; classes are tables with `__index` and a `new` function
  (`CoyoteTimer.new(0.1)`, methods called with `:`). No globals except `KIT` (set by conf.lua) and `love`.
- `local` everything. Tunables in a constants block at the top of the file. No magic numbers in logic.
- Gameplay timing in `love.update(dt)`, drawing in `love.draw()`. Multiply by `dt`. For physics that must not drift
  with frame rate, step a fixed timestep (accumulate `dt`, step 1/60 at a time).
- Logging through `src/core/log.lua` (`Log.info("physics", "msg")`), never bare `print` in game code. The shell
  copies every line into game.log in the user-data folder's logs folder.
- Engine-free logic in `src/core/` or `src/game/logic/` with no `love.*` calls, so tests run it without a window.
- Input as actions, not keys: the game gets `Game.action("jump")` and asks `app.input:is_down("move_left")`, so
  rebinding in Settings just works. Analog: `app.input:move_vector()` (the left stick, the player's radial deadzone
  and invert_y applied, up is -y), `app.input:triggers()` (0 to 1) and `app.input:held_actions()`; the stick also
  holds `move_*`. Every visible string goes through `app:t("key")` (`data/i18n/en.json`).
- User data (settings, saves, logs, crashes, telemetry) only through `src/core/text_store.lua` and
  `atomic_file.lua`, never `love.filesystem.write` directly: `--data-dir` and crash safety depend on it.
- **Shaders:** `local fx = love.graphics.newShader("shaders/kit/flash.glsl")`, then `fx:send("u_amount", 1)` and
  `love.graphics.setShader(fx)` around the draw; `require("shaders.kit.params")` holds each recipe's defaults (send
  every one: GLSL leaves them at zero). A second picture goes in as `fx:send("kit_aux", image)`, `setColor` tints
  the result. Coordinates run 0 to 1 over the drawn image: `u_texel` is one over its size in texels, `u_canvas` the
  size pixel parameters (`light_pos`) are given in. Post effects (`crt`, `vignette`, `colorblind`) draw a Canvas of
  the whole frame through them. `check` compiles them and `smoke --shaders` compares each with its golden image;
  both open a small window off-screen (`--headless` cannot draw shaders).

## Gotchas (Claude: read before editing)
1. **LÖVE's error screen waits for a key, even with no window.** conf.lua replaces `love.errorhandler` so automated
   runs exit 1 instead of hanging. Keep that code in conf.lua, not main.lua: a syntax error in main.lua happens
   before main.lua could install anything. A syntax error in conf.lua itself is caught by `dev.py smoke` and
   `check` before LÖVE starts the game.
2. **No window, no graphics.** With `t.window = false` (tests, `smoke --headless`) every `love.graphics.new*` call
   errors ("cannot function without a window") and drawing calls crash LÖVE outright (verified on 11.5). Create
   images, fonts and canvases in `love.load` only if the game is not headless, or let `smoke` use its default small
   window.
3. **The smoke window is real but off-screen** (640x360, borderless, at -20000,-20000), so it renders every frame and
   catches drawing errors. Captures draw into a canvas and save the canvas: reading back an off-screen or covered
   window gives undefined pixels on some drivers.
4. **love.filesystem only writes inside the save folder** (`love.filesystem.getSaveDirectory()`, named by
   `t.identity`). Use `io.open` for an absolute path (screenshots, `--data-dir` in tests).
5. **`require` uses dots, not slashes**: `require("src.core.log")`. Paths in love.filesystem are relative to the
   game folder (or the .love) and case-sensitive inside a .love, even on Windows.
6. **Pixel art:** call `love.graphics.setDefaultFilter("nearest", "nearest")` before loading images, and scale by
   whole numbers from the 640x360 base.
7. **No rename in love.filesystem.** Atomic saves in the save folder write `<file>.tmp`, verify it, then write
   `<file>.bak` and `<file>`; with `--data-dir` (real files) they rename for real (atomic on POSIX; on Windows a
   rename does not replace, so the target is removed first there). A load that finds `<file>` missing next to a
   `.tmp` that parses (a crash between that remove and the rename) renames the `.tmp` back and logs "recovered".
   `io.open`, `os.remove` and `os.rename` take a path in the Windows code page, so a path with "Í" or a curly quote
   fails through them; for files by absolute path use `TextStore.file` (`require("src.core.text_store")`), which
   calls the wide C runtime functions there.
8. **API verification:** LÖVE 11 and 12 differ (for example `love.graphics.setColor` takes 0..1 since 11.0, not
   0..255). Check `lovec --version` and the matching wiki page (love2d.org/wiki) before using an unfamiliar API.

## Generated or binary (do not hand-edit)
`build/` (the .love and the fused exe), anything under the save folder, `shaders/kit/` (edit
`tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).
