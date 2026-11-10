# Engine: Unity (C#)

> Imported into CLAUDE.md. Long-form flow is in `docs/ENGINE_FLOW.md`. Written quickly, clean up later.

## Version and setup
- **Unity version:** (SET EXACT VERSION, from `ProjectSettings/ProjectVersion.txt`). Use the same editor version everywhere.
- **Env var:** `UNITY_EDITOR` = full path to the Unity editor executable for that version (Unity Hub installs it per version, e.g.
  `C:/Program Files/Unity/Hub/Editor/<version>/Editor/Unity.exe`; macOS `/Applications/Unity/Hub/Editor/<version>/Unity.app`).
  `dev.py doctor` checks.
- **Adopt-first:** create the project in Unity Hub, then from the kit run
  `python scripts/new_game.py --name "<Game>" --engine unity --dest <project folder> --adopt`. The scaffold does not generate `ProjectSettings/`.
- **Language:** C#. Render pipeline, input system, and UI toolkit choices go in an ADR.
- **Source control:** text serialization and visible meta files are required (Project Settings > Editor > Asset Serialization = Force Text; Project Settings > Version Control > Mode = Visible Meta Files;
  both are the Unity 6 defaults). Commit every `.meta` file.
- **Tests:** Unity Test Framework (EditMode for pure logic, PlayMode for scene behavior).

## Layout
```
Assets/Scripts/Core/     engine-agnostic logic (no UnityEngine types where possible), unit tested: juice (Shake, Hitstop,
                         Ease, FollowCamera, InputBuffer, CoyoteTimer, Spring, FlashLimiter), shell logic
                         (GameSettings, Bindings, SaveStore, I18n, AtomicFile, Json, DialogueData) and audio decisions
                         (AudioDirector, MusicDirector, AudioAccess), checked against data/golden/*.json
Assets/Scripts/Shell/    the front end on UI Toolkit (Game.Shell assembly): Shell (settings, strings, data folder),
                         FrontEnd (the screen flow), Screens/ (title, main menu, settings, pause, What now?, history,
                         credits, loading), SubtitleBar, PlayWorld (the placeholder game), Narrator, ShellInput,
                         AccessAudit and SmokeDrive (`dev.py smoke --drive`)
Assets/Scripts/Game/     gameplay MonoBehaviours and ScriptableObjects; AudioEventPlayer, MusicPlayer play the audio decisions
Assets/Editor/           editor-only code (GameKitBuild.cs; GameKitScenes.cs builds the starter and shell scenes;
                         GameKitShaders.cs checks the shader recipes)
Assets/Resources/GameKit/  the shell's panel theme (.tss) and the readable font (Atkinson Hyperlegible, OFL)
Assets/Shaders/Kit/      the kit's shader recipes as unlit shaders, Kit/<name> (generated)
Assets/Tests/EditMode/   EditMode tests (own assembly definition)
Assets/Tests/PlayMode/   PlayMode tests, incl. BootSmokeTests and ShellSmokeTests (what `dev.py smoke` runs; the second
                         also runs `--drive` scenarios) and AudioPlayModeTests (AudioEventPlayer on real AudioSources:
                         `dev.py test --mode PlayMode --filter Audio`)
Assets/Art, Audio, Prefabs, Scenes/   content (see docs/ASSET_LOG.md); Scenes/Shell.unity is the kit's front end
data/                    i18n/ string tables (en, fr), input/presets.json (one-handed layouts), access/colours.json,
                         dialogue/sample.built.json, golden/ test vectors; a build copies the first four into
                         Assets/StreamingAssets/ (GameKitBuild.SyncData), which is generated: do not edit it
Packages/manifest.json   package list (edit through the Package Manager or with care)
ProjectSettings/         project config (text, edit with care)
```

## The shell (the kit's screens, #168)
- `python tools/dev.py exec GameKitScenes.CreateShellScene` makes the shell scene (`Shell.unity` under `Assets/Scenes/`:
  a camera and the FrontEnd component) and puts it first in Build Settings: the game opens on the title. Until then
  `smoke --drive` exits 2 and says so. Every screen is built in
  code on a UI Toolkit panel (1280x720 reference, scaled so the smaller side fits), so there is no UXML or USS to
  keep in step; the panel theme is Unity's default runtime theme (`Assets/Resources/GameKit/GameKitTheme.tss`).
- Settings rows come from `GameSettings.Fields(section)` (the schema): a new field needs its `setting.<section>.<field>`
  string in `data/i18n/en.json` (and `value.<field>.<choice>` for a choice) and shows up on its tab.
- The accessibility baseline (SOP-20) is in place: subtitles (size, background, speaker names, barks, captions,
  wait-for-accept), text scale, the readable font and line spacing, the colour-blind palette (`Shell.I.Palette()`,
  `data/access/colours.json`), remapping with conflict swaps and the one-handed layouts, reduce motion and the flash
  limit settings, `timing_scale` / `auto_repeat` (`ShellInput` repeats a held action) / `subtitle_hold`, menu
  narration (the system's speech: PowerShell on Windows, `say`, `spd-say`), "What now?" and "Dialogue history" on
  the pause menu (`Shell.I.SetObjective`, lines recorded by the subtitle bar).
- Input: `ShellInput` reads the player's bindings through the Input System package when it is installed and active
  (Active Input Handling "Input System Package (New)" or "Both"), else through the Input Manager (the default of a
  `-createProject` project). The package is optional: `Game.Shell.asmdef` sets `GAMEKIT_INPUT_SYSTEM` from its
  `versionDefines` only when `com.unity.inputsystem` is in the project. On the Input System every binding works on any
  pad it knows (`Gamepad.current`). On the Input Manager gamepad buttons follow the Windows XInput order, the left
  stick reads the default `Horizontal`/`Vertical` axes, and the d-pad and the triggers read the axes
  `GameKitScenes.CreateShellScene` adds (`exec GameKitScenes.AddInputAxes` on its own: joystick axes 6, 7, 9 and 10,
  the Windows layout **(verify on other platforms and with a physical pad)**). Triggers (`pad:l2`, `pad:r2`) are axes,
  pressed past half way, on both. Active Input Handling set to the Input System without the package installed falls
  back to UI Toolkit's events: the menus work, custom pad bindings are not read.
- Line spacing adds space between the menus' lines and paragraphs: UI Toolkit has no line-height, so lines inside one
  wrapped paragraph keep the font's spacing **(verify: a later Unity may add it)**.
- Not here yet (Godot, LÖVE and web have them): crash files, telemetry rows, the pseudo-locale drive, the bug report
  key, a juice demo. `--locale pseudo` still runs the pseudo-locale on every string.

## Conventions
- C# standard style: `PascalCase` types and methods, `_camelCase` private fields, `[SerializeField] private` over public fields.
- Logic in plain C# classes (testable), MonoBehaviours stay thin glue.
- Tunables in `ScriptableObject` assets or config files, not literals.
- Logging: a small `Log` wrapper with channels, no stray `Debug.Log` in committed code.
- Use `Time.deltaTime` in `Update`, `Time.fixedDeltaTime` in `FixedUpdate`. Physics in `FixedUpdate`.
- Assembly definitions (`.asmdef`) per folder group for fast compile and test isolation.
- 3D models from `tools/bozzetto/bozzetto.py` land in `Assets/Models/` as `.glb`: Unity needs a glTF importer package
  for them (glTFast, `com.unity.cloud.gltfast`), or export FBX from Blender instead **(verify for your Unity version)**.
  A rigged character from `bozzetto.py rig make` has Mixamo bone names: set its rig to Humanoid so Unity maps them
  and Mixamo-style clips play on it **(verify: not yet tested in Unity)**.
  A `--material vertex` model keeps its colours in glTF `COLOR_0`: check that it is not white, because Godot ignores
  them by default (#202) and whether glTFast's materials use them is not tested here **(verify)**.
- **Shaders:** `new Material(Shader.Find("Kit/flash"))` (or a material asset using it) on a SpriteRenderer, a quad or
  any UV-mapped mesh; `material.SetFloat("u_amount", 1f)`, vectors with `SetVector("u_flash_color", ...)`, a second
  picture as `_AuxTex`. Coordinates run 0 to 1 over the UVs: `u_texel` is one over the picture's size in texels,
  `u_canvas` the size pixel parameters (`u_light_pos`) are given in. Post effects (`crt`, `vignette`, `colorblind`)
  are `Graphics.Blit(source, destination, material)` (Built-in) or a full-screen pass (URP). Textures want Filter
  Mode Point for pixel art. They are plain unlit passes, drawn by the Built-in pipeline and by URP (both checked);
  HDRP is not checked. `check` compiles them (`ShaderUtil`), `smoke --shaders` draws each and compares it with its
  golden image (a graphics device: no `-nographics`).

## Gotchas (Claude: read before editing)
1. **Never hand-edit** `Library/`, `Temp/`, `Logs/`, generated `.csproj`/`.sln`/`.slnx`. (`Logs/` is ignored by git, so `dev.py smoke` captures go there.)
2. **Never delete or hand-edit `.meta` files** or you break asset references. Move files in the Unity editor or move the `.meta` with the file.
3. **Scenes and prefabs are YAML**, fragile to hand edit, merge conflicts are painful. Prefer code and ScriptableObjects; make structural scene edits in the editor or in an editor script run headless with `python tools/dev.py exec Class.Method` (`Assets/Editor/GameKitScenes.cs` shows the pattern).
4. **Serialized fields:** renaming a field loses data unless `[FormerlySerializedAs]` is used.
5. **Batchmode needs the project closed** in the editor, only one Unity instance can open a project.
6. **Compile errors block everything**, including tests. Fix compile first (`dev.py check`).
7. **Editor-only code** goes in an `Editor` folder or `#if UNITY_EDITOR`, or player builds fail.
8. **Version matters:** APIs and package names changed across Unity 2022, Unity 6 and later. Verify against the project's version and docs.
9. **ScriptableObject field defaults only seed a new asset.** Change a default in C# later and the existing `.asset` keeps the old value, which
   is what the game reads. Tests that build `new MyTuning()` see the new value, so tests and game disagree silently. Load the asset in tests
   (`AssetDatabase.LoadAssetAtPath` in EditMode), and change tunables in the asset, or reset it from code with a `dev.py exec` method.
10. **The GUI editor needs a signed-in Unity Hub.** `dev.py run` (the editor window) waited at licensing on a machine where
    every batchmode command (`check`, `test`, `smoke`, `build`, `exec`) ran fine; sign in to Unity Hub once before `run` (K01).

## Generated or binary (do not hand-edit)
`Library/`, `Temp/`, `Logs/`, `UserSettings/`, `*.csproj`, `*.sln`, `*.slnx` (Unity 6.6 writes the new solution format), built players in `Build/`, the kit's shaders in
`Assets/Shaders/Kit/` (edit `tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).
