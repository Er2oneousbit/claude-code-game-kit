# Engine: Godot 4 (GDScript)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Godot version:** 4.7.2 (latest stable when built), standard build, not .NET. The AI guard's NobodyWho plugin needs 4.5 or later, so the kit's floor covers it. 4.6 is the floor, not the target: the shell's scripts use APIs new in 4.6 (`Control.has_focus(true)`) and 4.5 (the `Logger` crash hook), so on an older Godot they do not compile, and every `dev.py` command but `clean` and `ship` refuses it with exit 2 (`MIN_GODOT` in `tools/dev.py`).
- **Binary:** set env var `GODOT_BIN` to the Godot executable, or put `godot` on PATH. `python tools/dev.py doctor` verifies.
- **Language:** typed GDScript. No C# in this project unless an ADR says so.
- **Unit tests:** GUT addon in `addons/gut/` (install from the Godot Asset Library or GitHub). Version recorded in the ADR when chosen.
- **Import cache:** `python tools/dev.py import` builds `.godot/`. `check`, `test` and `smoke` re-run it automatically on a fresh clone, whenever a `class_name` script is added, renamed or removed (Godot only learns new class names on import), and when an asset is new or changed (no `<file>.import` beside it, or newer than it).

## Layout
```
project.godot            engine config (edit via editor or carefully by hand)
scenes/                  .tscn scenes (main.tscn is the entry)
scripts/core/            engine-agnostic helpers: log, timers, juice (shake, hitstop, springs...), settings,
                         bindings, saves, i18n (no gameplay knowledge; tested against data/golden/)
scripts/shell/           the front end: Shell autoload, screens (title, menus, settings, pause...), smoke drive
scripts/game/            gameplay scripts, one per scene or entity (play.gd is the placeholder game)
data/                    tunables (.tres or .json), levels; i18n/ string tables, dialogue/, golden/ test vectors
assets/                  art, audio, fonts (see docs/ASSET_LOG.md)
tests/                   GUT tests, files named test_*.gd
addons/                  third-party addons (GUT, etc.), never edit by hand
shaders/kit/             the kit's shader recipes, one .gdshader each (generated: tools/shaders/)
tools/                   dev.py and helpers
```

## Conventions
- Files `snake_case.gd`, classes `PascalCase` via `class_name` for reusable types, signals past tense (`health_changed`).
- Always type variables and function returns (`var speed: float = 120.0`, `func jump() -> void`).
- Tunables: `@export` on a Resource (`.tres`) or load JSON from `data/`. No magic numbers in logic.
- Physics code in `_physics_process(delta)`, visuals/UI in `_process(delta)`. Always multiply by `delta`.
- Prefer signals ("call down, signal up"). Node paths with `%UniqueName` over long relative paths.
- Autoloads: max 3: Log, Shell (settings, strings, data folder, crash files) and one for game state. Each documented in `ARCHITECTURE.md`.
- Every visible string goes through `Shell.t("key")` (tables in `data/i18n/`); `smoke --locale pseudo` fails on any that does not.
- Movement: `Shell.move_vector()` (keys, d-pad and the left stick: the shell binds the stick to `move_*` on top of the
  player's bindings, with their radial deadzone, invert_y on the stick only). Analog: `Shell.stick()`, `Shell.triggers()`
  (x left, y right, 0 to 1), `Shell.held_actions()`; `Input.is_action_pressed()` works as usual.
- Player files (settings, saves, logs, crashes) live in `Shell.data_dir` (user://, or `--data-dir`); write them with `AtomicFile`/`SaveStore`.
- Pure logic goes in `RefCounted` classes under `scripts/core/` or `scripts/game/logic/` so GUT can test it without scenes.
- Logging via the `Log` autoload (`Log.info("physics", "msg")`), never bare `print` in committed code.
- 3D models: `.glb` under `assets/models/` (what `tools/blender/prep_export.py` and `tools/bozzetto/bozzetto.py` write:
  metres, +Y up, pivot at the bottom centre) import in the editor; headless, `check`, `test` and `smoke` import a new one first
  (or run `python tools/dev.py import`); instance one with
  `load("res://assets/models/<name>.glb").instantiate()`. Tested with a Bozzetto model: import, check, smoke, a GUT load (K01).
- A vertex-coloured model (`bozzetto.py make --material vertex`, colours in glTF `COLOR_0`) renders **white**: Godot 4.7
  imports the colours but leaves the material's `vertex_color_use_as_albedo` off (K01, #202). Turn it on after
  instancing:
  ```gdscript
  for mi in model.find_children("*", "MeshInstance3D", true, false):
      for s in mi.mesh.get_surface_count():
          var mat: Material = mi.get_active_material(s)
          if mat is StandardMaterial3D:
              mat = mat.duplicate()
              mat.vertex_color_use_as_albedo = true
              mi.set_surface_override_material(s, mat)
  ```
- **Shaders:** a `ShaderMaterial` with `res://shaders/kit/<name>.gdshader` on a CanvasItem (Sprite2D, TextureRect):
  `mat.set_shader_parameter("u_amount", 1.0)`, a second picture as `kit_aux` (dissolve's noise, the palette, the normal
  map). Post effects (`crt`, `vignette`, `colorblind`) read the screen (`hint_screen_texture`): put them on a full-screen
  ColorRect in a CanvasLayer above the game; the shell's colour-blind setting already does (`color_filter.gd`). Give
  each sprite its own material (`material.duplicate()`). `check` compiles them and `smoke --shaders` draws each in a
  window and compares it with its golden image (headless Godot has no renderer).

## Gotchas (Claude: read before editing)
1. **Never hand-edit** `.godot/`, `*.import`, or generated `.uid` files. Commit the `.uid` files that Godot creates (every supported version writes them), they keep references stable.
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
10. **Comparing different types is an error** (`1.0 == "a"` is a SCRIPT ERROR on 4.7.2), and JSON numbers are always floats. Check `typeof()` first when a value can be anything (settings, saves, JSON).
11. **Crash files come from a `Logger`** (`scripts/shell/crash_hook.gd`, `OS.add_logger`): it sees every script error, on any thread, and the Shell writes the file on the main thread.
12. **The windowed shader check can crash under GPU load.** Godot 4.7.2 died twice in five `check` runs (exit
    3221226356, 0xC0000374, heap corruption) during a SubViewport readback while other programs used the GPU; never
    seen with Godot alone. `dev.py` then says "Godot crashed after N recipe(s)": rerun it, or use `check --no-shaders`
    and let `smoke --shaders` cover them later. "It needs a window" means nothing was drawn at all.

## Generated or binary (do not hand-edit)
`.godot/`, `*.import`, `*.uid` (commit, but do not edit), exported builds in `build/`, `*.translation`,
`shaders/kit/` (edit `tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).

## Optional tooling
- A Godot MCP server or editor plugin can let Claude inspect and edit scenes. If used, record it in an ADR and note start instructions here.
