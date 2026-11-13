# Engine: C++17 + SDL3 (custom engine)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Language:** C++17 (set `CMAKE_CXX_STANDARD` in `CMakeLists.txt` if you move to 20). **Compilers:** MSVC (VS 2022), GCC, Clang.
- **Build system:** CMake 3.21+ with `CMakePresets.json`. **Dependencies:** vcpkg manifest mode (`vcpkg.json`).
- **Env var:** `VCPKG_ROOT` must point at vcpkg (the presets use `$env{VCPKG_ROOT}`). On Windows the copy inside VS Build Tools works. `vcpkg.json` is pinned with `builtin-baseline`; keep it.
- **Path length:** keep the project at a short path on Windows; deep paths break vcpkg's dependency builds (see `docs/ENGINE_FLOW.md`).
- **Libraries:** SDL3 3.4 (window, input, renderer, audio). The overlay was SDL2 until kit 0.14: an older game moves with
  ENGINE_FLOW's "Upgrading from SDL2". Optional add-ons are commented `find_package` lines in `CMakeLists.txt`; to
  enable one, add its vcpkg port to `vcpkg.json` (`sdl3-image`, `sdl3-ttf`, `sdl3-mixer`: lowercase with hyphens) and write
  an ADR. The engine id stays `cpp-sdl2` (existing games' `.game-kit.json` name it).
- **Shaders:** the kit's recipes (`shaders/kit/*.frag.hlsl`, generated) run on SDL's GPU renderer as custom render states.
  KitShaders (in src/gfx): `auto fx = gfx::KitShader::load(renderer, "flash");` (`nullptr` without a GPU renderer: smoke
  runs use the software one), `kit_shaders::FlashParams p; p.amount.x = 1.0f; fx->set_params(&p, sizeof p);`, then
  `fx->begin(renderer)` ... draw ... `gfx::KitShader::end(renderer)`. A second picture goes in at load
  (`KitShader::load(renderer, "dissolve", noise)`), `SDL_SetTextureColorMod` tints the result. Coordinates run 0 to 1 over
  the drawn texture: `u_texel` (`p.texel`) is one over its size in texels, `canvas` the size pixel parameters are given in.
  Post effects (`crt`, `vignette`, `colorblind`) draw the frame into a target texture, then that texture through the
  recipe. The build compiles every recipe with shadercross (vcpkg host tool) to SPIR-V, DXIL and MSL into `shaders/kit/`
  next to the exe; `smoke --shaders` draws each with `kit_shader_check` and compares it with its golden image.
- **Tests:** doctest, built as `unit_tests`, one CTest test per `TEST_CASE`. `tests/test_golden_vectors.cpp` holds
  `src/core` to the kit's reference logic: it reads `data/golden/juice.json`, `shell.json` and `credits.json` (the
  credits screen's text: CREDITS.md without its HTML comments and markdown marks, the same rule on every engine) at
  test time (path from the `GOLDEN_DIR` compile definition); never copy their expected values into code.
- **JSON:** nlohmann-json (vcpkg, header-only, MIT) for settings, saves and string tables. Settings and saves go
  through `src/core/AtomicFile.hpp` (write `<file>.tmp`, flush, rename; saves keep `<file>.bak`).
- **Version:** one source, `project(... VERSION x.y.z)` in `CMakeLists.txt` (SOP-06). Code reads it as the `GAME_VERSION`
  string (a compile definition on `core`); `--version` prints it and the BOOT_OK line carries it.
- **Game options:** everything after `--` on the command line goes to `Game::configure()` (autoplay modes, cheats, seeds),
  so a game adds options without touching `main.cpp`. `dev.py smoke` passes them the same way:
  `python tools/dev.py smoke --frames 20000 --until RUN_WON --fail-on CAUGHT -- --autoplay careful`.
  `--screenshot build/shot.bmp` and `--record build/frames` capture frames (BMP; `tools/art/frames_to_gif.py` reads them).
- **The shell (SOP-19, SOP-20):** `src/shell/` is the front end around the game: title (with the telemetry question), main
  menu, settings (Display, Audio, Controls with press-a-key rebinding and the one-handed layouts, Accessibility, Language),
  credits (`CREDITS.md`), loading, pause with "What now?" and "Dialogue history", subtitles and captions
  (`data/dialogue/*.built.json`), menu narration through the system's speech. The settings are `src/core/Settings`; the
  menu logic (`src/core/Menu.hpp`, `ShellLogic.hpp`) has no SDL and is doctest-tested (`tests/test_menu.cpp`), like
  the motor-access logic (`MotorAccess.hpp`, `tests/test_motor_access.cpp`). The game
  fills in the play screen through `shell::PlayHooks` (`Game.cpp`) and reads settings through
  `shell_->game_speed()`, `access_flag("auto_repeat")`, `palette("player")`, `is_down("attack")`, `say_line(id)`,
  `caption(id)`, `set_objective(text)`. Text is SDL's built-in 8x8 font (`SDL_RenderDebugText`, scaled by
  `access.text_scale`; `readable_font` draws it bold; `line_spacing` applies): no font file, no SDL3_ttf, **ASCII only**, so
  the shell ships `data/i18n/en.json` alone. A translation with accents, or a real typeface (the kit's readable font
  elsewhere is Atkinson Hyperlegible), means adding `sdl3-ttf` (below) and swapping `src/shell/Draw.cpp`'s glyph call.
- **Analog input (#274):** `shell_->stick()` is the left stick with the player's `input.deadzone` (radial: the vector's
  length, rescaled so a lean just past it starts near 0) and `input.invert_y`; axes follow SDL, **+y is down**.
  `left_trigger()` / `right_trigger()` run 0 to 1 past a small fixed deadzone (`core::analog::kTriggerDeadzone`).
  `held_actions()` is the set of game actions held now (no `ui_*`; the stick past the deadzone holds `move_*`, invert_y
  honoured), and `move_vector()` adds the held `move_*` keys to the stick, length 0 to 1 (a half lean walks at half
  speed). `is_down("move_left")` counts the stick too. The menus still get the stick as d-pad presses with hysteresis and
  each trigger as `pad:l2` / `pad:r2` past half travel. The maths is `src/core/Analog.hpp` (`tests/test_analog.cpp`,
  the same cases as the Bevy shell's analog module), all of it in `core::analog`: `stick()` and `move_vector()` return
  a `core::analog::Vec2`, so a game's own `core::Vec2` never clashes with it (copy `x` and `y` across).
- **Crash files and bug reports (#275):** an exception that reaches the top of main.cpp's loop, an uncaught one
  (`std::terminate`) and a fatal signal (a bad pointer, `abort`, a failed assert; best effort) write
  `crashes/crash_<UTC time>.txt` in the user-data folder (game, version, build, OS, screen, locale, seed from
  `shell_->set_run_seed()`, the error, the last 60 log lines, settings.json) and print `CRASH_WRITTEN <path>`; the run
  exits 1, and outside smoke runs a message box names the file. In a debug build (no `NDEBUG`: the `debug` preset) **F8**
  saves `bug_<UTC time>/` there (a screenshot.bmp of that frame, log_tail.txt, settings.json, info.txt) and prints
  `BUG_REPORT <folder>`; nothing leaves the machine. The texts are `src/core/Report.hpp` (`tests/test_reports.cpp`).
- **Pseudo locale (#275):** `--locale pseudo` (or Settings > Language > pseudo in a debug build) shows every string from
  `t()` bracketed and 40 % longer, in an **ASCII form without accents** (`core::pseudo_ascii`): the 8x8 font cannot draw
  accented letters, so this pseudo locale finds clipped and untranslated text, not missing glyphs. Text that is not UI
  copy (key names, CREDITS.md, arrows) is drawn with `TextOpts::raw` and skips the "went through t()" rule.
- **Juice demo (#275):** a debug build's main menu has "Juice demo" (`src/shell/JuiceDemo.cpp`): hit the box for trauma
  shake, hitstop, a spring squash, a rate-limited flash and an eased ring; a follow camera with its deadzone drawn; a
  buffered jump with coyote time; the guard (hold or toggle); walking by keys or the analog stick; a line, a bark and a
  caption. Copy the parts you want into `Game.cpp`. The shake's angle is not drawn (SDL's renderer has no rotated
  rectangles).
- **Dotwork art (#60):** packs from Dotwork (`tools/art/dotwork/`) arrive as PNGs plus `assets/dotwork/<pack>.assets.json`
  (spec: `tools/art/dotwork/ASSET_MANIFEST.md`, 1.x: 1.0.0 and 1.1.0 load, another major is refused).
  `src/core/DotworkAssets` (SDL-free, `core::dotwork`) reads them: clips with each frame's `duration` (`ClipPlayer`),
  sprites, icons, portraits, tilesets, maps, fonts (glyph quads from `chars`: `layout_text`), UI kits, and the extra
  kinds (background layers with their velocities and `repeat`, particles with the emitter JSON, transition, normal_map,
  image) as plain data by name (`pack.background("hills")`, `particle_set`, `transition`, `normal_map`, `image`); the
  object that scrolls, emits, wipes or lights with them is the game's (SDL's 2D renderer has no normal-map lighting:
  the texture loads, nothing lights with it). **Maps** become placed cells at load: a `tiles` layer as listed, a
  `stamps` layer expanded tile by tile (tile `j` of a stamp at `(x + j % w, y + j / w)`), a `terrain` layer resolved by
  the spec's rules ported to C++: `cell_mask` for `blob47`, `sides4` and `corners4` (the corner bits of the blob mask;
  a corners4 tile's key from its `corners` by shape, `tile_key`), then the variant pick among the tiles with that key
  with `cell_roll(x, y, layer_index)` (`hash32`, Jenkins' 6-shift hash in `uint32_t`, the spec's vectors in the test)
  walking the `probability` weights, so every engine picks the same variant. A cell no tile fits stays empty with one
  warning per layer. Cells land where `cell_centre` says: square `((x + 0.5) w, (y + 0.5) h)`, isometric
  `((x - y + 1) w / 2, (x + y + 1) h / 2)` (Godot's diamond-down layout; cell (0, 0) of a 16x8 set at (8, 4)), and a
  tile's image is drawn with its `origin` (else the atlas tile's centre) on that point (`placed_corner` gives the
  top-left; `map_bounds` what an isometric map covers, which starts left of pixel 0). `src/gfx/DotworkRender`
  (`gfx::dotwork::Library`) loads every pack and its textures (the extra kinds' too) and draws them: `draw_frame` (the
  frame rect as the source rect, offset by the pivot), `draw_sprite`, `draw_map` (both shapes through `cell_centre`,
  flip flags included), `draw_text`, `draw_ui_part` (9-slice
  through `SDL_RenderTexture9Grid`). **PNG decoder:** SDL's own `SDL_LoadPNG` (SDL 3.4.0 and later; the pinned 3.4.12 has
  it), so no SDL3_image or stb_image: SDL documents it for trusted files, which a game's own assets are. Every texture is
  `SDL_SCALEMODE_NEAREST` (SDL's renderer makes no mipmaps); draw at whole-number scales. A `font` or `ui_kit` image
  (its glyph rects, metrics and 9-slice margins too) is already upscaled by the manifest's `scale`: draw it 1:1, never
  times `scale` again. The starter play screen shows
  a map, a label in the font, a prop and a character walking when the game has packs (`src/game/DotworkShowcase`,
  PROTOTYPE). `tests/test_dotwork_assets.cpp` holds the loader to `data/golden/dotwork/expected.json` (1e-6: every
  kind, the three maps' `terrain`, `placed` and `centres` included) and fails
  on any manifest under `assets/dotwork/` that does not load or names a missing, non-PNG or wrongly sized file; a PNG
  SDL cannot decode is an `[ERROR]` line at boot, which fails `smoke`. All types are in `core::dotwork` and
  `gfx::dotwork`, so a game's own `Sprite` or `Map` never clashes with them.
- **Smoke scenarios:** `python tools/dev.py smoke --drive menus` (changes two settings, saves, quits; prints
  `SETTINGS_WRITTEN`), `--drive crash` (a planted exception: `CRASH_WRITTEN`, exit 1 on purpose), `--drive pseudo
  --locale pseudo` (every screen, every label: `PSEUDO_PASS` or `PSEUDO_FAIL` lines and exit 1; `pseudo-plant` must
  fail on its planted label), `--drive bug` (F8 on the menu: `DRIVE_BUG <folder>`),
  `--drive show:<title|menu|settings|pause|subtitle|play|juice|credits> --screenshot captures/x.bmp`, and
  `--drive access` (the accessibility sweep's tour; `python tools/access/sweep.py` runs it five ways). `--data-dir` keeps
  settings.json in a folder of yours (default: a fresh `build/smoke-data/`, never the player's preferences folder;
  one inside a build tree such as `build/debug/` is refused, exit 2), `--locale` picks the language. Scenarios live in
  `src/shell/Drive.cpp`; the juice demo and the bug drive need the debug preset (smoke's default).
- **Verify:** `python tools/dev.py doctor`.

## Layout
```
CMakeLists.txt, CMakePresets.json, vcpkg.json
src/core/        SDL-free, unit tested: Log, FixedTimestep; juice (Shake, Hitstop, Ease, FollowCamera, InputBuffer,
                 CoyoteTimer, Spring, FlashLimiter); motor access (MotorAccess: timing_scale, hold_to_toggle);
                 shell logic (Settings, Bindings, SaveStore, I18n, AtomicFile, Menu, ShellLogic); Analog (stick and
                 trigger shaping); Report (crash files, bug-report texts); DotworkAssets (Dotwork manifests)
src/shell/       the shell's screens on SDL: Shell (stack, input, settings applied), Draw (text, panels, the access
                 report), Drive (smoke scenarios), JuiceDemo (debug builds)
src/game/        gameplay: Game class (owns the shell, fills in the play screen), DotworkShowcase, entities, systems
src/gfx/         KitShaders: the kit's shader recipes on SDL's GPU renderer; DotworkRender: Dotwork packs drawn
data/            i18n/en.json (every label), dialogue/sample.built.json (lines and captions), access/colours.json
                 (the colour-blind palettes), input/presets.json, golden/ (the test vectors, golden/dotwork/ the
                 Dotwork fixture); every build copies it next to the exe without golden/ and shaders/, and assets/
                 with it (docs/ENGINE_FLOW.md "Packaging")
cmake/           copy_game_data.cmake (that copy)
src/tools/       kit_shader_check (dev.py smoke --shaders), not shipped
shaders/kit/     the recipes: *.frag.hlsl, kit_shaders.hpp (parameter structs), kit_shaders.cmake (generated)
src/main.cpp     startup, arg parsing, main loop
tests/           doctest tests for src/core and engine-free parts of src/game
assets/          art, audio, fonts (see docs/ASSET_LOG.md); dotwork/*.assets.json: Dotwork's manifests
tools/           dev.py and helpers
build/           build output (git-ignored): build/<preset>/
```

## Conventions
- `PascalCase` types and files (`FixedTimestep.hpp`), `snake_case` functions and variables, `kConstants`, `m_member` or trailing underscore (pick one per project, record here).
- Headers: `#pragma once`, include what you use, forward declare when you can.
- RAII for every SDL resource (custom deleters with `std::unique_ptr`). No raw `SDL_Destroy*` scattered in code.
- No naked `new`/`delete`. Prefer value types and `std::unique_ptr`. `std::vector` over C arrays.
- Fixed timestep for simulation (see `FixedTimestep`), render interpolation later. Never tie logic to frame rate.
- Errors: functions that can fail return `std::optional`, `bool` plus out param, or a small `Result`. Reserve exceptions for startup failures. Log with context via `Log`.
- Tunables in one `constants`/config header or a data file loaded at startup, never literals inside logic.
- Warnings are on (`-Wall -Wextra`, `/W4`). Fix them, do not silence them without a comment.

## Gotchas (Claude: read before editing)
1. **`main` must be `int main(int, char**)`** and `#include <SDL3/SDL_main.h>` must be in that translation unit (once in
   the program). SDL3 functions return `bool` (true = success), not 0: `if (!SDL_Init(...))`.
2. **SDL_Quit order:** destroy renderer, then window, then `SDL_Quit()`. RAII wrappers must be destroyed before `SDL_Quit`.
3. **Event loop must pump events** every frame (`SDL_PollEvent`), or the window freezes.
4. **Time:** use `SDL_GetPerformanceCounter()`/`SDL_GetPerformanceFrequency()` for deltas, clamp huge deltas (debugger pauses) to avoid the spiral of death.
5. **Headless/smoke runs** use `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy` and the software renderer, which has no
   shaders: code must cope with `KitShader::load` returning `nullptr`. Outside smoke main.cpp asks for the GPU renderer.
10. **Load each shader recipe once and keep it** (or let KitShaders' cache do it): SDL 3.4.12's GPU renderer caches pipelines
    by shader address, so a shader released and another created at the same address drew the old effect in the kit's own
    check. `release_kit_shaders(renderer)` frees them before the renderer goes (main.cpp's renderer deleter calls it).
6. **Windows DLLs:** vcpkg copies dependency DLLs next to the exe at build time. If the exe cannot start, check the build output folder.
7. **vcpkg baseline:** `vcpkg.json` ships pinned to vcpkg release 2026.07.29 (tested). Never remove `builtin-baseline` (the vcpkg bundled with Visual Studio refuses a manifest without one). To upgrade libraries, swap in a newer vcpkg release commit.
8. **Do not edit** `build/`, `vcpkg_installed/`, or generated CMake files.
9. **Include hygiene:** SDL headers only in `src/game/`, `src/shell/`, `src/gfx/` and `src/main.cpp`, not in `src/core/`,
   so core stays unit-testable.
11. **A menu row's callback must not tear down its own screen directly:** `Shell::push/pop/replace/reset` called while an
    action is being dispatched are queued and run after the callback returns (a `std::function` destroyed while it runs
    is undefined behaviour). Call them freely; just do not expect the stack to have changed on the next line.
12. **Non-ASCII text draws as nothing** with the debug font (gotcha of `SDL_RenderDebugText`): keep `data/i18n/*.json`
    and `CREDITS.md` ASCII until the game adds `sdl3-ttf`.

## Generated (do not hand-edit)
`build/`, `vcpkg_installed/`, `CMakeUserPresets.json` (local overrides, git-ignored), `shaders/kit/` (edit
`tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).
