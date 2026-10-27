// ---------------------------------------------------------------------------
// GameKitBuild.cs
// Purpose : Headless build entry point called by `python tools/dev.py build`.
// Usage   : Unity -batchmode -quit -projectPath . -executeMethod GameKitBuild.Build -buildTarget <t> -outputPath <p>
// Notes   : Reads -outputPath from the command line. Uses scenes enabled in Build Settings.
//           Exits non-zero on failure so CI and dev.py notice. Named GameKitBuild (not BuildScript)
//           so it cannot collide with a build class an adopted project already has.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class GameKitBuild
{
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
