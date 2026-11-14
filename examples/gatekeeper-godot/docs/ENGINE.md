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
                         bindings, saves, i18n, the Dotwork importer (dotwork_manifest.gd + dotwork_assets.gd)
                         (no gameplay knowledge; tested against data/golden/)
scripts/shell/           the front end: Shell autoload, screens (title, menus, settings, pause...), smoke drive
scripts/game/            gameplay scripts, one per scene or entity (play.gd is the placeholder game)
data/                    tunables (.tres or .json), levels; i18n/ string tables, dialogue/, golden/ test vectors
assets/                  art, audio, fonts (see docs/ASSET_LOG.md); assets/dotwork/<pack>.assets.json = Dotwork
                         asset manifests
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
- **Rigged characters (glTF with clips, #290):** a `.glb` with a skin and animations (a Bozzetto `rig make` result:
  Mixamo bone names, clips `idle`, `walk` ...) goes under `assets/models/` like any model. `KitCharacter`
  (`scripts/core/kit_character.gd`) does the rest:
  `var hero := KitCharacter.load_scene("res://assets/models/hero_rigged.glb")`, `add_child(hero)`,
  `KitCharacter.play(hero, "walk")` (loops; `play(hero, "wave", false)` plays once; a 0.2 s crossfade between clips).
  Why: glTF clips import **without looping**, so `play()` sets `loop_mode` (or set Loop Mode per animation in the
  Advanced Import Settings). Godot renames bones: `:` becomes `_` (`mixamorig:Hips` is `mixamorig_Hips`;
  `KitCharacter.bone_name()` converts). No root motion is applied: the clips walk in place and the game moves the
  node. Scale: metres, 1 unit = 1 m (the golden character is 1.8 m). Facing: glTF's front is +Z, Godot's forward -Z,
  so the character faces the default camera; turn it toward a point with `look_at(target, Vector3.UP, true)` (model
  front). `load_scene()` falls back to a run-time load (`GLTFDocument`) for a file Godot has not imported (user://, a
  download). Godot's own humanoid retargeting (a `BoneMap` with `SkeletonProfileHumanoid` in the import dialog) is
  for sharing clips between skeletons; it should match the Mixamo names **(verify: not tried)**. `play()` sets the
  loop flag on the player's own copies of the clips (`own_animations()`): instances of one imported scene share
  their Animation resources, so without that one hero's `play("wave", false)` would stop another's looping wave.
  `play()` of the clip already playing with the same loop setting changes nothing (it keeps its time, and a one-shot
  that ended keeps holding, where `AnimationPlayer.play` would start it again), so a game may call it every frame;
  `play(hero, clip, loop, blend, true)` (restart) or another loop setting starts it from 0: the same rule in all five
  engines' character helpers (#296). Tested 2026-11-11 on Godot 4.7.2:
  `tests/test_kit_character.gd` (5 GUT tests then, 6 since the restart rule) loads `data/golden/character/character.glb` both ways, finds `idle`
  and `walk` at their lengths, plays `walk` 30 frames and checks `mixamorig_LeftUpLeg` swings as far as
  `expected.json` says and no further, that the loop's period is the clip's length at 1x, and that two instances
  keep their own loop flags; `check`, `test` (109 tests) and `smoke` passed on a fresh scaffold. The same helper
  loaded a 69-bone Tripo rig with three textured clips (idle, walk, run): every clip looped, the Mixamo names mapped
  through `bone_name()`, its own chain bones kept their names, 1.8 m tall facing +Z (2026-11-11, not a kept test).
- **Dotwork art** (`tools/art/dotwork/`, spec `ASSET_MANIFEST.md` 1.1.0; 1.0.0 packs still load, another major is
  refused): Dotwork writes Godot's own resources straight into the game (SpriteFrames, TileSets, prop scenes, map
  scenes; its README "Godot notes"), and every pack also gets `assets/dotwork/<pack>.assets.json`. The importer
  reads those manifests like every other engine's does (#307), for the packs that have no Godot resources, such as
  the sheets `tools/blender/render_sprites.py --manifest` renders from a 3D character (`/make-character`'s 2D route):
  `var art := DotworkAssets.load_all()` (every pack; problems logged), or
  `var m := DotworkAssets.load_manifest("res://assets/dotwork/hero.assets.json")`, then
  `var hero := DotworkAssets.animated_sprite(m["animated_sprite"]["hero"])` and `DotworkAssets.play(hero, "walk_s")`
  (a SpriteFrames per asset, each frame's own `duration`, the clip's pivot as the offset: the feet on the node's
  position), `DotworkAssets.sprite(m["sprite"]["crate"])` (Sprite2D, pivot on the position, a `Shadow` child, a
  `Body` StaticBody2D per collision rect), `add_child(DotworkAssets.map_node(m["map"]["yard"]))` (a Node2D with a
  TileMapLayer per layer and the props under a y-sorted `Props` node), `DotworkAssets.font(...)` (FontFile from the
  `.fnt`), `DotworkAssets.nine_patch(kit, part)`, `background(...)`, `lit_texture(normal_map)` (a CanvasTexture).
  Textures: Godot's imported PNG when there is one, else the PNG decoded at run time.
  - **Maps.** Cells arrive resolved (`scripts/core/dotwork_manifest.gd`, no nodes): a terrain layer's cells get the
    spec's key (`blob47`, `sides4`, `corners4`) and, among a key's variants, the tile `DotworkManifest.cell_roll(x,
    y, layer_index)` picks, the same tile every engine draws, then `set_cell` puts it in the TileMapLayer. Godot's
    own terrain solver is not used for the variant (it rolls its own dice); Dotwork's map scenes take the same pick
    since #307. The importer's TileSet has no terrain sets: paint terrain by hand with Dotwork's own TileSet `.tres`.
    Placement is Godot's: square, or isometric diamond-down (`tile_layout = TILE_LAYOUT_DIAMOND_DOWN`), the tile's
    `origin` set as `texture_origin`, an iso layer `y_sort_enabled` so a taller block overdraws the one above it.
  - `tests/test_golden_dotwork.gd` holds it to `data/golden/dotwork/expected.json` to 1e-6 (every kind; the maps'
    terrain, placed cells and centres read back from the TileMapLayers, `map_to_local` included) and the spec's
    `hash32` / `cell_roll` vectors; `tests/test_dotwork_manifests.gd` loads every pack of the game and fails on a
    missing or mis-sized file. The extra kinds load as data plus textures (the spec's per-engine table). Checked on
    4.7.2: `check`, `test`, `smoke`, and a frame of the golden maps drawn through it (2026-11-13). The starter scene
    does not draw Dotwork art yet: add the nodes to your scene.
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
7. **Pixel art settings** (Project Settings): default texture filter Nearest, stretch mode `canvas_items`, aspect
   `expand`, scale mode `integer` on a 640x360 base (it divides 720p, 1080p, 1440p and 4K evenly; the template sets
   these and a 1920x1080 window), snap 2D transforms to pixel. Layout stays in 640x360 units and pixel art scales by
   whole numbers, but text and 3D draw at the window's resolution, so menus, the HUD and the readable font stay sharp
   (until kit 0.15.4 the mode was `viewport`, which drew everything at 640x360 and scaled it: letters became 3 to 6 px
   blocks at 1080p to 4K, #311). The trade-off: a moving sprite snaps to screen pixels, not the art grid. A game that
   wants a strict art grid puts its world in a 640x360 SubViewport and keeps the UI outside it, at native size; any
   SubViewport renders at its size times k with its camera zoom times k (k = window height / 360), or its text stays
   blocky. `smoke --screenshot` saves at the window's size. The root viewport is the window, so connect a callable to
   `get_viewport().size_changed` or `get_window().size_changed`, never both (Godot refuses the second as already
   connected). Do not change the mode without an ADR.
8. **Physics determinism:** do not rely on `_process` for gameplay timing. Use `_physics_process` or your own fixed-step logic.
9. **API verification:** Godot 4.x changes between minor versions. Check `godot --version` and the matching docs before using unfamiliar APIs.
10. **Comparing different types is an error** (`1.0 == "a"` is a SCRIPT ERROR on 4.7.2), and JSON numbers are always floats. Check `typeof()` first when a value can be anything (settings, saves, JSON).
11. **Crash files come from a `Logger`** (`scripts/shell/crash_hook.gd`, `OS.add_logger`): it sees every script error, on any thread, and the Shell writes the file on the main thread.
12. **The windowed shader check can crash under GPU load.** Godot 4.7.2 died twice in five `check` runs (exit
    3221226356, 0xC0000374, heap corruption) during a SubViewport readback while other programs used the GPU; never
    seen with Godot alone. It can also die before the first recipe (0xC0000005 and 0xC0000374, two runs in a row
    on 2026-11-11 while a Unity editor and other tests ran; the third passed). `dev.py` then says "Godot crashed
    after N recipe(s)" or "before drawing a recipe": rerun it, or use `check --no-shaders` and let
    `smoke --shaders` cover them later. "It needs a window" means nothing was drawn and Godot did not crash.
13. **The editor rewrites `project.godot`.** Whenever it saves the project settings (`ProjectSettings.save()`, the
    first open, any Project Settings change), Godot drops every comment and every key left at its default value, and
    sets `config/features` to the editor's own version (4.6 in the template, the kit's floor, becomes your 4.x: that is
    fine). So keep explanations here, never as comments in `project.godot`, and never rely on a default being written
    there: read a setting with `ProjectSettings.get_setting(name, default)`, and a tool that parses the file must treat
    a missing key as Godot's default (the Dotwork screens lane reads a missing viewport size as 1152x648). What the
    template sets, and why: a 640x360 viewport with a 1920x1080 window, stretch `canvas_items`, aspect `expand`, scale
    mode `integer` and Nearest filtering with 2D snapping (gotcha 7); `audio/general/text_to_speech` on for menu
    narration; `untyped_declaration` as a warning (typed GDScript); the `Log` and `Shell` autoloads. None of them is a
    default, so the editor keeps them. Checked on 4.7.2 (2026-11-13): a save kept every one of them and dropped a
    `physics_ticks_per_second=60` (the default) a game had written out.

## Generated or binary (do not hand-edit)
`.godot/`, `*.import`, `*.uid` (commit, but do not edit), exported builds in `build/`, `*.translation`,
`shaders/kit/` (edit `tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).

## Optional tooling
- A Godot MCP server or editor plugin can let Claude inspect and edit scenes. If used, record it in an ADR and note start instructions here.
