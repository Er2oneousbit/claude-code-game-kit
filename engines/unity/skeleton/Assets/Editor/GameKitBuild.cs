// ---------------------------------------------------------------------------
// GameKitBuild.cs
// Purpose : Headless build entry point called by `python tools/dev.py build`.
// Usage   : Unity -batchmode -quit -projectPath . -executeMethod GameKitBuild.Build -buildTarget <t> -outputPath <p>
// Notes   : Reads -outputPath from the command line. Uses scenes enabled in Build Settings.
//           Exits non-zero on failure so CI and dev.py notice. Named GameKitBuild (not BuildScript)
//           so it cannot collide with a build class an adopted project already has. Before building it copies
//           the shell's data files (data/i18n, data/input, data/access, data/dialogue, CREDITS.md) into
//           Assets/StreamingAssets/ so a player finds them (ShellFiles reads that copy first).
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): SyncData copies the shell's data files into
//           StreamingAssets before a build (#168)
// ---------------------------------------------------------------------------
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class GameKitBuild
{
    // Data the shell reads at run time, relative to the project root; copied under Assets/StreamingAssets
    public static readonly string[] DATA_DIRS = { "data/i18n", "data/input", "data/access", "data/dialogue" };
    public static readonly string[] DATA_FILES = { "CREDITS.md" };

    public static void Build()
    {
        string output = GetArg("-outputPath") ?? "Build/game";
        string[] scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
        if (scenes.Length == 0)
        {
            Debug.LogError("[ERROR][build] no enabled scenes in Build Settings");
            EditorApplication.Exit(2);
            return;
        }
        SyncData();

        var options = new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = output,
            target = EditorUserBuildSettings.activeBuildTarget,
            options = BuildOptions.None,
        };

        BuildReport report = BuildPipeline.BuildPlayer(options);
        bool ok = report.summary.result == BuildResult.Succeeded;
        Debug.Log($"[build] result={report.summary.result} size={report.summary.totalSize} output={output}");
        EditorApplication.Exit(ok ? 0 : 1);
    }

    /// <summary>Copies the shell's data files into Assets/StreamingAssets (same relative paths), replacing old copies.</summary>
    [MenuItem("Tools/Game Kit/Copy Data To StreamingAssets")]
    public static void SyncData()
    {
        string root = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        int copied = 0;
        foreach (string dir in DATA_DIRS)
        {
            string src = Path.Combine(root, dir);
            if (!Directory.Exists(src)) continue;
            string dst = Path.Combine(Application.streamingAssetsPath, dir);
            Directory.CreateDirectory(dst);
            foreach (string file in Directory.GetFiles(src))
            {
                if (file.EndsWith(".meta", StringComparison.Ordinal)) continue;
                File.Copy(file, Path.Combine(dst, Path.GetFileName(file)), true);
                copied++;
            }
        }
        foreach (string name in DATA_FILES)
        {
            string src = Path.Combine(root, name);
            if (!File.Exists(src)) continue;
            Directory.CreateDirectory(Application.streamingAssetsPath);
            File.Copy(src, Path.Combine(Application.streamingAssetsPath, name), true);
            copied++;
        }
        AssetDatabase.Refresh();
        Debug.Log($"[INFO][build] {copied} data file(s) copied to StreamingAssets");
    }

    // Reads "-name value" from the command line, or null if absent.
    private static string GetArg(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name) return args[i + 1];
        }
        return null;
    }
}
