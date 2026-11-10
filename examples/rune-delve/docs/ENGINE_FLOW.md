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
| `check` / `build` | `<UE_ROOT>/Engine/Build/BatchFiles/Build.bat <Target>Editor Win64 Development -Project=<uproject> -WaitMutex` (`Build.sh` on Linux/Mac). Blueprint-only projects (no `Source/`) skip it and pass, unless the GameKitShell plugin is enabled: then it builds the engine's `UnrealEditor` target with `-Project`, which compiles only the plugin (into `Plugins/GameKitShell/Binaries/`). A missing MSVC, Windows SDK or .NET Framework SDK, or an open editor with Live Coding, exits 2 with the fix |
| `test` | `UnrealEditor-Cmd <uproject> -ExecCmds="Automation RunTests <filter>; Quit" -TestExit="Automation Test Queue Empty" -unattended -nopause -NullRHI -nosplash -abslog=Saved/Logs/dev_automation.log`, then parses that log (the editor does not print results to stdout). The default filter is `<Game>`, plus `GameKit.` when the GameKitShell plugin is enabled (`+` joins filters); the summary counts the `GameKit.*` tests |
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
("does not look like uproject file but no targets have been found") on a machine without the Windows SDK; with the SDK and the
GameKitShell plugin enabled, `package` of the Blank Blueprint template wrote the game exe under Packaged/ (2026-11-10, "Packaging" below).

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

## Juice and shell plugin (GameKitShell)
`Plugins/GameKitShell/` holds the kit's engine-free game logic (SOP-18 game feel, SOP-19 front end and settings) as one
Runtime module of plain C++ on Unreal's Json module. No UObjects, no world: call it from your actors, components and
widgets. It ships disabled (`"EnabledByDefault": false`), so a project that does not use it builds as before.

| Header (`Plugins/GameKitShell/Source/GameKitShell/Public/`) | What it gives you |
|---|---|
| `GameKitShake.h`, `GameKitHitstop.h`, `GameKitEase.h`, `GameKitFollowCamera.h` | trauma screen shake and its noise, hitstop (`ScaledDt`), 14 easing curves by enum or name, deadzone and look-ahead camera follow |
| `GameKitInputBuffer.h`, `GameKitCoyoteTimer.h`, `GameKitSpring.h`, `GameKitFlashLimiter.h` | buffered presses, coyote time, a damped spring plus `GameKit::Squash`, at most three full-screen flashes per second |
| `GameKitSettings.h`, `GameKitBindings.h` | settings defaults and validated loading (bad fields fixed and listed), rebinding with swaps, button-glyph names |
| `GameKitSaveStore.h`, `GameKitAtomicFile.h` | versioned saves with migrations, a `.bak` of the last good save, crash-safe writes (`.tmp`, flush, rename) |
| `GameKitI18n.h`, `GameKitJson.h` | `Tr` with a fr-CA -> fr -> en fallback, plurals, the pseudo-locale; JSON helpers that never log |
| `GameKitAudioDirector.h`, `GameKitMusicDirector.h`, `GameKitAudioAccess.h` | Wavesmith's audio rules (tools/audio/wavesmith): which take of a sound event plays at what pitch and volume, voice caps, cooldowns and dialogue ducking; music transition plans on the exact sample (beat, bar, phrase, loop end, fades, stingers, synced entry; start sounds on them with a Quartz clock); settings sliders per bus, never twice down one branch, and the arrow for a caption whose sound is off screen |

Turn it on:
1. In the `.uproject`, add `{ "Name": "GameKitShell", "Enabled": true }` to `"Plugins"`.
2. In your module's `Build.cs`, add `"GameKitShell"` (and `"Json"` if your code touches `FJsonObject`) to
   `PublicDependencyModuleNames`, then `#include "GameKitShake.h"` and so on.
3. `python tools/dev.py check`, then `python tools/dev.py test`: it runs your `<Game>` tests and the plugin's `GameKit.*`
   tests and prints how many of those passed. `test --filter GameKit` runs only the plugin's.

A Blueprint-only project (no `Source/`) has no `Build.cs`, so skip step 2. `check` then compiles the plugin once through
the engine's own `UnrealEditor` target (the C++ toolchain from docs/ENGINE.md is needed for that), and `test` runs its
`GameKit.*` tests; until then `test` exits 2 with "run check first", because the editor cannot load a plugin module
that was never built. Blueprints cannot call the plugin (plain C++, no Blueprint nodes): to use it in the game, add a
C++ class (Tools > New C++ Class), which makes it a C++ project, and do step 2.
   If you only turned the plugin on in the `.uproject` (step 1 without step 2), UnrealBuildTool may say "Target is up
   to date" and skip it, and `test --filter GameKit` then finds no tests: delete
   `Intermediate/Build/Win64/x64/<Game>Editor/Development/Makefile.bin` (seen on UE 5.8) and run `check` again.

The plugin's tests: `GameKit.Golden.Juice.<case>`, `GameKit.Golden.Shell.<case>`, `GameKit.Golden.Audio.<case>`,
`GameKit.Golden.Music.<case>` and `GameKit.Golden.Access.<case>` (one test per case) read `data/golden/juice.json`,
`shell.json`, `audio.json`, `music.json` and `access.json` from the project folder and compare every value with the kit's reference
(`tools/golden_vectors.py`) within the file's tolerance; `GameKit.Golden.Coverage` fails when a vector type has no case;
`GameKit.Shell.*` writes real files in a temp folder (a crash between write and rename leaves the old file, a corrupt save
falls back to the `.bak`, a newer game's save is never overwritten). Keep `data/golden/` in the repo.

- Player files: `FPaths::ProjectSavedDir() / TEXT("GameKit/settings.json")` and `.../save.json` (the user's folder in a
  packaged game). The headers' Usage blocks show each call; settings and saves are `FJsonObject`, so keys a newer build
  wrote survive.
- Wire the values to the engine yourself: `UGameUserSettings` for window mode, resolution and vsync, Sound Classes or
  submixes for the volumes, your Enhanced Input mapping for the binding strings (`key:space`, `pad:south`), and
  `EffectiveShake` into your camera shake. The menus come with the plugin's GameKitShellUI module ("Shell screens"
  below); the logic module is what runs under them.
- Differences from the reference: keys of `TMap` and `FJsonObject` are case-insensitive (two actions or table keys
  that differ only in case collapse into one), and Unreal's JSON reader needs an object or array at the top level.
- Change the logic: edit the plugin, keep `test` green; when the kit's reference changes, the vectors change with it.
- Verified on UE 5.8 (Windows, VS 2022 Build Tools / MSVC 14.44, 2026-11-01) in a minimal C++ project (K01): `check`
  builds the plugin without warnings, `test` passes every `GameKit.*` test and the game module links against the
  plugin; a planted wrong vector value and an unknown case type both fail `test`. In a Blueprint-only project made
  from UE 5.8's Blank Blueprint template (K01, 2026-11-02): `test` before `check` exits 2 (the plugin module is
  missing), `check` compiles the plugin with no warnings, then `test` passes all 70 `GameKit.*` tests headless.
  Linux and macOS are untested, and so is turning the plugin on from the editor's Plugins window (Edit > Plugins,
  then restart); in a Blueprint-only project run `check` before opening the editor, or it reports the module as
  missing **(verify)**.

## Shell screens (GameKitShellUI)
The plugin's second module draws the shell's screens over your game, the same set as the Godot, LÖVE and web
overlays (SOP-19, SOP-20): title with the telemetry question, main menu, settings with the tabs Display, Audio,
Controls (rebinding with swaps, "press a key", the one-handed layouts of `data/input/presets.json`, reset),
Accessibility (text size, subtitles and their size, background and speaker names, barks and sound captions, the
colour-blind palette, reduce motion, shake, gentle flashes, hold to toggle, difficulty, game speed, readable font,
line spacing, subtitles that wait, timing windows, hold to repeat, menu narration), Language (and the telemetry
consent), loading, play, pause with Resume, "What now?", Dialogue history, Settings and Quit to title, credits from
`CREDITS.md`, and the subtitle bar.

**Why Slate from C++, not UMG assets:** a `WBP_` widget is a binary `.uasset` Claude cannot edit and the kit cannot
ship as text; Slate widgets are C++ in the plugin, build in a Blueprint-only project through `check`, run headless
in the automation tests, and draw to a PNG without a game window. UMG is only a dependency for that capture
(`FWidgetRenderer`). Your own HUD can still be UMG; the shell sits above it (Z order 100).

Turn it on: enable the plugin (above), then either `Config/DefaultGame.ini`
```
[/Script/GameKitShellUI.GameKitShellSettings]
bShowScreens=True
```
or `-GameKitShell` on the command line for one run. `UGameKitShellSubsystem` (a game-instance subsystem) adds the
widget to the viewport after the first map loads, gives it keyboard focus and sets the first player controller to
Game and UI input **(verify in your project: a game that sets its own input mode afterwards must leave the widget
focused)**. Wire the game to it:
- `GetGameInstance()->GetSubsystem<UGameKitShellSubsystem>()->OnShellEvent.AddUObject(this, &AMyGame::OnShell)`:
  "play" (the loading screen is over: start or unpause), "resume", "quit_title" (reset the level), "quit",
  "settings_changed" (read the settings again: `GetModel()->Settings`, `UGameUserSettings` for the window,
  Sound Classes for the volumes, `access.timing_scale` into your buffers), "consent".
- `Say(Speaker, Text)` shows a subtitle and records it for "What now?" and the history; `SetObjective(Text)` sets the
  goal "What now?" shows (#167). Both are `BlueprintCallable`, as are `SettingNumber`/`SettingFlag` and `TopScreen`,
  so a Blueprint-only project reads `access.auto_repeat` or `audio.music` without C++.
- While the top screen is "play" the widget draws nothing but subtitles; `pause` (Escape, Start) opens the pause menu.
- Menu narration (#165): every focus, value and screen change makes a line (`GetModel()->LastNarration`); with
  `access.narration` on the model calls `OnNarrate`, which logs it. Speak it through Unreal's TextToSpeech plugin or
  the platform's voice **(verify: not wired, no voice on the test machine)**.
- `FGameKitAutoRepeat` (GameKitAutoRepeat.h) is "hold to mash" for `access.auto_repeat`, as on the other engines.
- Keys arrive as binding strings (`GameKitShellInput.h`: SpaceBar is `key:space`, the bottom face button `pad:south`);
  the pad's make comes from the name its input plugin registers for the device (`FInputDeviceRegistry`), with the
  C++ shell's hints plus Nintendo ones: `pad_xbox`, `pad_playstation`, `pad_switch` or `pad_other`, and `auto`
  prompts follow it (Switch and unknown pads get the generic positional set). What a pad is called depends on the
  plugin: on Windows, XInput and GameInput report every pad as an Xbox one (Steam Input and DS4Windows present a
  PlayStation pad as one too), the WinDualShock plugin reports Sony pads, Linux passes SDL's pad names
  **(verify: only the name-to-make mapping is tested, no pad on the test machine)**. The left stick moves the focus
  like the D-pad, with hysteresis (pressed past 0.5 or `input.deadzone`, let go under 0.3), one step per push.
- Analog input through the shell (#274, as Bevy's `Intent`): `GetStick()` is the left stick with the player's
  `input.deadzone` (radial, then rescaled from 0, so a stick just past it gives a small value) and `input.invert_y`
  (up is +Y), `GetTrigger(bRight)` a trigger from 0 to 1 (a 0.05 rest deadzone removed), `IsActionHeld(Action)` and
  `GetHeldActions()` the game actions held now (keys and buttons, plus the `move_*` the stick leans past the deadzone,
  at least 0.2). All `BlueprintPure`, all zero outside play, so a menu never leaks a held trigger into the game; the
  maths is `GameKitAnalog.h`. The widget lets the stick, the triggers and the keys through to your own input as well
  **(verify with a pad: only the model is tested, no pad on the test machine)**.
- Debug builds (not Shipping) add the **juice demo** to the main menu (a box to hit: trauma shake, hitstop, squash
  spring, gentle flashes through the limiter, follow camera with its deadzone drawn, buffered jump with coyote time,
  a guard on `interact` that honours hold to toggle, moving by held keys or the stick), the **pseudo** language in the
  Language tab, and the **F8 bug report**: `bug_<time>/` in the data folder with `bug_<time>/info.txt`,
  `bug_<time>/log_tail.txt` (the last 200 log lines), `settings.json` and `screenshot.png` (the viewport, a frame
  later), and a toast.
- **Crash files:** while the screens run, a fatal error writes `crashes/crash_<time>.txt` in the data folder (version,
  engine, OS, the error, the last 60 log lines, the settings) from `FCoreDelegates::OnHandleSystemError`, before
  Unreal's own crash reporter; nothing leaves the machine. `smoke --drive crash` proves the writer with a planted error
  through the same handler and does not crash the editor (an unattended editor crash may be sent to Epic by its crash
  reporter) **(verify: the handler on a real fatal error in a packaged game is not tried)**.
- Strings: `data/i18n/en.json` and `fr.json` (the LÖVE shell's tables); add a locale by adding a file (`package` ships
  the whole `data/` folder: "Packaging"). The version on the title is the project version from Project Settings.

Scripted runs (the plugin's `GameKit.Screens.Drive` and `.Show` tests, headless on the model):
```
python tools/dev.py smoke --drive menus                                # settings changed and saved: SETTINGS_WRITTEN
python tools/dev.py smoke --drive crash                                # exit 1 on purpose: CRASH_WRITTEN <file>
python tools/dev.py smoke --drive bug                                  # F8 on the menu: DRIVE_BUG <folder> (a GPU, for the picture)
python tools/dev.py smoke --drive pseudo --locale pseudo               # every screen: PSEUDO_PASS, or PSEUDO_FAIL lines
python tools/dev.py smoke --drive pseudo-plant --locale pseudo         # exit 1 on purpose, naming plant.too_small
python tools/dev.py smoke --drive show:juice --screenshot captures/juice.png   # the box hit: DRIVE_JUICE
python tools/dev.py smoke --drive show:settings --screenshot captures/settings.png   # a picture (the editor off-screen, a GPU)
python tools/dev.py smoke --drive access:res=1280x800,scale=2,pad      # the sweep's tour: ACCESS_* lines
python tools/access/sweep.py                                            # runs the tour at both sizes and checks it
python tools/dev.py test --filter GameKit.Screens                       # the screens' own tests (rows, keys, rebinding, hold ...)
```
`--data-dir` keeps a settings folder between runs (default: a fresh `Saved/GameKitSmoke`; one inside `Packaged/`,
`Saved/StagedBuilds/` or `Binaries/` is refused, exit 2), `--locale fr` shows another
language. Screens for `show:`: title, main_menu, settings, pause, help, history, credits, loading, subtitle, juice
(the box just hit, inside the hitstop; `DRIVE_JUICE` lists hits, trauma, frozen, squash, flash and the ring, and the
drive fails unless every one took). The pseudo drive checks each screen, each settings tab at its top and its end,
the "press a key" prompt, the juice demo and the pause pages: a text wider than its column, or not through `T()` (no
leading `[`), is a `PSEUDO_FAIL` line (without `--locale pseudo` it switches and says so). The
access report describes the 1920x1080 design (scaling "exact": the view scales it to the window), each text's size,
colours and whether it fits its column (measured with Slate's font service), and which rows the arrow keys reach; a
`res=` option is noted, not applied. Paths given to `--screenshot` and `--data-dir` may contain spaces, and so may
the project folder: dev.py passes every path the editor gets (`-abslog=`, `-script=`, the drive's) as `-Name="a b"`
with forward slashes, the form Unreal's command line reads whole, and the shader check names its script by its
place on the editor's Python path (kit_shaders/shader_check.py under `Content/Python/`), so no path sits inside
`-ExecCmds` (K01: UE 5.8 on Windows, 2026-11-10, `check`, `test`, `exec` and the drives from a folder with a space); a double quote is refused.

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
   With the GameKitShell plugin enabled the package also carries, as loose files: `data/` (the string tables, input
   presets, colour palettes and your own data files, at `Packaged/<Platform>/<Project>/data/`, where
   `FPaths::ProjectDir()` points in the packaged game as in the editor), staged by the plugin's
   `Plugins/GameKitShell/Config/Game.ini` (`+DirectoriesToAlwaysStageAsNonUFS=(Path="../data")` under `ProjectPackagingSettings`; Unreal layers an enabled
   plugin's Game.ini over your DefaultGame.ini, so there is nothing to merge), and the readable font under the
   plugin's `Resources/Fonts` (a `RuntimeDependencies` line in `GameKitShellUI.Build.cs`). `data/golden/` and
   `data/shaders/` (test files, about 200 KB) go along: Unreal stages a folder whole. Without `data/` the menus show
   their keys (`menu.play`); the log names the folder it read (`i18n: string tables en, fr from ...`). K01: a
   Blueprint-only project with the plugin packaged in about 4 minutes on UE 5.8 (Windows, 2026-11-10); its exe, started
   from another folder with `-GameKitShell -GameKitLocale=fr`, read `data/i18n` and narrated in French, and the
   plugin's `GameKit.Screens` tests passed inside it (`-ExecCmds="Automation RunTests GameKit.Screens; Quit"`).
   `CREDITS.md` is not staged yet: the packaged credits screen shows its placeholder **(verify, kit issue)**.
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
