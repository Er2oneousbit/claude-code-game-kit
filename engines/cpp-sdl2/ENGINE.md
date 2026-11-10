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
  `src/core` to the kit's reference logic: it reads `data/golden/juice.json` and `shell.json` at test time (path from
  the `GOLDEN_DIR` compile definition); never copy their expected values into code.
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
  menu logic (`src/core/Menu.hpp`, `ShellLogic.hpp`) has no SDL and is doctest-tested (`tests/test_menu.cpp`). The game
  fills in the play screen through `shell::PlayHooks` (`Game.cpp`) and reads settings through
  `shell_->game_speed()`, `access_flag("auto_repeat")`, `palette("player")`, `is_down("attack")`, `say_line(id)`,
  `caption(id)`, `set_objective(text)`. Text is SDL's built-in 8x8 font (`SDL_RenderDebugText`, scaled by
  `access.text_scale`; `readable_font` draws it bold; `line_spacing` applies): no font file, no SDL3_ttf, **ASCII only**, so
  the shell ships `data/i18n/en.json` alone. A translation with accents, or a real typeface (the kit's readable font
  elsewhere is Atkinson Hyperlegible), means adding `sdl3-ttf` (below) and swapping `src/shell/Draw.cpp`'s glyph call.
- **Smoke scenarios:** `python tools/dev.py smoke --drive menus` (changes two settings, saves, quits; prints
  `SETTINGS_WRITTEN`), `--drive show:<title|menu|settings|pause|subtitle|play> --screenshot captures/x.bmp`, and
  `--drive access` (the accessibility sweep's tour; `python tools/access/sweep.py` runs it five ways). `--data-dir` keeps
  settings.json in a folder of yours (default: a fresh `build/smoke-data/`, never the player's preferences folder),
  `--locale` picks the language. Scenarios live in `src/shell/Drive.cpp`.
- **Verify:** `python tools/dev.py doctor`.

## Layout
```
CMakeLists.txt, CMakePresets.json, vcpkg.json
src/core/        SDL-free, unit tested: Log, FixedTimestep; juice (Shake, Hitstop, Ease, FollowCamera, InputBuffer,
                 CoyoteTimer, Spring, FlashLimiter); shell logic (Settings, Bindings, SaveStore, I18n, AtomicFile,
                 Menu, ShellLogic)
src/shell/       the shell's screens on SDL: Shell (stack, input, settings applied), Draw (text, panels, the access
                 report), Drive (smoke scenarios)
src/game/        gameplay: Game class (owns the shell, fills in the play screen), entities, systems
src/gfx/         KitShaders: the kit's shader recipes on SDL's GPU renderer
data/            i18n/en.json (every label), dialogue/sample.built.json (lines and captions), access/colours.json
                 (the colour-blind palettes), input/presets.json, golden/ (the test vectors)
src/tools/       kit_shader_check (dev.py smoke --shaders), not shipped
shaders/kit/     the recipes: *.frag.hlsl, kit_shaders.hpp (parameter structs), kit_shaders.cmake (generated)
src/main.cpp     startup, arg parsing, main loop
tests/           doctest tests for src/core and engine-free parts of src/game
assets/          art, audio, fonts (see docs/ASSET_LOG.md)
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
