# C++ / SDL2 Flow

Engine-specific workflow for a custom C++ engine on SDL2. Universal process lives in `docs/sop/`.

> **Tested.** On Windows (2026-10-20) with VS 2022 Build Tools 17.14 (MSVC 14.44), its bundled CMake 3.31 and vcpkg, SDL2 2.32.10
> and doctest 2.5.3: `doctor`, `check`, `test`, `smoke`, `build --preset release`, `clean` all ran, and a planted compile error, failing
> test and boot-time `LOG_ERROR` each failed the right command. `run` (opens a window) and Linux/macOS are untested.
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
5. `python tools/dev.py doctor`. The first `check` builds SDL2 and doctest from source (about 3 minutes), later builds reuse vcpkg's binary cache.

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
| `smoke` | runs `<exe> --smoke 120` with dummy SDL drivers, checks exit code and output |
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

## Adding a dependency (SDL2_image, SDL2_ttf, SDL2_mixer, others)
1. Add the vcpkg **port** name to `vcpkg.json` dependencies (`sdl2-image`, `sdl2-ttf`, `sdl2-mixer`; ports are lowercase with
   hyphens, not the CMake names), write an `/adr`.
2. Uncomment the matching `find_package(SDL2_image CONFIG REQUIRED)` line in `CMakeLists.txt` and link the target.
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
- SDL2_mixer or miniaudio for audio **(your ADR)**. Load assets from `assets/...` relative to the working directory: `dev.py run`, `smoke` and the VS Code launch config all start
  the game from the project root. For a shipped build, put `assets/` next to the exe (Packaging step 2), and the game runs from there.
- Naming: `spr_player_idle.png`, `sfx_jump_01.wav`, `mus_level1.ogg`, `fnt_ui.ttf`.
- Sources and licenses: `docs/RESOURCES.md`, `docs/ASSET_LOG.md`.

## Profiling
- Frame time log in debug HUD (build one early), Tracy or Superluminal (Windows) or `perf`/`valgrind --tool=callgrind` (Linux).
- Measure in `release` or `RelWithDebInfo` builds, not `debug`. See SOP-10.

## Packaging (release)
1. `python tools/dev.py build --preset release`.
2. Package: exe, DLLs (vcpkg app-local copies), `assets/`, license files. Zip or installer.
3. Run from a clean folder on a machine without the dev tools to catch missing DLLs (SOP-06).

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| CMake: `Could not find toolchain file` | `VCPKG_ROOT` unset | Set env var, restart terminal/VS Code |
| `find_package(SDL2)` fails | vcpkg manifest not run | Configure with the preset (it passes the toolchain) |
| Window opens then closes instantly | event loop not pumping, or `quit` set early | Check `Game::handle_event` and loop |
| Smoke: `Couldn't create renderer` | hardware renderer under dummy driver | Use software renderer in smoke mode (already default in `main.cpp`) |
| `SDL2.dll not found` on launch | running exe outside build output | Run via `dev.py run` or copy DLLs |
| Linker: `undefined reference to WinMain` | missing `SDL2::SDL2main` | Link it as in `CMakeLists.txt` |
| `this vcpkg instance requires a manifest with a specified baseline` | `builtin-baseline` removed from `vcpkg.json` | Put a vcpkg release commit hash back |
| `"my_game" is not a valid package name` | a `name` field with underscores in `vcpkg.json` | Remove `name` (not needed for a project manifest) or use lowercase-with-hyphens |
| `fatal error C1083: Cannot open compiler generated file: ''` | project path too long for vcpkg's nested build folders | Move the project to a short path |

## Field notes (reported, unverified)
None recorded yet. Add notes from videos, forums or your own runs here, with an `E##` id in `docs/EVIDENCE.md`.
