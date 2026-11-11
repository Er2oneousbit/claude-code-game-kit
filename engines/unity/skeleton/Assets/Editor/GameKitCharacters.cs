// ---------------------------------------------------------------------------
// GameKitCharacters.cs
// Purpose : Adds the glTF importer the kit's rigged characters need (#290): glTFast, com.unity.cloud.gltfast, at
//           the version the kit tested, to Packages/manifest.json. Unity has no built-in glTF importer.
// Usage   : python tools/dev.py exec GameKitCharacters.AddGltfast        then any dev.py command resolves it
//           (or the menu Tools > Game Kit > Characters > Add glTFast, or Package Manager > + > Add package by name)
// Notes   : Edits the manifest's text (one line after "dependencies": {) and asks the Package Manager to resolve;
//           a batchmode run quits before that finishes, so the next editor start downloads and compiles it. A
//           manifest that already names the package is left alone (its version is logged). The version is pinned:
//           change PIN only after `dev.py test` passes with the new one (CharacterImportTests).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.PackageManager;
using UnityEngine;

public static class GameKitCharacters
{
    // ---- Tunables ------------------------------------------------------------
    public const string PACKAGE = "com.unity.cloud.gltfast";
    public const string PIN = "6.20.0";               // tested on Unity 6000.6.6f1 (2026-11-11)
    private const string MANIFEST = "Packages/manifest.json";

    [MenuItem("Tools/Game Kit/Characters/Add glTFast")]
    public static void AddGltfast()
    {
        if (!File.Exists(MANIFEST))
        {
            throw new FileNotFoundException($"no {MANIFEST}: is this a Unity project folder?");
        }
        string text = File.ReadAllText(MANIFEST);
        Match have = Regex.Match(text, "\"" + Regex.Escape(PACKAGE) + "\"\\s*:\\s*\"([^\"]*)\"");
        if (have.Success)
        {
            Debug.Log($"[INFO][characters] {PACKAGE} is already in {MANIFEST} ({have.Groups[1].Value}); nothing to do");
            return;
        }
        Match deps = Regex.Match(text, "\"dependencies\"\\s*:\\s*\\{(\\r?\\n)?");
        if (!deps.Success)
        {
            throw new InvalidDataException($"{MANIFEST} has no \"dependencies\" object: add \"{PACKAGE}\": \"{PIN}\" to it by hand");
        }
        string newline = deps.Groups[1].Success ? deps.Groups[1].Value : "\n";
        bool empty = text.Substring(deps.Index + deps.Length).TrimStart().StartsWith("}");
        string line = $"    \"{PACKAGE}\": \"{PIN}\"{(empty ? "" : ",")}{newline}";
        if (!deps.Groups[1].Success)
        {
            line = newline + line;                    // "dependencies": { on one line with its first entry
        }
        File.WriteAllText(MANIFEST, text.Insert(deps.Index + deps.Length, line));
        Debug.Log($"[INFO][characters] added {PACKAGE} {PIN} to {MANIFEST}; the next editor start resolves and compiles it");
        Client.Resolve();
    }
}
