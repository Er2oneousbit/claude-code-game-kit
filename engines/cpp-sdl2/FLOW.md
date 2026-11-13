# C++ / SDL3 Flow

Engine-specific workflow for a custom C++ engine on SDL3. Universal process lives in `docs/sop/`.

> **Tested.** On Windows (2026-11-06) with VS 2022 Build Tools 17.14 (MSVC 14.44), its bundled CMake 3.31 and vcpkg, SDL3 3.4.12,
> sdl3-shadercross 3.0.0-preview2 and doctest 2.5.3: `doctor`, `check`, `test`, `smoke`, `smoke --shaders` (every recipe matched its
> golden image on Vulkan and on Direct3D 12), `build --preset release`. The shell's screens (2026-11-09): `smoke`, `smoke --drive
> menus`, every `show:` capture, `smoke --drive access` and `tools/access/sweep.py` (all five runs pass), `test` (51 cases).
> Crash files, F8, the pseudo locale and the juice demo (2026-11-10): `smoke --drive crash|bug|pseudo|pseudo-plant`,
> `show:juice`, `test` (70 cases); a real gamepad's analog stick and triggers are untested (the maths is unit tested).
> Before the SDL3 move (SDL2 2.32.10, 2026-10-20) a planted compile error, failing test and boot-time `LOG_ERROR` each failed
> the right command. `run` (opens a window), a real gamepad, the spoken narration, Metal (MSL) and Linux/macOS are untested.
> Anything marked **(verify)** is the likeliest to need tweaks. Paste errors to Claude verbatim.

## One-time setup
1. Install: a compiler (Windows: Build Tools for Visual Studio 2022, workload "Desktop development with C++"; no IDE needed, VS Code works), CMake 3.21+, Git, Python 3.8+.
   On Windows the Build Tools already include CMake, Ninja and vcpkg (add the "C++ CMake tools for Windows" component). Add CMake to `PATH`:
   `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin`.
2. `VCPKG_ROOT`: either the bundled copy (`...\2022\BuildTools\VC\vcpkg`) or your own clone (`git clone https://github.com/microsoft/vcpkg`, run its bootstrap script).
3. `vcpkg.json` ships pinned to a `builtin-baseline` (vcpkg release 2026.07.29). The bundled vcpkg refuses a manifest without one. To move to newer
   library versions, replace the hash with a newer vcpkg release commit and rebuild.
4. Keep the project path short (for example `D:\games\my_game`). vcpkg builds dependencies deep inside `build\`, and a project path much over
   100 characters hits the Windows 260-character limit (`fatal error C1083: Cannot open compiler generated file: '': Invalid argument`).
5. `python tools/dev.py doctor`. The first `check` builds SDL3, sdl3-shadercross (with SPIRV-Cross, and Microsoft's DXC
   release, which vcpkg downloads) and doctest (a few minutes); later builds reuse vcpkg's binary cache.

## Daily loop
```
python tools/dev.py check     # configure + compile (debug preset)
python tools/dev.py test      # build + run unit tests via CTest
python tools/dev.py smoke     # run the game headless for 120 frames, fail on errors
python tools/dev.py run       # launch the game
python tools/dev.py build --preset release
```

## Mapped to CMake
| dev.py | What it runs |
|---|---|
| `check` | `cmake --preset <p>` then `cmake --build --preset <p>` |
| `test` | build, then `ctest --preset <p> --output-on-failure` |
| `smoke` | runs `<exe> --smoke 120 -- --data-dir build/smoke-data` with dummy SDL drivers (the shell walks title -> menu -> play), checks exit code and output |
| `smoke --drive <scenario>` | the same with `--drive`, 6000 frames at most, passes when the run prints `DRIVE_DONE`: `menus` (prints `SETTINGS_WRITTEN`), `show:<title|menu|settings|pause|subtitle|play|juice|credits>` (add `--screenshot`), `access[:res=WxH,scale=N,pad,read]` (what `tools/access/sweep.py` runs), `bug` (F8: `DRIVE_BUG`), `pseudo` with `--locale pseudo` (`PSEUDO_PASS`); `crash` (`CRASH_WRITTEN`) and `pseudo-plant` (a `PSEUDO_FAIL` for `plant.too_small`) exit 1 on purpose |
| `smoke --shaders` | also runs `kit_shader_check <build>/shader_check` (GPU renderer, hidden window), then `tools/shaders/shader_ref.py compare` |
| `run` | runs the built exe from the project root so `assets/` paths resolve |
| `build` | same steps as check; add `--preset release` for the shipping build (global options work before or after the command) |
| `clean` | removes `build/` |

Presets: `debug` and `release`. Both write to `build/<preset>/`.

## VS Code
`.vscode/` is pre-wired: CMake Tools picks up the presets, `launch.json` debugs the game, `tasks.json` exposes the dev.py commands.
Recommended extensions: C/C++ (ms-vscode.cpptools), CMake Tools (ms-vscode.cmake-tools), clangd optional.

## Adding a source file
1. Create `src/game/Thing.hpp/.cpp` with the standard header (docs/STYLE.md).
2. Add the `.cpp` to `GAME_SOURCES` in `CMakeLists.txt` (explicit list on purpose: no surprise globbing).
3. `python tools/dev.py check`.

## The shell's screens (SOP-19, SOP-20)
- The play screen is yours: `Game::play_enter / play_update / play_draw / play_action` in `src/game/Game.cpp` (the
  shell calls them through `shell::PlayHooks`). Draw with `shell::Draw` (`fill(..., ui = false)` for game content) or
  with SDL directly; the shell owns the pause menu, the HUD hint and the subtitles.
- Settings reach the game through `shell_->game_speed()`, `timing_scale()`, `access_flag("hold_to_toggle")`,
  `settings()["audio"]["sfx"]`, `palette("player")` (the colour-blind palette from `data/access/colours.json`),
  `is_down("attack")`; a line says itself with `say_line("guide.welcome")` (subtitles, history, `subtitle_hold`),
  a sound captions itself with `caption("box_hit")`, the goal for "What now?" with `set_objective(t("..."))`.
- Motor access (#166): every timing window goes through `core::scaled_window(base, shell_->timing_scale())`
  (`InputBuffer::set_window`, `CoyoteTimer::set_window`), and every held action (guard, sprint, aim) through a
  `core::HeldAction` with `access_flag("hold_to_toggle")` (`src/core/MotorAccess.hpp`). The starter's jump and guard
  in `Game.cpp` show both.
- A new setting: `Settings.cpp` (default and schema rule), `Menu.cpp` (its row), `data/i18n/en.json` (its label), and
  the kit's reference `tools/golden_vectors.py` when the kit itself changes.
- A new screen: a `ScreenId`, a case in `Shell::make_screen`, `screen_action` and `draw_screen`; its title key in
  `kScreenTitleKeys` for the narration; a `show:` entry in `Drive.cpp` if a picture of it should be one command away.
- Check it: `python tools/dev.py smoke --drive show:settings --screenshot captures/settings.bmp`, then
  `python tools/access/sweep.py` (text size, contrast, clipping, reach, both devices, at 100 % and 200 % text), then
  `python tools/dev.py smoke --drive pseudo --locale pseudo` (every label 40 % longer: nothing cut off, nothing
  bypassing `t()`; a key name or file content is drawn with `TextOpts::raw`).
- Analog play (#274): read `shell_->move_vector()` (keys and the stick, length 0 to 1), `stick()`, `right_trigger()` and
  `held_actions()` in `play_update`; the juice demo walks that way. +y is down, as on SDL's screen. The vectors are
  `core::analog::Vec2`: copy `x` and `y` into the game's own vector type.
- When it breaks (#275): the player's crash file is `crashes/crash_<time>.txt` in the user-data folder (SDL's preferences
  folder, `%APPDATA%\<game slug>` on Windows (verify); `build/smoke-data/` in a smoke run). In a debug build F8 saves a
  bug report folder next to it. Name the run's seed with `shell_->set_run_seed()` so both carry it.

## Adding a dependency (SDL3_image, SDL3_ttf, SDL3_mixer, others)
1. Add the vcpkg **port** name to `vcpkg.json` dependencies (`sdl3-image`, `sdl3-ttf`, `sdl3-mixer`; ports are lowercase with
   hyphens, not the CMake names), write an `/adr`. `sdl3-image` has no image formats by default: name them,
   `{ "name": "sdl3-image", "features": ["png"] }` (without it every PNG fails with "Unsupported image format").
2. Uncomment the matching `find_package(SDL3_image CONFIG REQUIRED)` line in `CMakeLists.txt` and link the target
   (`SDL3_image::SDL3_image`).
3. Rebuild. First build after a new dependency is slow (vcpkg compiles it).

## Testing
- doctest tests in `tests/`, one file per unit, named for behavior.
- Only SDL-free code is unit tested (`src/core`, pure parts of `src/game`).
- `unit_tests` target links the `core` library, never SDL.

## Debugging
- VS Code: F5 uses the `debug` preset exe. MSVC: use the Visual Studio debugger via CMake Tools.
- Run with `--debug` for verbose log channels, `--smoke N` for N headless frames.
- Sanitizers (GCC/Clang): configure with `-DENABLE_SANITIZERS=ON` (option in `CMakeLists.txt`).
- Crashes: build `debug`, run under debugger, read the call stack top frame in **your** code first.

## Assets and audio
- SDL3_mixer or miniaudio for audio **(your ADR)**. Load assets from `assets/...` relative to the working directory: `dev.py run`, `smoke` and the VS Code launch config all start
  the game from the project root. A shipped build has `assets/` next to the exe (every build copies it, Packaging step 1): join your paths to
  `shell.game_dir()` (`shell.game_dir() / "assets/spr_player.png"`): it is the working directory when that has `data/i18n`,
  else the exe's folder, so the shipped game also runs when started from another folder (a shortcut, a launcher). The shell
  reads `data/` and `CREDITS.md` the same way.
- PNGs: SDL 3.4's own `SDL_LoadPNG` (no SDL3_image needed for PNG), then `SDL_CreateTextureFromSurface` and
  `SDL_SetTextureScaleMode(tex, SDL_SCALEMODE_NEAREST)` for pixel art. Dotwork packs load through
  `gfx::dotwork::Library` (docs/ENGINE.md "Dotwork art"), which does all of that.
- Naming: `spr_player_idle.png`, `sfx_jump_01.wav`, `mus_level1.ogg`, `fnt_ui.ttf`.
- Sources and licenses: `docs/RESOURCES.md`, `docs/ASSET_LOG.md`.

## Profiling
- Frame time log in debug HUD (build one early), Tracy or Superluminal (Windows) or `perf`/`valgrind --tool=callgrind` (Linux).
- Measure in `release` or `RelWithDebInfo` builds, not `debug`. See SOP-10.

## Packaging (release)
1. `python tools/dev.py build --preset release`. Every build copies `data/` (the string tables, dialogue, input presets,
   colour palettes and your own data files; not the kit's test folders `data/golden/` and `data/shaders/`), `assets/`
   (art, audio, Dotwork packs with their manifests; files whose copy is current are skipped, deleted ones removed) and
   `CREDITS.md` next to the exe (the `game_data` target, `cmake/copy_game_data.cmake`), so `build/release/bin/`
   (`bin/Release/` with Visual Studio) is the shipped layout.
2. Package that folder: exe, DLLs (vcpkg app-local copies), `data/`, `CREDITS.md`, the `shaders/` folder (the compiled
   recipes), `assets/`, license files. Zip or installer. Without `data/` the menus show their keys (`menu.play`) and the
   log says `no string tables in ...`.
3. Run from a clean folder on a machine without the dev tools to catch missing DLLs (SOP-06). The log's first line names
   where the strings came from (`string tables en from <folder>/data/i18n`). K01: the release exe, copied to another folder
   with a French table added and started from a third one with `--locale fr`, read `data/i18n` next to it and drew
   "Jouer" (Windows, 2026-11-10).

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| CMake: `Could not find toolchain file` | `VCPKG_ROOT` unset | Set env var, restart terminal/VS Code |
| `find_package(SDL3)` fails | vcpkg manifest not run | Configure with the preset (it passes the toolchain) |
| `Could not find SHADERCROSS` | the host tool did not install | `vcpkg.json` lists `sdl3-shadercross` with `"host": true`; delete `build/` and configure again |
| A shader recipe fails the build | an edit in `tools/shaders/ksl/` that HLSL rejects | the shadercross line names the file and line; fix the `.ksl`, run `shader_gen.py` |
| `shader ...: not the GPU renderer` warning | software or another renderer (smoke, no GPU) | expected in smoke; elsewhere check the GPU driver (`SDL_GPU_DRIVER=vulkan` or `direct3d12`) |
| Window opens then closes instantly | event loop not pumping, or `quit` set early | Check `Game::handle_event` and loop |
| Smoke: `Couldn't create renderer` | hardware renderer under dummy driver | Use software renderer in smoke mode (already default in `main.cpp`) |
| `SDL3.dll not found` on launch | running exe outside build output | Run via `dev.py run` or copy DLLs |
| Linker: `undefined reference to WinMain` | main.cpp lacks `#include <SDL3/SDL_main.h>` | Include it there, once |
| `this vcpkg instance requires a manifest with a specified baseline` | `builtin-baseline` removed from `vcpkg.json` | Put a vcpkg release commit hash back |
| `"my_game" is not a valid package name` | a `name` field with underscores in `vcpkg.json` | Remove `name` (not needed for a project manifest) or use lowercase-with-hyphens |
| `fatal error C1083: Cannot open compiler generated file: ''` | project path too long for vcpkg's nested build folders | Move the project to a short path |

## Upgrading from SDL2 (games made before kit 0.14)
`new_game.py --upgrade` replaces the kit's files you never edited (CMakeLists.txt, vcpkg.json, main.cpp when unchanged)
and leaves `.gold` copies beside the ones you changed. Your own code moves to SDL3 by hand; SDL's migration guide (README-migration.md in SDL's docs folder)
lists every rename, and these are the ones the kit's starter and example hit:
- Headers: `#include <SDL3/SDL.h>`, and `#include <SDL3/SDL_main.h>` once, in main.cpp. CMake: `find_package(SDL3)`, link
  `SDL3::SDL3`; there is no SDL2main.
- Return values: most functions return `bool` (true = success); `SDL_Init(...) == 0` becomes `SDL_Init(...)`.
- Window and renderer: `SDL_CreateWindow(title, w, h, flags)` (no position), `SDL_CreateRenderer(window, name)` (a driver
  name or nullptr, no flags; vsync is `SDL_SetRenderVSync`), `SDL_RenderSetLogicalSize` is
  `SDL_SetRenderLogicalPresentation(r, w, h, SDL_LOGICAL_PRESENTATION_LETTERBOX)`.
- Drawing takes floats: `SDL_RenderCopy`/`SDL_RenderCopyF` are `SDL_RenderTexture` with `SDL_FRect`, `SDL_RenderDrawLineF`
  is `SDL_RenderLine`, `SDL_RenderFillRectF` is `SDL_RenderFillRect`, `SDL_RenderDrawRectF` is `SDL_RenderRect`.
- Surfaces: `SDL_FreeSurface` is `SDL_DestroySurface`; `SDL_RenderReadPixels(r, rect)` returns a new surface.
- Events: `SDL_QUIT` is `SDL_EVENT_QUIT`, `SDL_KEYDOWN` is `SDL_EVENT_KEY_DOWN`, `event.key.keysym.sym` is `event.key.key`,
  `SDL_MOUSEBUTTONDOWN` is `SDL_EVENT_MOUSE_BUTTON_DOWN`.
- Game controllers are gamepads: `SDL_GameController*` is `SDL_Gamepad*`, `SDL_INIT_GAMECONTROLLER` is `SDL_INIT_GAMEPAD`,
  `SDL_CONTROLLERDEVICEADDED` is `SDL_EVENT_GAMEPAD_ADDED`, `SDL_GameControllerGetAxis` is `SDL_GetGamepadAxis`.
- Scale modes: `SDL_ScaleModeLinear` is `SDL_SCALEMODE_LINEAR` (and `SDL_SCALEMODE_PIXELART` is new in 3.4).
Then `python tools/dev.py check`, `test`, `smoke` and `smoke --shaders`. The kit's own example `examples/scrap-tanks` made
the same move in 0.14; its diff is a worked example.

## Field notes (reported, unverified)
None recorded yet. Add notes from videos, forums or your own runs here, with an `E##` id in `docs/EVIDENCE.md`.
