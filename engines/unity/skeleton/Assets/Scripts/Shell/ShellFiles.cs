// ---------------------------------------------------------------------------
// ShellFiles.cs
// Purpose : Where the shell's data files are: the kit ships them at the project root (data/i18n/*.json,
//           data/input/presets.json, data/access/colours.json, data/dialogue/*.built.json, CREDITS.md), which the
//           editor and a PlayMode test can read; a built player reads the copy GameKitBuild puts in
//           Assets/StreamingAssets/ (the same relative paths).
// Usage   : string text = ShellFiles.ReadOrNull("data/i18n/en.json");     // null when neither copy exists
//           foreach (string path in ShellFiles.List("data/i18n", "*.json")) ...
// Notes   : StreamingAssets wins when both exist (a player never sees the project root). On Android the
//           StreamingAssets folder is inside the APK and File.ReadAllText cannot open it (verify: not tested;
//           a UnityWebRequest read would be needed there).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace {{GAME_SLUG}}.Shell
{
    public static class ShellFiles
    {
        /// <summary>The folder above Assets/ (the project root in the editor, next to the player otherwise).</summary>
        public static string ProjectRoot => Path.GetFullPath(Path.Combine(Application.dataPath, ".."));

        /// <summary>The first existing copy of a relative path: StreamingAssets, then the project root; null when none.</summary>
        public static string Find(string relative)
        {
            foreach (string root in Roots())
            {
                string path = Path.Combine(root, relative);
                if (File.Exists(path))
                {
                    return path;
                }
            }
            return null;
        }

        public static string ReadOrNull(string relative)
        {
            string path = Find(relative);
            if (path == null)
            {
                return null;
            }
            try
            {
                return File.ReadAllText(path, System.Text.Encoding.UTF8);
            }
            catch (IOException e)
            {
                Debug.LogWarning($"[WARN][shell] cannot read {path}: {e.Message}");
                return null;
            }
        }

        /// <summary>Files matching pattern in the first root that has the folder (sorted by name).</summary>
        public static List<string> List(string relativeDir, string pattern)
        {
            var found = new List<string>();
            foreach (string root in Roots())
            {
                string dir = Path.Combine(root, relativeDir);
                if (Directory.Exists(dir))
                {
                    found.AddRange(Directory.GetFiles(dir, pattern));
                    found.Sort(System.StringComparer.Ordinal);
                    return found;
                }
            }
            return found;
        }

        private static IEnumerable<string> Roots()
        {
            yield return Application.streamingAssetsPath;
            if (Application.isEditor || Application.platform == RuntimePlatform.WindowsPlayer
                || Application.platform == RuntimePlatform.LinuxPlayer || Application.platform == RuntimePlatform.OSXPlayer)
            {
                yield return ProjectRoot;
            }
        }
    }
}

// {{FOOTER}}
