// ---------------------------------------------------------------------------
// GameKitScenes.cs
// Purpose : Create scenes from code, headless: the starter scene that the boot smoke test needs, and
//           the helper a game's own scene builder uses to register scenes in Build Settings.
// Usage   : python tools/dev.py exec GameKitScenes.CreateStarterScene
//           (or the menu Tools > Game Kit > Create Starter Scene)
// Notes   : Scenes and prefabs are YAML that is fragile to hand-edit (docs/ENGINE.md). Building them in an
//           editor script keeps every structural change in reviewable C#, and lets Claude make a scene
//           without the editor UI. Pattern for a game: write `public static void Build()` in an Editor
//           folder that creates the scene, wires assets with AssetDatabase, saves, and calls
//           AddToBuildSettings; run it with `dev.py exec YourBuilder.Build`. Idempotent: run it again any time.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class GameKitScenes
{
    public const string StarterScenePath = "Assets/Scenes/Main.unity";

    [MenuItem("Tools/Game Kit/Create Starter Scene")]
    public static void CreateStarterScene()
    {
        if (!File.Exists(StarterScenePath))
        {
            // A camera and a light, nothing else: the smallest scene the boot smoke test can load
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            Directory.CreateDirectory(Path.GetDirectoryName(StarterScenePath));
            EditorSceneManager.SaveScene(scene, StarterScenePath);
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
