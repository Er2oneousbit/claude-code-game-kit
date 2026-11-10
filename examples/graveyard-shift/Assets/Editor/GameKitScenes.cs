// ---------------------------------------------------------------------------
// GameKitScenes.cs
// Purpose : Create scenes from code, headless: the starter scene that the boot smoke test needs, the shell
//           scene (the kit's title, settings, pause and credits screens on the FrontEnd component), and the
//           helper a game's own scene builder uses to register scenes in Build Settings.
// Usage   : python tools/dev.py exec GameKitScenes.CreateStarterScene
//           python tools/dev.py exec GameKitScenes.CreateShellScene     (first in Build Settings: the game opens on it)
//           (or the menu Tools > Game Kit > Create Starter Scene / Create Shell Scene)
// Notes   : Scenes and prefabs are YAML that is fragile to hand-edit (docs/ENGINE.md). Building them in an
//           editor script keeps every structural change in reviewable C#, and lets Claude make a scene
//           without the editor UI. Pattern for a game: write `public static void Build()` in an Editor
//           folder that creates the scene, wires assets with AssetDatabase, saves, and calls
//           AddToBuildSettings; run it with `dev.py exec YourBuilder.Build`. Idempotent: run it again any time.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a failed SaveScene throws (it was ignored)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): CreateShellScene (#168)
// ---------------------------------------------------------------------------
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class GameKitScenes
{
    public const string StarterScenePath = "Assets/Scenes/Main.unity";
    public const string ShellScenePath = graveyard_shift.Shell.FrontEnd.SCENE_PATH;

    [MenuItem("Tools/Game Kit/Create Shell Scene")]
    public static void CreateShellScene()
    {
        if (!File.Exists(ShellScenePath))
        {
            // A camera (the game's picture) and the front end: the shell builds every screen in code
            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var cam = new GameObject("Main Camera") { tag = "MainCamera" };
            var camera = cam.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.10f, 0.11f, 0.16f);
            cam.AddComponent<AudioListener>();
            var front = new GameObject("FrontEnd");
            front.AddComponent<graveyard_shift.Shell.Shell>();
            front.AddComponent<graveyard_shift.Shell.FrontEnd>();
            Directory.CreateDirectory(Path.GetDirectoryName(ShellScenePath));
            if (!EditorSceneManager.SaveScene(scene, ShellScenePath))
            {
                throw new IOException($"could not save {ShellScenePath} (read-only folder, or a file in the way?)");
            }
            Debug.Log($"[INFO][scenes] created {ShellScenePath}");
        }
        AddToBuildSettings(ShellScenePath, first: true);
    }

    [MenuItem("Tools/Game Kit/Create Starter Scene")]
    public static void CreateStarterScene()
    {
        if (!File.Exists(StarterScenePath))
        {
            // A camera and a light, nothing else: the smallest scene the boot smoke test can load
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            Directory.CreateDirectory(Path.GetDirectoryName(StarterScenePath));
            if (!EditorSceneManager.SaveScene(scene, StarterScenePath))
            {
                // Throwing makes `dev.py exec` fail (exit 1) instead of putting a missing scene in Build Settings
                throw new IOException($"could not save {StarterScenePath} (read-only folder, or a file in the way?)");
            }
            Debug.Log($"[INFO][scenes] created {StarterScenePath}");
        }
        AddToBuildSettings(StarterScenePath, first: true);
    }

    // Puts a scene in Build Settings (once). first = make it the scene the player starts in.
    public static void AddToBuildSettings(string path, bool first = false)
    {
        var scenes = EditorBuildSettings.scenes.Where(s => s.path != path).ToList();
        var entry = new EditorBuildSettingsScene(path, true);
        if (first) scenes.Insert(0, entry);
        else scenes.Add(entry);
        EditorBuildSettings.scenes = scenes.ToArray();
        AssetDatabase.SaveAssets();
        Debug.Log($"[INFO][scenes] build settings: {string.Join(", ", EditorBuildSettings.scenes.Select(s => s.path))}");
    }
}
