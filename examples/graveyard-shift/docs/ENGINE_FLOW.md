# Unity Flow

> Every command below was run against Unity 6000.6.6f1 on Windows (see "Verified" under Mapped to Unity). Items marked
> **(verify)** were not.

## Setup
1. Create the project in Unity Hub with the editor version you want. Pick the template (2D, 3D, URP) and record it in an ADR.
2. Check Project Settings > Editor > Asset Serialization = Force Text and Project Settings > Version Control > Mode = Visible Meta Files
   (both default in Unity 6).
3. From this kit: `python scripts/new_game.py --name "<Game>" --engine unity --dest <project folder> --adopt`.
4. Set `UNITY_EDITOR` to the editor executable path (for that exact version). `python tools/dev.py doctor`.

## Daily loop
```
python tools/dev.py check     # batchmode compile, fail on C# errors
python tools/dev.py test      # EditMode tests (use --mode PlayMode for play tests)
python tools/dev.py smoke     # PlayMode tests named Smoke (starter: boots the first Build Settings scene)
python tools/dev.py exec GameKitScenes.CreateStarterScene   # first scene, headless (or your own scene builder)
python tools/dev.py build --target StandaloneWindows64
python tools/dev.py run       # open the project in the editor
```
Close the editor before running batchmode commands (one instance per project).

## Mapped to Unity
| dev.py | What it runs |
|---|---|
| `check` | `Unity -batchmode -nographics -quit -projectPath . -logFile Logs/dev_unity.log` and scans the log for `error CS` |
| `test` | `Unity -batchmode -nographics -projectPath . -runTests -testPlatform EditMode -testResults <xml> -logFile ...` |
| `smoke` | same with `-testPlatform PlayMode -testFilter Smoke`; runs `Assets/Tests/PlayMode/BootSmokeTests.cs` |
| `build` | `Unity -batchmode -nographics -quit -projectPath . -executeMethod GameKitBuild.Build -buildTarget <t> -outputPath <p>` using `Assets/Editor/GameKitBuild.cs` |
| `run` | opens the editor on the project |
| `clean` | removes `Library/` (forces reimport, slow) and `Temp/` after confirmation, or `--yes` |
| `exec` | `Unity -batchmode -nographics -quit -projectPath . -executeMethod <Class.Method>`: scene builders and asset setup in C# |
| `smoke --graphics`, `--screenshot`, `--record` | drops `-nographics` so cameras render; `GameKitCapture` (Assets/Tests/PlayMode) writes PNGs. Capture into `Logs/` (`--record Logs/frames`): `build/` is the player's `Build/` folder on Windows, so `smoke` refuses it |
| `smoke --until M`, `--fail-on M` | scans the Unity log for the markers your scenario test logs |

Test results are read from the NUnit XML (`failed="N"`), not the exit code alone. If nothing passed (no test matched, or every test was
ignored) the command exits 2 and prints the reason, because that is a setup gap, not a failing test.

Verified on Unity 6000.6.6f1, Windows, 2026-10-20, on a project made with `Unity -batchmode -createProject` and then adopted: `check` and
`test` catch a planted compile error and a planted failing assert; `smoke` exits 2 with no scene, passes with one, and exits 1 on an error
logged while the scene loads; `build` writes the player to Build/game.exe (about 45 s). Unity 6.6 ships the Test Framework built in, so no package install
was needed. Known gap: an error logged the moment Play mode starts, before the test begins, is not caught by `smoke`.

**Boot smoke test.** `BootSmokeTests.Smoke_FirstSceneBootsWithoutErrors` loads the first scene in Build Settings and runs 120 frames; Unity
Test Framework fails it on any logged error or exception. It is ignored until you add a scene (File > Build Profiles). The test runner adds
its own `InitTestScene<guid>` to Build Settings during PlayMode runs, so the test skips that one when picking "the first scene".

## Claude and Unity
- Claude edits C#, asmdefs, ScriptableObject definitions, docs, tools. Humans (or a Unity MCP server if you adopt one, record in an ADR) edit scenes, prefabs, animation graphs, shaders graphs.
- **Scenes from code** (no human needed): an editor script builds the scene, wires assets through `AssetDatabase` and
  registers it (`GameKitScenes.AddToBuildSettings`); run it with `dev.py exec YourBuilder.Build`. The level itself can be
  built at runtime from data (and AI Navigation can bake a NavMesh at runtime), so the scene file stays tiny.
- **Unity Behavior graphs** (`com.unity.behavior` 1.0.16) are authored in the editor's graph window: the graph modules and
  node constructors are internal, so code can add custom nodes but cannot wire a graph. For a code-only workflow, write the
  AI in C# (SOP-14: an FSM first); use Behavior when a human will own the graph.
- Pattern: Claude writes the C# component and a spec for the prefab ("add component X, set these defaults, wire event Y").
- Keep logic in `Assets/Scripts/Core` so EditMode tests run fast without a scene.

## Unity MCP (optional, record in an ADR)
AnkleBreaker Unity MCP is a community Unity MCP server (claims 281 tools) seen in a marketplace listing and one video. Unverified here. Before adopting: read its repo and license, commit your work, run it only on a branch, and review the scene and prefab diffs.

**One-prompt clones through MCP (E20, unverified):** a creator connected Unity 6.6 and Blender 5.2 to Claude Code through MCP, with Blender making the models and Unity assembling menus, scenes and gameplay. The MCP bridge had a setting to pick the client (Codex or Claude Code) and a Connect button. Which Unity MCP it was is not stated, so treat this as "it can be done", not a recommendation. Same advice applies: branch, commit, review diffs.

## Assets and audio
- Import audio WAV or OGG, set load type and compression per clip, route through an AudioMixer (Master > Music, SFX, UI).
- Sprites: Pixels Per Unit consistent, Filter Mode Point for pixel art, no compression for small sprites.
- 3D from generators (Tripo and similar): clean in Blender first (SOP-11), import FBX or GLB (GLB needs a glTF importer package **(verify)**).
- Naming: `spr_player_idle.png`, `sfx_jump_01.wav`, `mus_level1.ogg`, `fnt_ui.ttf`; prefabs `PF_<Thing>`, ScriptableObjects
  `SO_<Thing>`; 3D per SOP-11 (`prop_`, `chr_`, ...). Sources and licenses: `docs/RESOURCES.md`, `docs/ASSET_LOG.md`.

## Profiling
Window > Analysis > Profiler and Frame Debugger. Profile a development build, not the editor. See SOP-10.

## Packaging (build)
1. `python tools/dev.py build` runs `GameKitBuild.Build` in batchmode (see `Assets/Editor/GameKitBuild.cs` for target and output folder).
2. Test the built player from a clean folder, not the editor (SOP-06).
3. Development builds for profiling, release builds for players. Strip debug menus (`VERTICAL_SLICE.md`).

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| Batchmode exits instantly, log says project already open | editor still running | close the editor |
| `error CS...` in check | C# compile error | fix, rerun check |
| Missing references after a move | `.meta` mismatch | restore the `.meta`, move assets inside the editor |
| Tests not discovered | missing asmdef reference to the test framework | check `Assets/Tests/EditMode/*.asmdef` |
| Player build fails on editor code | `UnityEditor` used outside `Editor` | move or wrap in `#if UNITY_EDITOR` |

## Field notes (reported, unverified)
**Terrain and RTS-style maps (E16).**
- A video creator on Unity 6 + URP reports the built-in terrain shows black artifacts past about 8 painted layers, and fixed it with the MicroSplat asset (up to 32 layers; URP/Unity 6 support reported as a paid extension). Check the current Unity docs and the asset page before buying. Details in `docs/resources/ai-tools.md`.
- Terrain painting, tree and detail placement are editor work. Claude can drive them through a Unity MCP (see "Unity MCP" above) but you should learn the tools first.
- Pattern for team colors: keep flags/banners as separate meshes or material slots so ownership is a material swap.
- Fog of war and limited-vision forests were done in that project as gameplay systems, so put them in `docs/ARCHITECTURE.md` early.
