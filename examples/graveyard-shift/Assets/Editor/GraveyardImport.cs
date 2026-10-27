// ---------------------------------------------------------------------------
// GraveyardImport.cs
// Purpose : Import rules for the Kenney models (Graveyard Kit and Nature Kit): characters get Legacy animation (played by name in
//           code, no Animator Controller asset), props import without colliders (the game adds a box per
//           prop) and without animation. Music (night_music_*, win_music_*) streams from disk instead of being
//           decompressed into memory (a 77 s stereo track would take about 30 MB of RAM).
// Usage   : automatic on import; SceneBuilder.Build reimports the models so the rules apply.
// Notes   : An AssetPostprocessor keeps import settings in reviewable C# instead of .meta edits.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEditor;
using UnityEngine;

public sealed class GraveyardImport : AssetPostprocessor
{
    private static readonly string[] ArtFolders = { "Assets/Art/Graveyard/", "Assets/Art/Nature/" };

    private void OnPreprocessModel()
    {
        if (!System.Array.Exists(ArtFolders, f => assetPath.StartsWith(f))) return;
        var importer = (ModelImporter)assetImporter;
        importer.addCollider = false;
        bool character = System.IO.Path.GetFileName(assetPath).StartsWith("character-");
        importer.importAnimation = character;
        importer.animationType = character ? ModelImporterAnimationType.Legacy : ModelImporterAnimationType.None;
    }

    private void OnPreprocessAudio()
    {
        if (!assetPath.StartsWith("Assets/Audio/night_music_") && !assetPath.StartsWith("Assets/Audio/win_music_")) return;
        var importer = (AudioImporter)assetImporter;
        var settings = importer.defaultSampleSettings;
        settings.loadType = AudioClipLoadType.Streaming;
        importer.defaultSampleSettings = settings;
    }
}
