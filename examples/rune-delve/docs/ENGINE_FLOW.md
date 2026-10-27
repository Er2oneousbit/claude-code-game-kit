# Unreal Flow

Engine-specific workflow for Unreal Engine 5. Universal process lives in `docs/sop/`.

> **Honesty note.** Verified on UE 5.8 (details under "Mapped to Unreal"); `run`, `genproj` on a real C++ game and
> Blueprint-only `package` are untested. Paths and flags move between UE releases: items marked **(verify)** are the likeliest
> to differ. If a command fails, give Claude the exact error and your UE version.

## Setup (adopt-first)
1. Install Unreal (Epic Launcher) and, for C++ projects, Build Tools for Visual Studio 2022 with the "Desktop development with C++"
   workload plus the ".NET Framework 4.8 SDK" component (see docs/ENGINE.md).
2. In the editor, create the project (C++ or Blueprint). Use a name without spaces: it becomes the `.uproject` name and the
   `<Game>.Smoke` test filter. Keep the path short (Windows 260-character limit). Close the editor (Live Coding blocks builds).
3. From the kit: `python scripts/new_game.py --name "<Game>" --engine unreal --dest <the folder holding the .uproject> --adopt`.
4. Set `UE_ROOT` persistently (Windows: `setx UE_ROOT "C:\Program Files\Epic Games\UE_5.x"`, then open a new terminal;
   macOS/Linux: export it in your shell profile).
5. `git lfs install` (once per machine), then `python tools/dev.py doctor`.

## Daily loop
```
python tools/dev.py check     # compile the editor target (UnrealBuildTool)
python tools/dev.py test      # run automation tests headless (NullRHI)
python tools/dev.py smoke     # run the smoke test group (you define the tests)
python tools/dev.py run       # open the project in the editor
python tools/dev.py genproj   # regenerate IDE project files
```

## Mapped to Unreal
| dev.py | What it runs |
|---|---|
| `check` / `build` | `<UE_ROOT>/Engine/Build/BatchFiles/Build.bat <Target>Editor Win64 Development -Project=<uproject> -WaitMutex` (`Build.sh` on Linux/Mac). Blueprint-only projects (no `Source/`) skip it and pass. A missing MSVC, Windows SDK or .NET Framework SDK, or an open editor with Live Coding, exits 2 with the fix |
| `test` | `UnrealEditor-Cmd <uproject> -ExecCmds="Automation RunTests <filter>; Quit" -TestExit="Automation Test Queue Empty" -unattended -nopause -NullRHI -nosplash -abslog=Saved/Logs/dev_automation.log`, then parses that log (the editor does not print results to stdout) |
| `smoke` | same as `test` with filter `<Game>.Smoke` (C++ tests; a Blueprint-only project has none, use `test --filter` on its functional tests). `--filter Boot` runs `<Game>.Smoke.Boot` only; `--until M` and `--fail-on M` check scenario markers your tests log, like the other overlays. Tests run with `-NullRHI`, so nothing renders: capture screenshots from the game itself (a `-record=<dir>` option calling `FScreenshotRequest::RequestScreenshot`, as `examples/rune-delve` does) |
| `package` | `RunUAT BuildCookRun -project=... -noP4 -platform=<host> -clientconfig=<--config, default Development> -build -cook -stage -pak -archive -archivedirectory=Packaged` (Development verified on UE 5.8; `--config Shipping` for the release build) |
| `exec <script.py>` | `UnrealEditor-Cmd <uproject> -run=pythonscript -script=<script>`: editor Python headless (asset imports, maps, data assets). Needs the PythonScriptPlugin enabled for the editor. The script's prints are shown; any `LogPython: Error` (a traceback) fails it |
| `run` | launches `UnrealEditor` with the uproject |
| `genproj [--vscode]` | `Build.bat -projectfiles -project=<uproject> -game -progress` (UBT's project-file mode, plus `-rocket` on a Launcher engine and `-VSCode` with `--vscode`) **(verify on a real C++ game)** |
| `clean` | removes `Intermediate/`, `Binaries/`, and optionally `DerivedDataCache/` (asks unless `--yes`) |

Test pass/fail is decided by **parsing the log** (`Result={Success}` / `Result={Fail}` lines) because exit codes are not reliable across versions.
Verified on UE 5.8 (launcher install, Windows, VS 2022 Build Tools 17.14 / MSVC 14.44, 2026-10-20) with a minimal C++ project:
`check` compiles (about 1 minute) and fails on a planted compile error; `test` runs the project's tests and fails on a planted
`Result={Fail}`; `smoke` runs only `<Game>.Smoke.*`; `package` wrote the game exe under Packaged/ (about 4 minutes); `clean` works.
A Blueprint-only project also ran `test --filter System.Core.Math` (40 engine tests). Packaging a Blueprint-only project failed in UAT
("does not look like uproject file but no targets have been found") on a machine without the Windows SDK; not retested since **(verify)**.

## The Claude + Unreal division of labor
- **Claude edits:** C++ (`Source/`), Build.cs, Config/*.ini (carefully), docs, tools, test code, CSV/JSON that feed DataTables.
- **You (or an MCP plugin) edit:** Blueprints, materials, levels, UI layout, animation graphs, Niagara.
- **Pattern:** Claude writes a C++ base class with exposed properties and events, plus a spec for the Blueprint child
  ("create BP_Enemy deriving from AEnemyBase, set these defaults, hook this event"). You build it in the editor.
- **With an Unreal MCP plugin:** Claude can inspect actors and assets and make editor changes. Treat it like any tool that can change
  binary assets: commit before a big session, review changes in the editor, do not let it run unattended on `main`.
  Record plugin choice in an ADR.

## Content from scripts (no editor UI)
Binary content can still come from text: an editor Python script run by `python tools/dev.py exec tools/unreal/<script>.py`.
- Enable the plugin in the `.uproject`: `{ "Name": "PythonScriptPlugin", "Enabled": true, "TargetAllowList": [ "Editor" ] }`.
- Import: `unreal.AssetImportTask` (filename, destination_path, `automated=True`, `save=True`, `replace_existing=True`) and
  `AssetToolsHelpers.get_asset_tools().import_asset_tasks([...])`. FBX goes through Interchange: a rigged character becomes a
  skeletal mesh, its skeleton and one AnimSequence per take, named `<mesh name><take name>` (e.g. `character-orcwalk`).
  An FBX with a rig and no character (a Kenney gate) also imports as a skeletal mesh with its animation. OGG and WAV import directly.
- A map: `EditorLoadingAndSavingUtils.new_blank_map(False)`, `EditorLevelLibrary.spawn_actor_from_class(...)` (a PlayerStart,
  a NavMeshBoundsVolume: its brush is 200 cm, scale it), `save_map(world, "/Game/Maps/X")`.
- Print what you imported (sizes from `get_bounding_box()`), so C++ layouts use measured sizes.
- Compile first. In a C++ project the editor (and so `exec`, `test`, `smoke`) cannot load until `dev.py check` has built the
  game module once; a fresh clone runs `check` before the content script.
- Assets your code loads only by path are not cooked unless listed: `+DirectoriesToAlwaysCook=(Path="/Game/Art")` under
  the ProjectPackagingSettings section of your project's Config/DefaultGame.ini.
Worked example: the kit's Rune Delve example (`examples/rune-delve` in the kit repo), whose build_content.py script imports 120 assets and makes the map.

## Data-driven content (so Claude can change things)
- Gameplay numbers: `UDataAsset` classes or DataTables imported from CSV/JSON. Keep source CSV/JSON in the repo (`Content/Data/Source/` or `Data/`), reimport in the editor.
- Config knobs: `UDeveloperSettings` subclasses appear in Project Settings and are stored in `Config/`.
- Tuning without recompiling: console variables (`TAutoConsoleVariable`) and `exec` commands.

## Tests
- **Simple automation tests:** `IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMyTest, "MyGame.Logic.CoyoteTimer", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter)`.
  Use for pure logic (math, timers, state machines). Since UE 5.5 the context mask is the free constant
  `EAutomationTestFlags_ApplicationContextMask` (an underscore, not `::`); the old spelling no longer compiles (verified on 5.8).
- **Smoke tests:** name them `<Game>.Smoke.*` so `dev.py smoke` finds them. Example: load the default map, spawn the player, tick a few frames, assert no errors.
- **Smoke tests that play the map:** `AutomationOpenMap("/Game/Maps/X")` in `RunTest` loads the map and starts Play In Editor
  (it queues a "start PIE" latent command). Calling it again from *inside* a latent command queues that start at the END of
  the test's queue, behind every later command, so a test that runs several sessions waits forever. For one session per
  run, request PIE yourself in the latent command: `GEditor->RequestEndPlayMap()`, then `GEditor->RequestPlaySession(Params)`
  and `GEditor->StartQueuedPlaySessionRequest()` (the editor's own code does the same; K01, UE 5.8).
- Keep logic in plain C++ classes or `UObject`s that do not need a world, so tests are fast.
- Spec-style (`BEGIN_DEFINE_SPEC`) is also fine, record the choice in an ADR.

## Source control (Git + LFS)
- `.gitattributes` in this repo routes `.uasset`, `.umap`, textures, audio, and meshes through LFS. Run `git lfs install` before the first commit.
- Never commit `Intermediate/`, `Binaries/`, `Saved/`, `DerivedDataCache/`. See `.gitignore`.
- Commit often. Binary assets do not merge, so small commits are your rollback safety net.
- Large teams use Perforce. For a solo or small Git team, LFS is fine. Record the choice in an ADR if it changes.

## Assets and audio
- Import audio as WAV, build MetaSounds or Sound Cues, route through Sound Classes and Submixes (Master > Music, SFX, UI).
- Naming prefixes in `ENGINE.md`. Content folder structure by feature (`Content/Characters/`, `Content/Levels/`, `Content/UI/`), not by asset type.
- Marketplace content comes through **Fab** **(verify current terms)**. Log every pack in `docs/ASSET_LOG.md`, including license and engine version.
- Sources of free or CC0 content: see `docs/RESOURCES.md`.
- Tripo AI lists an Unreal plugin **(verify)**. Generated meshes are drafts: clean in Blender (SOP-11), then import FBX/GLB, and keep the plan or tier in `ASSET_LOG.md`.

## Profiling
- In editor/PIE: `stat fps`, `stat unit`, `stat game`, `stat gpu`. Unreal Insights for deep traces.
- Profile a **packaged Development or Test build**, not PIE, for release truth. See SOP-10.
- Typical culprits: Tick on many actors, Blueprint heavy loops, overdraw, unculled draw calls, shader complexity, large textures, GC hitches.

## Packaging
1. Set the default map and startup settings in Project Settings > Maps & Modes.
2. `python tools/dev.py package --config Shipping --platform Win64` (output in Packaged/, which git ignores). Verified with the default Development config on UE 5.8.
3. Test the packaged build on a clean machine (SOP-06). Check logs under `Saved/Logs/` of the packaged game.

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| Unresolved external symbol | module missing in `Build.cs` | Add to `PublicDependencyModuleNames`, rebuild |
| Editor says modules are out of date | headers changed without rebuild | `dev.py check`, restart editor |
| Class does not appear in editor | missing `UCLASS()`/`GENERATED_BODY()` or build failed | Check compile output, reopen editor |
| Packaging fails on editor-only code | code not guarded | Wrap in `#if WITH_EDITOR` or move to an Editor module |
| Crash after hot reload/Live Coding | reflection changes under Live Coding | Close editor, full rebuild, reopen |
| LFS pointer files in `Content/` | LFS not installed on this machine | `git lfs install`, `git lfs pull` |
| `Platform Win64 is not a valid platform to build. SDK validation failed` | no MSVC / Windows SDK | Install Build Tools for Visual Studio, workload "Desktop development with C++" (no IDE needed; VS Code works as the editor) |
| `Could not find NetFxSDK install dir` | .NET Framework SDK component missing | Visual Studio Installer > Modify Build Tools > add ".NET Framework 4.8 SDK" |
| `Unable to build while Live Coding is active` | an Unreal editor is open on this engine, any project | Close it, or compile inside it with Ctrl+Alt+F11 |
| `test` says no tests matched, but tests exist | an older `dev.py` read stdout only | Update `tools/dev.py` (it reads the run's log file, Saved/Logs/dev_automation.log) |

## Field notes (reported, unverified)
**One-prompt AAA-style FPS (E27).** A creator reports Claude building a one-mission tactical FPS in Unreal Engine 5 with Blender assets from a single big prompt in about 4 hours, with graphics, menus and settings that worked, and weak spots in the surrounding level and enemy tuning. He says it located Unreal and Blender itself without an MCP. Treat as "possible", not a recipe. For real work, start with one feature, keep the `dev.py` command contract, and read `docs/sop/SOP-09` for the interaction smoke checklist. Needs a strong GPU and about 50 GB of install.
