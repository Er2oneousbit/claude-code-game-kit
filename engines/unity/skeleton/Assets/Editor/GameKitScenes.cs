// ---------------------------------------------------------------------------
// GameKitScenes.cs
// Purpose : Create scenes from code, headless: the starter scene that the boot smoke test needs, the shell
//           scene (the kit's title, settings, pause and credits screens on the FrontEnd component), and the
//           helper a game's own scene builder uses to register scenes in Build Settings.
// Usage   : python tools/dev.py exec GameKitScenes.CreateStarterScene
//           python tools/dev.py exec GameKitScenes.CreateShellScene     (first in Build Settings: the game opens on it;
//                                                               also runs AddInputAxes, the shell's pad axes)
//           (or the menu Tools > Game Kit > Create Starter Scene / Create Shell Scene)
// Notes   : Scenes and prefabs are YAML that is fragile to hand-edit (docs/ENGINE.md). Building them in an
//           editor script keeps every structural change in reviewable C#, and lets Claude make a scene
//           without the editor UI. Pattern for a game: write `public static void Build()` in an Editor
//           folder that creates the scene, wires assets with AssetDatabase, saves, and calls
//           AddToBuildSettings; run it with `dev.py exec YourBuilder.Build`. Idempotent: run it again any time.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a failed SaveScene throws (it was ignored)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): CreateShellScene (#168)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): AddInputAxes, the shell's d-pad and trigger axes (#266)
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
    public const string ShellScenePath = {{GAME_SLUG}}.Shell.FrontEnd.SCENE_PATH;

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
            front.AddComponent<{{GAME_SLUG}}.Shell.Shell>();
            front.AddComponent<{{GAME_SLUG}}.Shell.FrontEnd>();
            Directory.CreateDirectory(Path.GetDirectoryName(ShellScenePath));
            if (!EditorSceneManager.SaveScene(scene, ShellScenePath))
            {
                throw new IOException($"could not save {ShellScenePath} (read-only folder, or a file in the way?)");
            }
            Debug.Log($"[INFO][scenes] created {ShellScenePath}");
        }
        AddToBuildSettings(ShellScenePath, first: true);
        AddInputAxes();
    }

    // The Input Manager axes the shell reads for the d-pad and the triggers (#266), as joystick axis numbers of the
    // Windows XInput layout (verify on other platforms): name, 1-based axis, dead zone
    private static readonly (string name, int axis, float dead)[] INPUT_AXES =
    {
        ({{GAME_SLUG}}.Shell.ShellInput.AXIS_DPAD_X, 6, 0.19f),
        ({{GAME_SLUG}}.Shell.ShellInput.AXIS_DPAD_Y, 7, 0.19f),
        ({{GAME_SLUG}}.Shell.ShellInput.AXIS_L2, 9, 0.001f),
        ({{GAME_SLUG}}.Shell.ShellInput.AXIS_R2, 10, 0.001f),
    };

    /// <summary>Adds the shell's gamepad axes (d-pad, triggers) to Project Settings > Input Manager, once. Harmless
    /// when the project uses only the Input System package (the shell reads the pad through it then).</summary>
    [MenuItem("Tools/Game Kit/Add Input Axes")]
    public static void AddInputAxes()
    {
        Object[] assets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/InputManager.asset");
        if (assets == null || assets.Length == 0)
        {
            throw new IOException("ProjectSettings/InputManager.asset not found");
        }
        var so = new SerializedObject(assets[0]);
        SerializedProperty axes = so.FindProperty("m_Axes");
        int added = 0;
        foreach ((string name, int axis, float dead) in INPUT_AXES)
        {
            bool present = false;
            for (int i = 0; i < axes.arraySize && !present; i++)
            {
                present = axes.GetArrayElementAtIndex(i).FindPropertyRelative("m_Name").stringValue == name;
            }
            if (present)
            {
                continue;
            }
            axes.arraySize++;
            SerializedProperty a = axes.GetArrayElementAtIndex(axes.arraySize - 1);
            a.FindPropertyRelative("m_Name").stringValue = name;
            a.FindPropertyRelative("descriptiveName").stringValue = "Game Kit shell (ShellInput)";
            a.FindPropertyRelative("descriptiveNegativeName").stringValue = "";
            a.FindPropertyRelative("negativeButton").stringValue = "";
            a.FindPropertyRelative("positiveButton").stringValue = "";
            a.FindPropertyRelative("altNegativeButton").stringValue = "";
            a.FindPropertyRelative("altPositiveButton").stringValue = "";
            a.FindPropertyRelative("gravity").floatValue = 0f;
            a.FindPropertyRelative("dead").floatValue = dead;
            a.FindPropertyRelative("sensitivity").floatValue = 1f;
            a.FindPropertyRelative("snap").boolValue = false;
            a.FindPropertyRelative("invert").boolValue = false;
            a.FindPropertyRelative("type").intValue = 2;           // joystick axis
            a.FindPropertyRelative("axis").intValue = axis - 1;    // stored 0-based
            a.FindPropertyRelative("joyNum").intValue = 0;         // every joystick
            added++;
        }
        so.ApplyModifiedPropertiesWithoutUndo();
        AssetDatabase.SaveAssets();
        Debug.Log($"[INFO][scenes] input axes: {added} added, {INPUT_AXES.Length - added} already there");
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
