# Engine: Godot 4 (GDScript)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Godot version:** 4.3 or later (SET EXACT VERSION HERE, e.g. 4.7.2). Standard build, not .NET. Older 4.x lack `--import` or exit 1 after a clean quit, so `dev.py` cannot judge them; `doctor` fails below 4.3.
- **Binary:** set env var `GODOT_BIN` to the Godot executable, or put `godot` on PATH. `python tools/dev.py doctor` verifies.
- **Language:** typed GDScript. No C# in this project unless an ADR says so.
- **Unit tests:** GUT addon in `addons/gut/` (install from the Godot Asset Library or GitHub). Version recorded in the ADR when chosen.
- **Import cache:** `python tools/dev.py import` builds `.godot/`. `check`, `test` and `smoke` re-run it automatically on a fresh clone and whenever a `class_name` script is added, renamed or removed (Godot only learns new class names on import). Run it by hand after adding assets.

## Layout
```
project.godot            engine config (edit via editor or carefully by hand)
scenes/                  .tscn scenes (main.tscn is the entry)
scripts/core/            engine-agnostic helpers: log, timers, math, RNG (no gameplay knowledge)
scripts/game/            gameplay scripts, one per scene or entity
data/                    tunables (.tres or .json), levels, dialogue
assets/                  art, audio, fonts (see docs/ASSET_LOG.md)
tests/                   GUT tests, files named test_*.gd
addons/                  third-party addons (GUT, etc.), never edit by hand
tools/                   dev.py and helpers
```

## Conventions
- Files `snake_case.gd`, classes `PascalCase` via `class_name` for reusable types, signals past tense (`health_changed`).
- Always type variables and function returns (`var speed: float = 120.0`, `func jump() -> void`).
- Tunables: `@export` on a Resource (`.tres`) or load JSON from `data/`. No magic numbers in logic.
- Physics code in `_physics_process(delta)`, visuals/UI in `_process(delta)`. Always multiply by `delta`.
- Prefer signals ("call down, signal up"). Node paths with `%UniqueName` over long relative paths.
- Autoloads: max 3 (Log, Settings, Game state). Each documented in `ARCHITECTURE.md`.
- Pure logic goes in `RefCounted` classes under `scripts/core/` or `scripts/game/logic/` so GUT can test it without scenes.
- Logging via the `Log` autoload (`Log.info("physics", "msg")`), never bare `print` in committed code.

## Gotchas (Claude: read before editing)
1. **Never hand-edit** `.godot/`, `*.import`, or generated `.uid` files. Commit the `.uid` files that Godot creates (Godot 4.4 and later, **verify for your version**), they keep references stable.
2. **`.tscn` and `.tres` are text but fragile.** Make minimal edits, never reorder `[ext_resource]` ids, never invent uids. Prefer building scenes in code or asking the user to do structural scene edits in the editor, then read the result.
3. **Signals and `queue_free()`:** freed nodes referenced elsewhere cause "previously freed" errors. Check `is_instance_valid()` for stored node references.
4. **`@onready` runs after `_init`**, before `_ready`. Do not touch `@onready` vars in `_init`.
5. **Autoload names are globals.** Do not also give the script a `class_name` with the same name.
6. **Headless runs need the import cache** (`dev.py import`) or resources fail to load.
7. **Pixel art settings** (Project Settings): default texture filter Nearest, stretch mode `viewport`, aspect `expand`, scale mode `integer` on a 640x360 base (it divides 720p, 1080p, 1440p and 4K
   evenly; the template sets these and a 1920x1080 window), snap 2D transforms to pixel. A 3D game switches to
   `canvas_items` so 3D renders at full resolution. Do not change without an ADR.
8. **Physics determinism:** do not rely on `_process` for gameplay timing. Use `_physics_process` or your own fixed-step logic.
9. **API verification:** Godot 4.x changes between minor versions. Check `godot --version` and the matching docs before using unfamiliar APIs.

## Generated or binary (do not hand-edit)
`.godot/`, `*.import`, `*.uid` (commit, but do not edit), exported builds in `build/`, `*.translation`.

## Optional tooling
- A Godot MCP server or editor plugin can let Claude inspect and edit scenes. If used, record it in an ADR and note start instructions here.
