# Engine: Unity (C#)

> Imported into CLAUDE.md. Long-form flow is in `docs/ENGINE_FLOW.md`. Written quickly, clean up later.

## Version and setup
- **Unity version:** 6000.6.6f1 (from `ProjectSettings/ProjectVersion.txt`). Use the same editor version everywhere.
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
                         (AudioDirector, MusicDirector, AudioAccess), checked against data/golden/*.json; Analog
                         (stick and trigger shaping), CrashText (crash file text, log tail) and UiComposite (a UI
                         panel's texture over the camera's picture, blended as the screen does)
Assets/Scripts/Shell/    the front end on UI Toolkit (Game.Shell assembly): Shell (settings, strings, data folder),
                         FrontEnd (the screen flow), Screens/ (title, main menu, settings, pause, What now?, history,
                         credits, loading), SubtitleBar, ShellWorld with PlayWorld (the placeholder game) and
                         JuiceWorld (the juice demo), Narrator, ShellInput, ShellReports (crash files, F8 bug report),
                         UiCapture (the panel in screenshots), OutlineFace (outlined text that keeps its colour),
                         AccessAudit and SmokeDrive (`dev.py smoke --drive`)
Assets/Scripts/Game/     gameplay MonoBehaviours and ScriptableObjects; AudioEventPlayer, MusicPlayer play the audio decisions
Assets/Scripts/Dotwork/  Dotwork art at run time (Game.Dotwork assembly): DotworkPack (a pack's index), DotworkTile and
                         DotworkTerrainTile (tiles, autotiling by Core/Autotile), DotworkFont and DotworkLabel (bitmap text)
Assets/Scripts/Characters/  KitCharacter (Game.Characters assembly): a rigged glTF character's clips by name (#290)
Assets/Editor/           editor-only code (GameKitBuild.cs; GameKitScenes.cs builds the starter and shell scenes;
                         GameKitShaders.cs checks the shader recipes; GameKitDotwork.cs imports Dotwork packs, its
                         importer is Assets/Editor/Dotwork/; GameKitCharacters.cs adds the glTF importer package)
Assets/dotwork/          Dotwork's manifests (<pack>.assets.json) and what the importer makes of them (<pack>/)
Assets/Resources/GameKit/  the shell's panel theme (.tss) and the readable font (Atkinson Hyperlegible, OFL)
Assets/Shaders/Kit/      the kit's shader recipes as unlit shaders, Kit/<name> (generated)
Assets/Tests/EditMode/   EditMode tests (own assembly definition), incl. CharacterImportTests (the golden rigged character)
Assets/Tests/PlayMode/   PlayMode tests, incl. BootSmokeTests and ShellSmokeTests (what `dev.py smoke` runs; the second
                         also runs `--drive` scenarios), AudioPlayModeTests (AudioEventPlayer on real AudioSources:
                         `dev.py test --mode PlayMode --filter Audio`) and GameKitCaptureTests (a capture against the
                         GPU's own picture, outlined text in its own colour: `dev.py smoke --graphics --filter Capture`)
Assets/Art, Audio, Prefabs, Scenes/   content (see docs/ASSET_LOG.md); Scenes/Shell.unity is the kit's front end
data/                    i18n/ string tables (en, fr), input/presets.json (one-handed layouts), access/colours.json,
                         dialogue/sample.built.json, golden/ test vectors; a build copies the first four into
                         Assets/StreamingAssets/ (GameKitBuild.SyncData), which is generated: do not edit it
Packages/manifest.json   package list (edit through the Package Manager or with care)
ProjectSettings/         project config (text, edit with care)
```

## The shell (the kit's screens, #168)
- **This game keeps its own boot:** `Assets/Scenes/Graveyard.unity` (built by `SceneBuilder.Build`) stays the only
  scene in Build Settings, with the game's own IMGUI title and difficulty screen (`Hud.cs`). The shell code compiles
  alongside it (`Game.Shell`, referenced by the PlayMode tests) but `CreateShellScene` has not been run, so
  `Smoke_ShellDrive` reports Ignored under `dev.py smoke` and `smoke --drive` is not available. Run the line below
  only if the game is to adopt the kit's screens: it puts `Shell.unity` first and the game would open on its title.
- `python tools/dev.py exec GameKitScenes.CreateShellScene` makes the shell scene (`Shell.unity` under `Assets/Scenes/`:
  a camera and the FrontEnd component) and puts it first in Build Settings: the game opens on the title. Until then
  `smoke --drive` exits 2 and says so. Every screen is built in
  code on a UI Toolkit panel (1280x720 reference, scaled so the smaller side fits), so there is no UXML or USS to
  keep in step; the panel theme is Unity's default runtime theme (`Assets/Resources/GameKit/GameKitTheme.tss`).
- Settings rows come from `GameSettings.Fields(section)` (the schema): a new field needs its `setting.<section>.<field>`
  string in `data/i18n/en.json` (and `value.<field>.<choice>` for a choice) and shows up on its tab.
- The Display tab waits for Apply (#308): its rows stage through `DisplayStaging` (`Assets/Scripts/Core/`, held to
  `data/golden/shell.json`), Apply sets the changed fields through `Shell.SetValue` (mode before resolution) and saves,
  and a new window mode or size asks "Keep these display settings?", putting the old values back after 15 real seconds
  (a Stopwatch: paused games and `Time.timeScale` do not stop it). Back with a change waiting warns once. The other
  tabs apply at once. `smoke --drive display` runs it; `show:apply` and `show:confirm` photograph it.
- A game HUD's text size (#309): `Shell.I.HudFontSize(basePx)` (`HudScale.FontSize`, `display.ui_scale` times
  `access.text_scale`, `Assets/Scripts/Core/HudScale.cs`) and the `Shell.I.HudScaleChanged` event; `PlayWorld`'s hint
  line uses both. The shell's own menus size text by `access.text_scale` only (`UiTheme.Px`).
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
  stick moves the menus through the default `Horizontal`/`Vertical` axes, and the d-pad, the triggers and the analog
  stick read the axes `GameKitScenes.CreateShellScene` adds (`exec GameKitScenes.AddInputAxes` on its own: joystick
  axes 6, 7, 9 and 10, and 1 and 2 for the stick, the Windows layout **(verify on other platforms and with a physical
  pad)**). Triggers (`pad:l2`, `pad:r2`) are axes,
  pressed past half way, on both. Active Input Handling set to the Input System without the package installed falls
  back to UI Toolkit's events: the menus work, custom pad bindings are not read.
- Analog input for the game (#274, the rules of Bevy's `Intent`): `ShellInput.MoveVector()` (held move keys plus the
  stick, length at most 1), `ShellInput.Stick` (radial deadzone from `input.deadzone`, rescaled from 0, `invert_y`
  applied, up is +y), `LeftTrigger` / `RightTrigger` (0 to 1) and `HeldGameActions` / `IsGameHeld` (held game actions,
  the stick's `move_*` included). The Input System's own stick deadzone is bypassed (unprocessed values), so only the
  player's applies. None of it on the UI Toolkit fallback. Tests and drives hold a stick with `ShellInput.InjectAnalog`.
- Text over the game (HUD, hint, subtitles) gets `UiTheme.Outline(label)`: a black outline plus an un-outlined copy
  of the text drawn right on top (`OutlineFace`), because UI Toolkit centres `-unity-text-outline-width` on the
  glyph's edge and at body size even 1 px darkens the letters (2 px left almost none of `UiTheme.TEXT`, #283). Set the
  label's text and styles as usual: the copy follows them. A label outlined by hand, without the copy, is reported by
  the access sweep in its outline's colour.
- Line spacing adds space between the menus' lines and paragraphs: UI Toolkit has no line-height, so lines inside one
  wrapped paragraph keep the font's spacing **(verify: a later Unity may add it)**.
- Crash files and the bug report (#275): the first unhandled exception of a launch writes
  `crashes/crash_<time>.txt` in the data folder (version, error, stack, settings, log tail) and logs
  `CRASH_WRITTEN <path>`; Unity keeps running (a player started with `--smoke` quits with exit 1). F8 in the editor and
  development builds saves `bug_<time>/` (info, log tail, settings, a screenshot when there is a graphics device,
  always opaque) and logs `BUG_REPORT <dir>`.
- The juice demo (#275, main menu in the editor and development builds): hit the box for shake, hitstop, squash on a
  spring and a rate-limited flash, a follow camera with its deadzone drawn, a buffered jump with coyote time, a held
  guard, a line, a bark and a caption, analog movement. UI Toolkit elements only, so it needs no assets.
- Not here yet (Godot, LÖVE and web have it): telemetry rows.

## Dotwork art (#57)
- Dotwork (`tools/art/dotwork/`, `--engine none`) writes PNGs under `Assets/art/` and one manifest per pack,
  `Assets/dotwork/<pack>.assets.json` (spec: `tools/art/dotwork/ASSET_MANIFEST.md`). Dotwork reads the engine from
  `.game-kit.json` and uses `Assets` and `--engine none` by default (a `dotwork.config.json` that sets `assets_dir`
  wins: keep it `Assets`, since `assets` is another folder on a case-sensitive file system).
- `python tools/dev.py exec GameKitDotwork.ImportAll` (after every `pack` or `character`) imports every pack into
  `Assets/dotwork/<pack>/`: sprites sliced from the sheets (Point filter, no mipmaps, no compression, pixels per unit
  = the pack's first tileset's tile width, else 16; pivots and rects flipped to Unity's y up), an AnimationClip per clip
  (sprite keys at each frame's `duration`, `loopTime` from `loop`) with an AnimatorController (a state per clip, named
  as the clip) and a prefab per animated sprite, a prop prefab per sprite (BoxCollider2D per collision rect, shadow
  child), a DotworkTile per tileset cell (custom physics shapes for a TilemapCollider2D, animation frames, its
  `origin` as the sprite's pivot), a DotworkTerrainTile per terrain of every mode (blob47, sides4, corners4: paint it
  in the Tile Palette and it picks the tile by its neighbours and the cell's roll), a map prefab (Grid, a Tilemap per
  layer, the props), a DotworkFont per BMFont and the UI kit parts (9-slice margins as sprite borders). Everything is
  listed in `Assets/dotwork/<pack>/<pack>.asset` (DotworkPack: `pack.Animated("hero").Clip("walk", "s")`,
  `pack.Map("yard").prefab`, `pack.Font("dialogue")`, `pack.Background("hills").layers`). Running it again updates
  every asset in place (same GUIDs); commit the generated assets and their `.meta` files.
- Maps (asset manifest 1.1.0, #285): a `terrain` layer is resolved at import into the spec's own tiles (the key from
  the painted neighbours in the set's mode, the variant picked by `cell_roll(x, y, layer index)` among the tiles with
  that key by `probability`, the same pick as every other engine's importer; a cell with no tile for its key stays
  empty with one warning per layer), a `stamps` layer places every tile of each stamp, a `tiles` layer is placed as
  is (flip flags as the cell's transform), an unknown layer kind is skipped with one warning. A square map's row y is
  Unity cell y = -1 - y (the map's top-left corner at the origin, pixel (x, y) at `(x, -y) / ppu`). An isometric map
  uses Unity's Isometric Grid: Unity's diamonds run x up-right and y up-left and centre cell (0, 0) on x = 0, the spec
  (Godot's diamond-down layout) runs x down-right and y down-left with cell (0, 0) centred on (w/2, h/2), so the
  importer places map cell (x, y) at Unity cell (-1 - y, -1 - x) (`DotworkImporter.Cell(shape, x, y)`, inverse
  `MapCell`) and moves every layer's Tilemap half a diamond right, measured from the Grid, so a 16x8 set's cell (0, 0)
  is centred on (8, 4), (1, 0) on (16, 8), (0, 1) on (0, 8) map pixels, as the spec's `centres` say; a tile's sprite
  pivot is its origin, so its image lands at centre - origin (the raised iso block with `origin [8, 8]`). Isometric
  layers render with Mode Individual and Sort Order Top Right so the diamonds lower on the screen draw last **(verify:
  the headless tests prove the centres and the placed top-lefts, not the drawn order)**.
- The extra kinds are loaded and listed, the scene object that uses them is the game's: `background` (a sprite per
  layer with its size, velocity, repeat, wobble and scale; the texture wraps on the `repeat` axes), `particles` (the
  texture sprite and the emitter JSON as a `TextAsset`, `Assets/dotwork/<pack>/particles/<name>.json`), `transition`
  (the mask sprite and the transition kind), `normal_map` (a linear texture set as the target image's `_NormalMap`
  secondary texture through its TextureImporter; the test proves the slot on the target's sprites, that URP's 2D
  lights light it from there is not checked here, the kit's test projects are Built-in **(verify)**), `image` (a
  sprite). Only an unknown kind is skipped, with a warning.
- Fonts and UI kits are already drawn at their `scale` by Dotwork: draw them 1:1 (DotworkLabel does).
- `exec GameKitDotwork.Verify` (and `dev.py test`, `DotworkImportTests.EveryManifestInTheGameLoads`) fails on a missing
  file, a rect outside its image, a stale or broken import. `exec GameKitDotwork.ShowInStarterScene` puts the first
  map, a character walking, a prop and a label in the font in `Assets/Scenes/Main.unity`.
- Blend `add` uses a built-in particle shader (Built-in pipeline; URP needs its own particle material **(verify)**).
  The golden tests (`dev.py test --filter Dotwork`) read the three fixture maps back from their Tilemaps and compare
  every terrain cell, placed cell and centre with `data/golden/dotwork/expected.json`, both shapes, and load the
  rendered-character sheet pack (`data/golden/character/sprites/`) the same way.

## Rigged characters (glTF with clips, #290)
- **Package:** Unity has no glTF importer of its own. The kit uses glTFast (`com.unity.cloud.gltfast`, Unity's own,
  Apache 2.0) pinned at **6.20.0** (the newest release older than two weeks on 2026-11-11; it pulls in Burst,
  Collections and Mathematics). It is not installed by the scaffold, because adopt mode never rewrites your
  `Packages/manifest.json` and a 2D game does not need it: `python tools/dev.py exec GameKitCharacters.AddGltfast`
  adds the line (or Package Manager > + > Add package by name), the next `dev.py` command downloads and compiles
  it. Without it `.glb` files stay plain files, `KitCharacter.CanLoadGltf` is false and the character tests are
  ignored with that command as the reason. The alternative is FBX (Unity imports it natively), see Humanoid below.
- **Where the file goes:** `Assets/Models/<name>.glb` (Bozzetto's `rig make`, Tripo or Blender output). glTFast's
  importer makes the model (the main asset, with an Animator that has no controller and no avatar), its meshes,
  materials and one AnimationClip per glTF animation, named as in the file (`idle`, `walk`). Bone names stay as
  in the file, colon included (`mixamorig:Hips`; Godot is the engine that renames them).
- **Clips:** Mecanim clips, Generic (transform curves), with Loop Time already on for every clip (glTFast sets
  it). Play them with an AnimatorController (a state per clip) or with no controller at all through
  `KitCharacter.Attach(instance, clips).Play("walk")` (a PlayableGraph on the model's Animator).
  `Play(name, loop: false)` holds the last frame instead. A file loaded at run time (`KitCharacter.Load(path)`,
  mods or generated characters) gets legacy clips on an Animation component instead, because glTFast cannot make
  Mecanim clips in a player build; KitCharacter hides the difference.
- **Root motion off:** the kit's clips walk in place. `Attach` sets `Animator.applyRootMotion = false`; a Generic
  clip with no avatar has no root node to move anyway, and legacy clips have no root motion. A Humanoid FBX clip
  carries root curves: tick Root Transform Rotation and Position (Y, XZ) "Bake Into Pose" in its clip settings
  if it must not move the object.
- **Scale and facing:** glTF is metres, +Y up, front +Z. Unity shows the golden character 1.80 units tall (1 unit =
  1 m, no scale factor), feet at the origin, facing +Z (its `transform.forward`); glTFast flips X for Unity's
  left-handed space, so its left side is at -X and the model is not mirrored. A camera on Unity's default spot
  (z = -10, looking at +Z) sees its back: turn the character 180 degrees on Y to face the camera.
- **Humanoid vs Generic (what happened):** use **Generic** for a glTF character.
  1. glTFast makes no avatar: the imported Animator's `avatar` is null and every clip has `humanMotion` false.
  2. `AvatarBuilder.BuildHumanAvatar(root, description)` with a HumanDescription built from the Mixamo names
     (each `mixamorig:X` to Unity's bone: Spine1 Chest, Spine2 UpperChest, Arm UpperArm, ForeArm LowerArm, UpLeg
     UpperLeg, Leg LowerLeg, ToeBase Toes, the rest by the same name; skeleton = every transform's rest pose)
     makes a valid Humanoid avatar (all 22 bones mapped, from the A-pose). But glTFast's Generic clips move
     nothing on a Humanoid Animator (0.0 degrees on `mixamorig:LeftUpLeg`): a Humanoid Animator only plays
     humanoid (muscle) clips, and nothing turns a glTF clip into one at import.
  3. The same character exported from Blender 5.2.3 as FBX (glTF import, FBX export with every action baked)
     imports Generic by default. Set Rig > Animation Type to Humanoid (Avatar Definition: Create From This
     Model) and Unity maps it on its own: a valid Humanoid avatar with 20 bones mapped (every bone but
     `LeftShoulder`/`RightShoulder`, which the automatic mapping left out), clips `KitCharacter|idle` and
     `KitCharacter|walk` as humanoid clips with Loop Time off (tick it per clip). Its walk moved the thigh by
     37 degrees from the first pose where the Generic clip moves it 28: muscle retargeting is not 1:1.
  4. That humanoid FBX walk also played on the glTF model through the avatar built in step 2 (37.7 degrees). So
     Mixamo-style humanoid clips (FBX downloads) can drive a glTF character, through a script-built avatar.
  An FBX model's Animator culls by default (Culling Mode: Cull Update Transforms): off screen, and in every
  headless test, its bones do not move until it is set to Always Animate. glTFast's Animator always animates.
- **The helper** (`Assets/Scripts/Characters/KitCharacter.cs`, namespace `<game>.Characters`):
  `await KitCharacter.Load(path, parent)` (run time, needs glTFast), `KitCharacter.Attach(instance, clips)` (an
  imported model), then `Play(clip, loop = true, restart = false)`, `Seek(seconds)` (jump and pose now, also in
  edit mode), `ClipNames`, `Playing`, `ClipTime`, `Bone("mixamorig:LeftUpLeg")`. `Play` of the clip already
  playing with the same `loop` changes nothing (it keeps its time, a held clip keeps holding), so a game may call it
  every frame; `restart: true` or another loop setting starts it from 0: the same rule in all five engines'
  character helpers (#296, `KitCharacterPlayTests`, which needs no glTFast). An unknown clip name throws with the clip list. It
  plays one clip at a time with no blending: crossfades and layers belong in the game's AnimatorController.
- **Tested** (2026-11-11, Unity 6000.6.6f1, glTFast 6.20.0, Windows, a fresh `-createProject` project adopted with
  the kit, Built-in render pipeline): `dev.py test --filter Character` passed 6 of 6 (CharacterImportTests: bones
  and clips from `data/golden/character/expected.json`, 1.80 m tall on the origin facing +Z, walk swings
  `mixamorig:LeftUpLeg` within 0.5 to 1.25 of the expected 56 degrees, loops, stays in place, idle is not walk,
  for the editor import with `Attach` and for `Load`); `dev.py test --mode PlayMode --filter Character` passed 1
  (the walk in real frames: 55.9 degrees over 1.5 lengths). The whole runs there: before `AddGltfast`, `test`
  179 passed and the six skipped with the command as the reason; after it, `check` ok, `test` 186 passed (1
  skipped: no Dotwork packs), `test --mode PlayMode` 14 passed (2 capture tests skipped: no graphics device) once
  the scenes were made, `smoke` passed. With the pose step taken out of KitCharacter the swing
  tests fail (0.0 degrees), and with looping taken out the loop checks fail. The Humanoid findings above come
  from a one-off editor script run the same day, not from a kept test.
- **Not tested:** a player build with a run-time `Load` (glTFast's shaders must be in the build, see its docs
  **(verify)**), URP and HDRP materials **(verify)**, a Humanoid model's own clips through `Attach` in a game
  **(verify)**, macOS and Linux **(verify)**.

## Conventions
- C# standard style: `PascalCase` types and methods, `_camelCase` private fields, `[SerializeField] private` over public fields.
- Logic in plain C# classes (testable), MonoBehaviours stay thin glue.
- Tunables in `ScriptableObject` assets or config files, not literals.
- Logging: a small `Log` wrapper with channels, no stray `Debug.Log` in committed code.
- Use `Time.deltaTime` in `Update`, `Time.fixedDeltaTime` in `FixedUpdate`. Physics in `FixedUpdate`.
- Assembly definitions (`.asmdef`) per folder group for fast compile and test isolation.
- 3D models from `tools/bozzetto/bozzetto.py` land in `Assets/Models/` as `.glb`: Unity needs the glTFast package
  for them (`python tools/dev.py exec GameKitCharacters.AddGltfast`), or export FBX from Blender instead.
  A rigged character from `bozzetto.py rig make` has Mixamo bone names: import it Generic and play its own clips;
  Humanoid needs humanoid clips, see "Rigged characters" above for what was tried.
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
