// ---------------------------------------------------------------------------
// SceneBuilder.cs
// Purpose : Builds everything the editor would otherwise need clicks for: reimports the Kenney models
//           with the import rules, fills Assets/Config/SO_GraveyardSetup.asset (models by name, sounds,
//           tunables), writes the scene (one Bootstrap object) and puts it first in Build Settings, and
//           sets the player's version (SOP-06: one source of truth, read in game as Application.version).
// Usage   : python tools/dev.py exec SceneBuilder.Build      (or Tools > Graveyard Shift > Build Scene)
// Notes   : Idempotent: run it after adding a model or changing the version. Tunables already edited in
//           the Inspector are kept (only a new asset gets the defaults; SceneBuilder.ResetTuning copies them over). The level itself is built at
//           runtime from Core/Level.cs, so the scene file stays tiny.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.IO;
using System.Linq;
using graveyard_shift.Game;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SceneBuilder
{
    public const string Version = "0.2.0";
    private const string ScenePath = "Assets/Scenes/Graveyard.unity";
    private const string SetupPath = "Assets/Config/SO_GraveyardSetup.asset";
    private static readonly string[] ArtFolders = { "Assets/Art/Graveyard", "Assets/Art/Nature" };   // Kenney kits, every .fbx registered by name
    private const string AudioFolder = "Assets/Audio";

    [MenuItem("Tools/Graveyard Shift/Build Scene")]
    public static void Build()
    {
        // 1. Models with the import rules from GraveyardImport.cs
        string[] models = ArtFolders.SelectMany(f => Directory.GetFiles(f, "*.fbx")).Select(p => p.Replace('\\', '/')).ToArray();
        foreach (var m in models) AssetDatabase.ImportAsset(m, ImportAssetOptions.ForceUpdate);

        // 2. The setup asset
        Directory.CreateDirectory(Path.GetDirectoryName(SetupPath));
        var setup = AssetDatabase.LoadAssetAtPath<GraveyardSetup>(SetupPath);
        if (setup == null)
        {
            setup = ScriptableObject.CreateInstance<GraveyardSetup>();
            AssetDatabase.CreateAsset(setup, SetupPath);
        }
        setup.models = models.Select(p => new GraveyardSetup.Model
        {
            name = Path.GetFileNameWithoutExtension(p),
            prefab = AssetDatabase.LoadAssetAtPath<GameObject>(p),
        }).ToList();
        setup.soulCollected = Clip("soul_collected");
        setup.gateOpens = Clip("gate_opens");
        setup.ghostAlert = Clip("ghost_alert");
        setup.caught = Clip("caught");
        setup.lanternToggle = Clip("lantern_toggle");
        setup.ambience = Clip("night_ambience");
        setup.soulWhisper = Clip("soul_whisper");
        setup.ghostPresence = Clip("ghost_presence");
        setup.footsteps = new[] { Clip("footstep_1"), Clip("footstep_2"), Clip("footstep_3") }.Where(c => c != null).ToArray();
        setup.lanternFlame = Clip("lantern_flame");
        setup.ghostNotice = Clips("ghost_notice");
        setup.ghostCaught = Clips("ghost_caught");
        setup.ghostSearch = Clips("ghost_search");
        setup.ghostGiveUp = Clips("ghost_giveup");
        setup.keeperSoul = Clips("keeper_soul");
        setup.keeperGate = Clips("keeper_gate");
        setup.keeperLowTime = Clips("keeper_lowtime");
        setup.keeperCaught = Clips("keeper_caught");
        setup.narratorIntro = Clips("narrator_intro");
        setup.narratorEscape = Clips("narrator_escape");
        setup.narratorDawn = Clips("narrator_dawn");
        setup.dawnChorus = Clip("dawn_chorus");
        // the Suno end music (win_music_a/b, loss_sting_a/b); missing ones are left out
        setup.winTracks = new[] { Clip("win_music_a", optional: true), Clip("win_music_b", optional: true) }.Where(c => c != null).ToArray();
        setup.lossStings = new[] { Clip("loss_sting_a", optional: true), Clip("loss_sting_b", optional: true) }.Where(c => c != null).ToArray();
        // the two Suno takes (docs/BRIEFS.md), reimported first so GraveyardImport's streaming rule applies;
        // missing ones are left out, none means no music
        foreach (var p in Directory.GetFiles(AudioFolder, "*_music_*").Where(p => !p.EndsWith(".meta")))
            AssetDatabase.ImportAsset(p.Replace('\\', '/'), ImportAssetOptions.ForceUpdate);
        setup.musicTracks = new[] { Clip("night_music_a", optional: true), Clip("night_music_b", optional: true) }
            .Where(c => c != null).ToArray();
        EditorUtility.SetDirty(setup);
        AssetDatabase.SaveAssets();

        // 3. The scene: one Bootstrap object that builds the rest at runtime
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        // NewScene(Single) unloads unused assets: load the setup again, the old reference is dead now
        setup = AssetDatabase.LoadAssetAtPath<GraveyardSetup>(SetupPath);
        var boot = new GameObject("Bootstrap");
        var game = boot.AddComponent<GraveyardGame>();
        var so = new SerializedObject(game);
        so.FindProperty("setup").objectReferenceValue = setup;
        so.ApplyModifiedPropertiesWithoutUndo();
        if (game.GetType().GetField("setup", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
                ?.GetValue(game) == null)
        {
            Debug.LogError("[ERROR][build] the Bootstrap lost its SO_GraveyardSetup reference");
            EditorApplication.Exit(1);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
        EditorSceneManager.SaveScene(scene, ScenePath);
        GameKitScenes.AddToBuildSettings(ScenePath, first: true);

        // 4. The version (SOP-06)
        PlayerSettings.bundleVersion = Version;
        PlayerSettings.productName = "Graveyard Shift";
        PlayerSettings.companyName = "GameKitExamples";
        AssetDatabase.SaveAssets();
        Debug.Log($"[INFO][build] scene {ScenePath}, {models.Length} models, version {Version}");
    }

    // Copies the C# defaults (Core/GameTuning.cs) into the setup asset. Field defaults only seed a NEW asset;
    // after that the asset's values win, so changing a default in code changes nothing until this runs.
    [MenuItem("Tools/Graveyard Shift/Reset Tuning To Code Defaults")]
    public static void ResetTuning()
    {
        var setup = AssetDatabase.LoadAssetAtPath<GraveyardSetup>(SetupPath);
        if (setup == null)
        {
            Debug.LogError($"[ERROR][build] {SetupPath} missing: run SceneBuilder.Build first");
            EditorApplication.Exit(1);
            return;
        }
        setup.tuning = new graveyard_shift.Core.GameTuning();
        EditorUtility.SetDirty(setup);
        AssetDatabase.SaveAssets();
        Debug.Log($"[INFO][build] tuning in {SetupPath} reset to the code defaults");
    }

    // A numbered set of takes: <prefix>_1, <prefix>_2 ... until one is missing (fish_tts.py names sets this way)
    private static AudioClip[] Clips(string prefix)
    {
        var list = new System.Collections.Generic.List<AudioClip>();
        for (int i = 1; ; i++)
        {
            var clip = Clip($"{prefix}_{i}", optional: true);
            if (clip == null) break;
            list.Add(clip);
        }
        if (list.Count == 0) Debug.LogWarning($"[WARN][build] no {AudioFolder}/{prefix}_1.* found");
        return list.ToArray();
    }

    // A sound by name, whatever its format (wav from the generators, mp3 from a web tool, ogg)
    private static AudioClip Clip(string name, bool optional = false)
    {
        foreach (var ext in new[] { "wav", "ogg", "mp3" })
        {
            var clip = AssetDatabase.LoadAssetAtPath<AudioClip>($"{AudioFolder}/{name}.{ext}");
            if (clip != null) return clip;
        }
        if (optional) Debug.Log($"[INFO][build] no {AudioFolder}/{name}.* yet, that layer stays silent");
        else Debug.LogWarning($"[WARN][build] missing sound {AudioFolder}/{name}.wav (or .ogg, .mp3)");
        return null;
    }
}
