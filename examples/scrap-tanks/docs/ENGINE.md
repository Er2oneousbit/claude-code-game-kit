# Engine: C++17 + SDL2 (custom engine)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Language:** C++17 (set `CMAKE_CXX_STANDARD` in `CMakeLists.txt` if you move to 20). **Compilers:** MSVC (VS 2022), GCC, Clang.
- **Build system:** CMake 3.21+ with `CMakePresets.json`. **Dependencies:** vcpkg manifest mode (`vcpkg.json`).
- **Env var:** `VCPKG_ROOT` must point at vcpkg (the presets use `$env{VCPKG_ROOT}`). On Windows the copy inside VS Build Tools works. `vcpkg.json` is pinned with `builtin-baseline`; keep it.
- **Path length:** keep the project at a short path on Windows; deep paths break vcpkg's dependency builds (see `docs/ENGINE_FLOW.md`).
- **Libraries:** SDL2 (window, input, renderer, audio). Optional add-ons are commented `find_package` lines in `CMakeLists.txt`;
  to enable one, add its vcpkg port to `vcpkg.json` (`sdl2-image`, `sdl2-ttf`, `sdl2-mixer`: lowercase with hyphens) and write an ADR.
- **Tests:** doctest, built as `unit_tests`, run by CTest.
- **Version:** one source, `project(... VERSION x.y.z)` in `CMakeLists.txt` (SOP-06). Code reads it as the `GAME_VERSION`
  string (a compile definition on `core`); `--version` prints it and the BOOT_OK line carries it.
- **Game options:** everything after `--` on the command line goes to `Game::configure()` (autoplay modes, cheats, seeds),
  so a game adds options without touching `main.cpp`. `dev.py smoke` passes them the same way:
  `python tools/dev.py smoke --frames 20000 --until RUN_WON --fail-on CAUGHT -- --autoplay careful`.
  `--screenshot build/shot.bmp` and `--record build/frames` capture frames (BMP; `tools/art/frames_to_gif.py` reads them).
- **Verify:** `python tools/dev.py doctor`.

## Layout
```
CMakeLists.txt, CMakePresets.json, vcpkg.json
src/core/        header-light, SDL-free helpers: Log, FixedTimestep, math, RNG. Unit tested.
src/game/        gameplay: Game class, entities, systems. Talks to SDL only through thin wrappers.
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
1. **`main` must be `int main(int, char**)`** and `#include <SDL.h>` must be in that translation unit. On Windows SDL redefines `main` to `SDL_main`.
2. **SDL_Quit order:** destroy renderer, then window, then `SDL_Quit()`. RAII wrappers must be destroyed before `SDL_Quit`.
3. **Event loop must pump events** every frame (`SDL_PollEvent`), or the window freezes.
4. **Time:** use `SDL_GetPerformanceCounter()`/`SDL_GetPerformanceFrequency()` for deltas, clamp huge deltas (debugger pauses) to avoid the spiral of death.
5. **Headless/smoke runs** use `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy` and a software renderer. Hardware renderer creation fails under the dummy driver.
6. **Windows DLLs:** vcpkg copies dependency DLLs next to the exe at build time. If the exe cannot start, check the build output folder.
7. **vcpkg baseline:** `vcpkg.json` ships pinned to vcpkg release 2026.07.29 (tested). Never remove `builtin-baseline` (the vcpkg bundled with Visual Studio refuses a manifest without one). To upgrade libraries, swap in a newer vcpkg release commit.
8. **Do not edit** `build/`, `vcpkg_installed/`, or generated CMake files.
9. **Include hygiene:** SDL headers only in `src/game/` and `src/main.cpp`, not in `src/core/`, so core stays unit-testable.

## Generated (do not hand-edit)
`build/`, `vcpkg_installed/`, `CMakeUserPresets.json` (local overrides, git-ignored).
