# Engine: Unreal Engine 5 (C++ and Blueprints)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Unreal version:** 5.8.4 (Launcher build). Plugins: GameplayAbilities, EnhancedInput, PythonScriptPlugin (editor only).
- **Env var:** `UE_ROOT` = engine install folder (the one containing `Engine/`). `dev.py doctor` verifies.
- **Project file:** the `*.uproject` in the repo root. Adopt-first: create the project in the editor (no spaces in the name), close
  the editor, then run `new_game.py --adopt` into that folder and `python tools/dev.py doctor`. Full steps: `docs/ENGINE_FLOW.md` "Setup".
- **Toolchain:** MSVC, the Windows SDK and the .NET Framework 4.8 SDK. The free "Build Tools for Visual Studio 2022" with the "Desktop development with C++" workload plus the ".NET Framework 4.8 SDK" component is enough; the Visual Studio IDE is optional (VS Code works: `python tools/dev.py genproj --vscode`). Allowed and banned MSVC versions are in `<UE_ROOT>/Engine/Config/Windows/Windows_SDK.json` (UE 5.8: 14.44 or 14.50 families). Blueprint-only projects run tests without a toolchain (unless the GameKitShell plugin is enabled: `check` compiles it once).
- **Live Coding:** any open Unreal editor on the same engine install blocks command-line builds of every project. Close it before `dev.py check`.
- **Languages:** C++ for systems, base classes, and anything Claude must edit. Blueprints for content-facing glue and data. Editor Python (`python tools/dev.py exec <script.py>`, headless) for asset imports and maps, so binary content comes from a script Claude can edit (`docs/ENGINE_FLOW.md` "Content from scripts").
- **Source control:** Git with **Git LFS** (see `.gitattributes`). Set up LFS before the first commit of `Content/`.
- **Optional:** Unreal MCP plugin so Claude can inspect and modify the editor. Record which plugin and version in an ADR and describe how to start it here. 

## Layout
```
<Game>.uproject
Source/<Game>/           C++ module (Public/ and Private/)
Source/<Game>Tests/      automation tests (optional separate module, or Private/Tests/)
Content/                 binary assets (.uasset, .umap): NEVER hand-edit, LFS tracked
Config/                  .ini settings (text, editable with care)
Plugins/                 project plugins (including MCP if used)
Plugins/GameKitShell/    the kit's juice and shell logic in C++ (opt-in: docs/ENGINE_FLOW.md "Juice and shell plugin")
                         and, in its GameKitShellUI module, the shell's screens in Slate ("Shell screens")
data/i18n/               the screens' strings per locale (en.json, fr.json), data/input/presets.json the one-handed layouts
data/golden/             the kit's golden vectors, read by the plugin's GameKit.* tests
Content/Python/kit_shaders/  the kit's shader recipes: kit_recipes.py (generated HLSL), kit_materials.py (builds
                         them as materials), make_materials.py, shader_check.py
Content/Python/kit_dotwork/  the Dotwork importer (Paper2D): import_dotwork.py, its checks test_dotwork_*.py
Content/Python/kit_character/  rigged glTF characters: import_character (character.py), its check test_character_golden.py
assets/dotwork/          Dotwork's packs (`<pack>.assets.json` + PNGs under assets/art/): outside Content/ on purpose
Tools/ or tools/         dev.py and helpers
```

## The big rule: what Claude can and cannot edit
| Edit freely | Edit with care | Never edit by hand |
|---|---|---|
| `Source/**` C++ | `Config/*.ini` (check keys against docs) | `Content/**/*.uasset`, `*.umap` (binary) |
| `tools/`, `docs/` | `*.uproject`, `*.Target.cs`, `*.Build.cs` | `Intermediate/`, `Binaries/`, `Saved/`, `DerivedDataCache/` |
| Data files that get imported (CSV/JSON for DataTables) | Plugin descriptors | `.sln`/`.vcxproj` (generated) |

**Consequence:** put behavior in C++ (or data-driven assets fed by CSV/JSON) so Claude can change it by editing text.
Blueprint graph changes happen in the editor (by you, or via an MCP plugin if you set one up). Claude writes the C++ base class
and a clear spec for the Blueprint child.

## Conventions
- UE coding standard prefixes: `A` actors, `U` UObjects/components, `F` structs, `E` enums, `I` interfaces, `T` templates.
- Asset prefixes: `BP_` blueprint, `WBP_` widget, `M_` material, `MI_` material instance, `T_` texture, `SM_` static mesh,
  `SK_` skeletal mesh, `A_`/`AM_` animation, `DT_` data table, `DA_` data asset, `SFX_`/`MUS_` sound cues or MetaSounds.
- `UPROPERTY` and `UFUNCTION` specifiers on everything exposed. Use `EditAnywhere`, `BlueprintReadOnly` etc. deliberately.
- Tunables: `UDataAsset` or `UDeveloperSettings` or DataTables, not literals in `.cpp`.
- Logging: `DEFINE_LOG_CATEGORY` per system, `UE_LOG(LogMyGame, Warning, TEXT("..."))`. No `GEngine->AddOnScreenDebugMessage` in committed logic except behind a debug cvar.
- Debug toggles: console variables (`TAutoConsoleVariable`) or `exec` console commands.
- Tests: Automation Spec or simple automation tests for engine-light logic (see ENGINE_FLOW).
- 3D models from `tools/bozzetto/bozzetto.py` land in `SourceArt/Models/` (outside `Content/`): import the `.glb` as a
  static mesh (`SM_` prefix) with the editor's glTF import (Interchange) **(verify for your version)**.
  A `--material vertex` model keeps its colours in glTF `COLOR_0`: Unreal imports vertex colours, but a material shows
  them only through a Vertex Color node; check that it is not white (Godot ignores them by default, #202) **(verify)**.
- Juice and shell (SOP-18, SOP-19): screen shake, hitstop, easing, camera follow, input buffer, coyote time, springs,
  the flash limiter, settings, rebinding, glyphs, saves and localization are already written in `Plugins/GameKitShell`
  (plain C++, `GameKit::` and `FGameKit*`). Enable it in the `.uproject` and use it instead of writing them again.
- **Shell screens (SOP-19, SOP-20):** the plugin's `GameKitShellUI` module draws the title, main menu, settings
  (Display, Audio, Controls with rebinding and the one-handed layouts, Accessibility, Language), loading, pause
  with "What now?" and the dialogue history, and credits in **Slate from C++** (no `.uasset` widgets to hand-edit;
  builds in a Blueprint-only project). Turn them on in `Config/DefaultGame.ini` (`bShowScreens=True` under the
  `GameKitShellUI.GameKitShellSettings` section: docs/ENGINE_FLOW.md has the lines) or with `-GameKitShell`; the subsystem
  `UGameKitShellSubsystem` puts them over your map and fires `OnShellEvent` ("play", "resume", "quit_title",
  "settings_changed"). Strings in `data/i18n/<locale>.json`, credits from `CREDITS.md` (a packaged game reads
  its copy, credits.md in `data/`, which the plugin keeps in step: never edit the copy). The subsystem also gives the
  game analog input (`GetStick`, `GetTrigger`, `IsActionHeld`, Blueprint-callable) with the player's deadzone and
  invert_y, writes a crash file on a fatal error, and in debug builds adds the juice demo, the pseudo language and the
  F8 bug report. `python tools/dev.py smoke --drive menus|crash|bug|pseudo` and `--drive show:<screen> --screenshot
  captures/x.png` walk and picture them (docs/ENGINE_FLOW.md "Shell screens"); `python tools/access/sweep.py` runs the
  accessibility sweep on them.
- **Shaders:** `python tools/dev.py exec Content/Python/kit_shaders/make_materials.py` builds every kit recipe as a
  material in `/Game/KitShaders/` (`M_Kit_<name>`: an Unlit material whose Custom node holds the recipe's HLSL;
  sprites and lighting Translucent, the rest Opaque). Make a material instance per use, set `MainTex` (and `AuxTex`)
  and the `u_<name>` parameters; tween them from C++ or Blueprints through a dynamic material instance. Coordinates
  are the mesh's UVs (top-left origin, as the recipes): `u_texel` is one over the picture's size in texels,
  `u_canvas` the size pixel parameters (`u_light_pos`) are given in. Import pixel art as linear, Nearest, no mips
  (`kit_materials.import_texture` does it). `check` compiles the recipes as materials and `smoke --shaders` draws each
  into a render target and compares it with its golden image, both in the full editor off-screen (a GPU; about a
  minute each). Those runs draw opaque check variants built from the same graph; the translucent `M_Kit_` assets and
  post effects in a Post Process material (PostProcessInput0 in place of `MainTex`) are **(verify)** in your game.
  Python needs the PythonScriptPlugin enabled in the `.uproject`.
- **Dotwork art (Paper2D):** Dotwork runs with `--engine none` in an Unreal game by default (from `.game-kit.json`;
  its `assets_dir` stays "assets", which keeps the PNGs out of `Content/`, where the open editor would auto-import
  them), then `python tools/dev.py exec
  Content/Python/kit_dotwork/import_dotwork.py` builds every `assets/dotwork/<pack>.assets.json` under
  `/Game/Dotwork/<pack>/`: textures (`T_`, nearest, no mips, uncompressed), a PaperSprite per frame and per prop
  (`S_`, custom pivot, collision boxes), a PaperFlipbook per clip (`FB_<name>_<clip>`, a frame rate at which every
  hold is a whole frame run), a PaperTileSet per atlas (`TS_`, per-tile collision, the surface as user data, and
  the Drawing Offset that puts its tiles where the manifest draws them: the tile's `origin`, or its centre, on the
  cell's centre; the rule comes from Paper2D's render source, `PaperTileMapComponent::RebuildRenderData`, and
  every golden atlas needs offset 0, the golden iso block included, so a non-zero offset is **(verify)** until an
  atlas needs one), a PaperTileMap per map (`TM_`, Orthogonal for a square set, Isometric Diamond for an isometric
  one), an offline Font (`F_`) and Slate brushes for UI parts (`SB_`, 9-slice margins). Maps follow the manifest
  spec's rules (`tools/art/dotwork/ASSET_MANIFEST.md` 1.1.0, Paper2D has no autotiling): a `terrain` layer's cells
  get the tile whose key matches (blob47, sides4 and corners4; a cell with no tile stays empty with a warning), a
  variant among tiles with the same key is picked by `probability` with the cell's roll (`cell_roll`, so every
  engine but Godot shows the same tile), a `stamps` layer places every tile of each stamp, and Paper2D's own grid
  is the spec's in both projections: it centres cell (0, 0) on the tile map's origin, so a map pixel `(px, py)`
  (y down, cell (0, 0)'s top-left at 0) sits at local `(px - w/2, 0, -(py - h/2))` (`dotwork_paper.map_to_local`);
  the golden test reads the centres back from Paper2D's `GetTileCenterPosition` to prove it, isometric included. A
  tile whose origin differs from the first tile of its atlas (or lands on a half pixel) gets a warning: a tile set
  has one whole-pixel Drawing Offset, so put such tiles in an atlas of their own. The extra kinds load as textures:
  `background` layers (wrapping on their `repeat` axes, `dotwork.velocity`), `particles` (the mask texture with
  the emitter JSON in its `dotwork.emitter` tag; nothing is written beside it under `Content/`, because the editor's
  auto-import is on by default (`bMonitorContentDirectories`, `bAutoCreateAssets`) and `CSVImportFactory` claims
  `.json`, so a loose file there would be offered as a DataTable on the next editor start, read from the 5.8 source,
  not watched **(verify)**; a Niagara system is #286), `transition`
  (`dotwork.transition`), `normal_map` (linear, `dotwork.target`; a lit Paper2D material is #286) and `image`.
  Loop, blend, directions, hotspots, map objects and the map's shape are metadata tags (`dotwork.*`) too. It also
  saves `/Game/Dotwork/L_DotworkDemo` (the map, its props placed through `map_to_local`, a character walking, a
  label in the font; `DOTWORK_DEMO=0` skips it). Run it again after every Dotwork `pack`: assets update in place.
  `dev.py test` runs the importer's checks (the golden pack against `data/golden/dotwork/expected.json`: clips,
  sprites, the three maps' terrain, placed cells and centres, then every manifest of the game) through the
  pythonscript commandlet; enable the PythonAutomationTest plugin as well to have them as
  `Editor.Python.<Game>.kit_dotwork.*` automation tests. Both need `PythonScriptPlugin` (and Paper2D, on by
  default) in the `.uproject`. Paper2D cannot do: animated tiles (first frame shown; the frames are in
  `dotwork.animated_tiles`), additive blend (no Paper2D material; set one), a font's per-glyph x offset and kerning
  pairs (offline Fonts keep one advance per glyph). An offline Font draws in TextRender and Canvas; UMG text wants a
  runtime font from a TTF/OTF **(verify)**. The font's page textures can only be set by the commandlet (the editor
  refuses the `set` command), so import through `dev.py exec`, not from the editor's Python console. To try the
  importer on the golden pack, copy `data/golden/dotwork/assets/` over the project's `assets/` and run the `exec`
  line above (the pack is `golden`).
- **Frame times in smoke (#90):** `dev.py smoke` reports and budget-checks (`--frame-budget MS`) a line
  `FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=logic` when one of your `<Game>.Smoke.*` tests logs it
  (the kit ships no Smoke test here). Time each tick with `FPlatformTime::Seconds()` in a latent command and log the
  line once at the end (nearest-rank percentiles); `mode=logic`, since the automation run uses `-NullRHI` and draws
  nothing. Without the line smoke says "not measured" and checks no budget **(verify)**.

## Rigged characters (glTF with clips, #290)
A rigged `.glb` (one skinned mesh, clips as glTF animations: Bozzetto's rig routes, Mixamo, Blender) comes in through
Unreal's own glTF importer (Interchange) with `kit_character.import_character`, from an editor script:
```
# tools/unreal/import_hero.py, run with: python tools/dev.py exec tools/unreal/import_hero.py
from kit_character import import_character
ch = import_character("SourceArt/Models/hero.glb", "/Game/Characters/Hero", sample_rate=30)
ch.mesh, ch.skeleton, ch.physics_asset, ch.materials   # SK_ asset, its Skeleton, PhysicsAsset, material instances
ch.sequences["walk"]                                   # one AnimSequence per glTF clip, keyed by the clip's name
ch.bone("mixamorig:LeftHand")                          # the Skeleton's name for a glTF joint: "mixamorig_LeftHand"
```
- **Where the file goes:** outside `Content/` (`SourceArt/Models/`, where Bozzetto writes), like Dotwork's PNGs: the
  open editor watches `Content/` and would offer to import a dropped file with its own settings **(verify)**. The
  assets remember the source path, so the editor's Reimport finds it. Arguments: `dest` (default
  `/Game/Characters/<stem>`), `sample_rate` (glTF stores no frame rate: Interchange samples at 30 fps without it),
  `loop` (default True), `save` (default: yes, unless `dest` is under `/Temp/`), `materials` (the glTF material pipeline).
- **What it makes:** a fresh Interchange generic pipeline plus the engine's glTF material pipeline (the project's import
  settings do not apply): SkeletalMesh `<stem>`, `<stem>_Skeleton`, `<stem>_PhysicsAsset`, a MaterialInstanceConstant per
  glTF material, and an AnimSequence `<stem><clip>` per clip (`walk` in `hero.glb` becomes `herowalk`).
- **Scale:** glTF metres arrive as centimetres (the 1.80 m golden character is 180.13 cm tall); keep
  `import_offset_uniform_scale` at 1.0, never 100.
- **Facing:** glTF +Y up becomes +Z up, the glTF front (+Z) becomes **+Y**, left (+X) stays +X: the way the UE
  Mannequin's mesh faces, so in a Character turn the mesh component -90 yaw and lower it by the capsule's half height
  (feet are at the origin) **(verify)**.
- **Root bone and names:** the first joint is the root (`mixamorig_Hips`); the armature node is not a bone (the log's
  "Node [...] with a skinned mesh is not root" warning is harmless). `:` in a bone name becomes `_` (`mixamorig:Hips`
  is `mixamorig_Hips`), so sockets, Blueprints and C++ use the underscore names; nothing else in the golden names
  changed (other characters: **(verify)**).
- **Looping and root motion:** glTF has no loop flag; the helper sets each AnimSequence's Loop flag (`loop`, kept
  through a reimport), but the player decides at run time: a SkeletalMeshComponent in Animation Mode "Use Animation
  Asset" with Looping on, `Mesh->PlayAnimation(Walk, /*bLooping=*/true)` in C++, or a Sequence Player's Loop Animation.
  Root motion is off and Force Root Lock is left off on purpose: Hips is the root, so the lock would pin the hips to
  the rest pose and kill their bob. A clip with real root motion needs a root bone above Hips **(verify)**.
- **After the `.glb` changes:** run the script again. Interchange then reimports only the SkeletalMesh, so the helper
  reimports each clip already in `dest` from the file (`InterchangeManager.reimport_asset`); a clip new to the file
  may not be added by that run **(verify)**: import into a new folder then.
- **Playing it in a level:** drop the SkeletalMesh in, set Animation Mode "Use Animation Asset", Anim to Play the
  `walk` sequence, Looping and Playing on (or `PlayAnimation` from BeginPlay). In the commandlet a SkeletalMeshActor
  took `play_animation(walk, True)` (playing, looping), but nothing ticks there, so the visible motion is **(verify)**.
- **Mannequin animations:** to play UE5 Mannequin clips on this skeleton (or Mixamo clips on the Mannequin), make an IK
  Rig per skeleton and an IK Retargeter between them **(verify)**.
- **The check:** `dev.py test` runs `Content/Python/kit_character/test_character_golden.py` through the pythonscript
  commandlet (it needs the PythonScriptPlugin): it imports `data/golden/character/character.glb` twice into `/Temp`
  (never saved; the second run at expected.json's fps, so the frame counts prove the clips were reimported), then
  compares with `expected.json`: every bone under its Unreal name, the root, the height, the axes, both clips (length,
  frames, Loop flag, root motion off), and that `walk` turns the moving bone by at least half its swing, ends where it
  starts and keeps the root in place. Run 2026-11-11 on UE 5.8.4, a fresh adopt-first Blueprint-only project
  (TP_BlankBP plus the PythonScriptPlugin): `check` 0, `test` 0 (no game tests yet, then the 2 Dotwork checks and
  this one passed: 22 bones, `idle` 48 and `walk` 24 frames at 24 fps, `mixamorig_LeftUpLeg` turns 56.00 degrees over
  `walk`), and with expected.json changed (frames, swing) the check failed with exit 1 and a `CHARACTER_DIFF` line each.
  The plain-Python half (`character_spec.py`: glTF names, clip matching, angles) is also checked by the kit without Unreal.

## Gotchas (Claude: read before editing)
1. **Header changes require a full editor restart or a Live Coding-incompatible rebuild.** Prefer building with `dev.py check` and restarting the editor after header/reflection changes. Live Coding handles function body edits only.
2. **Never edit generated files** (`*.generated.h`, `.sln`, `Intermediate/`). Regenerate project files with `dev.py genproj`.
3. **`#include "X.generated.h"` must be the last include** in a header with `UCLASS`/`USTRUCT`.
4. **Add new modules or plugins to `Build.cs`/`.uplugin`** explicitly, or you get linker errors.
5. **Raw `UObject*` members need `UPROPERTY()`** or the GC may collect them. Use `TObjectPtr<>` for UE5 members.
6. **Binary assets cannot merge.** Use file locking or "one person per asset" etiquette. Solo dev: still commit often.
7. **Hard-coded asset paths** break on rename. Use soft references or data-driven lookups.
8. **Tick everything is expensive.** Disable tick by default, enable when needed, prefer timers and events.
9. **Version matters:** many APIs moved between UE 5.x releases. Check the engine version in this file and the matching docs before using an unfamiliar API.
10. **Editor-only code** needs `#if WITH_EDITOR` or an Editor module, or packaging will fail.
11. **Secrets live in Config/ too.** `Config/DefaultCrypto.ini` holds pak encryption and signing keys (Claude is denied it), and Android signing puts `KeyStorePassword`/`KeyPassword` in `Config/DefaultEngine.ini`. Never read those values out or paste them anywhere; keep the repo private if they are committed.
12. **Never load assets by path in a constructor.** Every UCLASS builds its default object when the module loads, so a
    `LoadObject` there runs in every editor command, before a fresh clone has made or pulled its content; the error it logs fails
    commandlets (`dev.py exec`). Load in `BeginPlay` (or use `ConstructorHelpers` only for assets that always exist, such as engine ones).

## Generated or binary (do not hand-edit)
`Content/**/*.uasset`, `*.umap`, `Intermediate/`, `Binaries/`, `Saved/`, `DerivedDataCache/`, `.vs/`, `*.sln`, `*.generated.h`, the kit's generated recipes
(edit `tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py` and `make_materials.py`).
