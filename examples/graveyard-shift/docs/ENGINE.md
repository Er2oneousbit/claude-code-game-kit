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
Assets/Scripts/Core/     engine-agnostic logic (no UnityEngine types where possible), unit tested
Assets/Scripts/Game/     gameplay MonoBehaviours and ScriptableObjects
Assets/Editor/           editor-only code (GameKitBuild.cs lives here)
Assets/Tests/EditMode/   EditMode tests (own assembly definition)
Assets/Tests/PlayMode/   PlayMode tests, incl. BootSmokeTests (what `dev.py smoke` runs)
Assets/Art, Audio, Prefabs, Scenes/   content (see docs/ASSET_LOG.md)
Packages/manifest.json   package list (edit through the Package Manager or with care)
ProjectSettings/         project config (text, edit with care)
```

## Conventions
- C# standard style: `PascalCase` types and methods, `_camelCase` private fields, `[SerializeField] private` over public fields.
- Logic in plain C# classes (testable), MonoBehaviours stay thin glue.
- Tunables in `ScriptableObject` assets or config files, not literals.
- Logging: a small `Log` wrapper with channels, no stray `Debug.Log` in committed code.
- Use `Time.deltaTime` in `Update`, `Time.fixedDeltaTime` in `FixedUpdate`. Physics in `FixedUpdate`.
- Assembly definitions (`.asmdef`) per folder group for fast compile and test isolation.

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
`Library/`, `Temp/`, `Logs/`, `UserSettings/`, `*.csproj`, `*.sln`, `*.slnx` (Unity 6.6 writes the new solution format), built players in `Build/`.
