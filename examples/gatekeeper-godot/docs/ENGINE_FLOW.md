# Godot Flow

Engine-specific workflow for a Godot 4 / GDScript project. Universal process lives in `docs/sop/`.

> **Tested.** Every command ran against Godot 4.7.2 (Windows) with GUT 9.7.1, the test commands including planted failures
> (`build` exported Windows, Linux and Web; `run` booted the game); an auditor also ran the test commands on 4.3 to 4.6.3. Godot below 4.3 is not supported (see docs/ENGINE.md). Items marked **(verify)** are untested.

## Daily loop
```
python tools/dev.py check      # compile every .gd file inside the project (one Godot launch)
python tools/dev.py test       # GUT unit tests, headless
python tools/dev.py smoke      # boot the game headless for 120 frames, scan for errors
python tools/dev.py run        # launch the game window
```
Edit in VS Code (godot-tools extension) or the Godot script editor. Keep the Godot editor open for scene work.
Hot reload: the editor reloads changed scripts on focus. Running games started by `dev.py run` do not hot reload.

## The universal commands, mapped to Godot
| dev.py | What it runs |
|---|---|
| `import` | `godot --headless --path . --import` builds `.godot/`; fails on asset import errors (Godot itself exits 0) |
| `check` | `godot --headless --path . -s res://tools/check_scripts.gd -- res://<file>.gd ...`, loads each script inside the project so autoloads resolve; scripts broken by a dependency count too. Skips `tests/` until GUT is installed |
| `test` | `godot --headless --path . -s addons/gut/gut_cmdln.gd -gdir=res://tests -gexit`; fails when GUT skipped a file or ran 0 tests |
| `smoke` | `godot --headless --path . --quit-after N`, passes if output has `BOOT_OK` and no `ERROR`/`SCRIPT ERROR` |
| `run` | `godot --path .` |
| `build` | `godot --headless --path . --export-release "<preset>" <out>`. The skeleton ships `export_presets.cfg` with "Windows Desktop", "Linux" and "Web" (tests, tools and docs excluded); with no options `build` picks this computer's preset and its `export_path` (`build/windows/<game>.exe`). Verified on Godot 4.7.2: all three export from Windows in seconds and the exe boots |
| `clean` | removes `build/`, and `.godot/` with `--deep` (keeps `.godot/export_credentials.cfg`) |
| `doctor` | Godot found and 4.3+, GUT and cache present, then `tools/doctor.py` |

`check`, `test` and `smoke` run `import` first when `.godot/` is missing or a `class_name` script was added, renamed or removed:
Godot only learns class names on import, so without it valid code fails `check` and new test files are skipped.

## Setting up tests (GUT)
1. Install GUT into `addons/gut/` (Asset Library or the GUT GitHub release for your Godot version; 9.7.1 works with Godot 4.7.2).
   The folder must be `addons/gut/`, not the GUT files loose in `addons/`. The next `check`/`test` re-imports automatically.
2. Enable it under Project Settings > Plugins for the editor panel. The headless `dev.py test` works without enabling it.
3. Tests live in `tests/`, files `test_*.gd`, extend `GutTest`, functions `test_*`. Example in `tests/test_coyote_timer.gd`.
4. `python tools/dev.py test` runs them headless. Add `--filter <name>` to run one file.

## Adopting an existing project
`new_game.py --adopt` never edits your `project.godot`; the kit's version lands in `project.godot.gold`. After adopting:
1. Copy the `[autoload]` line `Log="*res://scripts/core/log.gd"` from `project.godot.gold` into your `project.godot` (the kit's scripts call `Log`).
2. Print the boot marker from your own main scene's `_ready()`: `Log.info("core", "BOOT_OK <Game>")`. `smoke` passes only when it sees it.
3. Keep or delete the kit's starter files (`scenes/main.tscn`, `scripts/game/main.gd`, the CoyoteTimer example), then delete every `*.gold` file once merged (Godot ignores them meanwhile).
4. Install GUT (above), then `python tools/dev.py check`, `test`, `smoke`.

## Scenes vs code
- Structural scene work (adding nodes, wiring signals in the editor): do it in the editor. Claude can read the `.tscn` after.
- Behavior: scripts. Claude edits `.gd` freely.
- Spawn/instantiate via `preload("res://scenes/x.tscn")`, tune values from data.

## Assets and audio
- Import settings live in `*.import` files. Pixel art: Filter off, mipmaps off. Audio loops: set loop in the import tab, verify in-game.
- Audio buses: Master > Music, SFX, UI. Create in the Audio tab, expose volume sliders in settings from day one.
- Naming: `spr_player_idle.png`, `sfx_jump_01.wav`, `mus_level1.ogg`, `fnt_ui.ttf`.
- Find sources in `docs/RESOURCES.md`, log in `docs/ASSET_LOG.md`.
- Tripo AI lists a Godot plugin **(verify)**. Whether you use it or just import GLB, import generated meshes as drafts and clean them in Blender first (SOP-11).

## Profiling
Editor > Debugger > Profiler and Monitors. Record: FPS, process/physics time, draw calls, object count.
Release-like check: export a release build and watch the on-screen FPS counter. Editor numbers run slower. See SOP-10.

## Packaging (export)
1. Install export templates for your exact Godot version once (Editor > Manage Export Templates, or download the
   `.tpz` for your version from godotengine.org and install it from that dialog).
2. `export_presets.cfg` comes with the project: "Windows Desktop", "Linux" and "Web", with `tests/*, tools/*, docs/*,
   addons/gut/*` excluded. Add macOS, Android or iOS in Project > Export (they need signing). Commit `export_presets.cfg` but
   **never** credentials: Godot 4 writes keystore passwords and the PCK encryption key to .godot/export_credentials.cfg
   (git-ignored with the rest of .godot/, denied to Claude, and kept by `clean --deep`).
3. `python tools/dev.py build` (this computer's preset), or `build --preset Web` (a folder you can upload to itch.io).
4. Check the build boots: `build/windows/<game>.exe --headless --quit-after 120` must log `BOOT_OK`.
5. Play the exported build, not the editor, before release (SOP-06).

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| `Identifier not found` for an autoload from a hand-run `godot --check-only --script` | `--check-only --script` runs outside the project's autoloads (confirmed on 4.7.2) | Use `dev.py check`, which loads scripts through `tools/check_scripts.gd` |
| Godot crashes (signal 11) when checking scripts | a `-s` script tried to recompile itself | `check_scripts.gd` skips itself; do not pass it to another checker |
| `Could not load resource` in headless runs | import cache missing | `python tools/dev.py import` |
| `Invalid call. Nonexistent function` after pulling | stale `.godot/` cache | `python tools/dev.py clean --deep`, then `import` |
| GUT not found | addon not installed or not enabled | See "Setting up tests" |
| `Identifier "X" not declared` / `Could not find base class "GutTest"` on valid code | class cache older than the scripts | `python tools/dev.py import` (check/test/smoke do it automatically when class names change) |
| `test` says "no tests ran" or "a test file was skipped" | `--filter` matches nothing, a test file has a parse error, or GUT was installed after the last import | Fix the file or filter; the printed lines name it |
| Test passes in editor, fails headless | depends on scene tree or window | Move logic into a `RefCounted` class |

## Claude-specific tips
- Ask Claude to create tests alongside new logic classes. Keep logic out of node scripts.
- When Claude proposes a Godot API, ask "verified or unverified?" It should check docs for your version.
- If scenes get hairy, have Claude describe the desired node tree and you build it in the editor.

## Field notes (reported, unverified)
**No MCP needed (E04).** Godot scenes, scripts, shaders, and most resources are plain text. A video creator runs agents directly against the project files with no Godot MCP server, then launches the game, checks, and iterates. That matches this kit: `tools/dev.py check|test|smoke` is the feedback loop. Binary assets (images, audio, .blend) are the exception.
Terrain note: for MultiMesh grass or foliage, test painted textures on simple planes versus real geometry for the look you want.

**Screenshots and bursts from the kit (K01):** `python tools/dev.py smoke --screenshot <file.png>` and `--record <folder>`
run the game in a real window after the headless smoke (headless has no renderer; a window opens for a few seconds),
through `tools/capture.gd`; `tools/art/frames_to_gif.py <folder> <out.gif>` makes the GIF.

**Recording gameplay (E09, verify).** A video creator reported that capturing the running game fails while Godot's window mode is "windowed". Setting Project Settings > Display > Window > Mode to fullscreen fixed capture for him. Windows Game Bar (Win+G) is a free recorder. Recordings are handy for pulling screenshots and for `/playtest-report` notes.
