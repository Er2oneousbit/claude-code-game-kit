// ---------------------------------------------------------------------------
// AtomicFile.cs
// Purpose : Crash-safe writes for settings and saves: the old file stays readable until the new one is
//           complete on disk, and the previous good version is kept as <file>.bak.
// Usage   : AtomicFile.Write(path, text);                                   // keeps <path>.bak
//           AtomicFile.Write(path, text, isGood: old => ...);               // back up only a valid old file
//           string text = AtomicFile.ReadOrNull(path);                      // null = no file
//           (path from Application.persistentDataPath in game code; Core itself has no UnityEngine types)
// Notes   : A crash, power cut or killed process between WriteTemp and Commit leaves the old file intact; the
//           stale <file>.tmp is overwritten by the next write. Tested against the real filesystem in
//           Assets/Tests/EditMode/AtomicFileTests.cs. Text is UTF-8 without a BOM. The replace uses
//           File.Replace (one rename on the same folder); a platform without it (some WebGL runtimes, verify)
//           falls back to delete and move, where a crash in between leaves .tmp and .bak but no primary.
//
// Pseudocode:
//   WriteTemp: create the folder ; write <file>.tmp ; flush to disk (a full disk throws here, nothing replaced)
//   Commit:    if <file> exists: copy it to <file>.bak when backup and isGood(old) ; replace <file> with .tmp
//              else rename .tmp to <file>
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.IO;
using System.Text;

namespace {{GAME_SLUG}}.Core
{
    public static class AtomicFile
    {
        // ---- Tunables ------------------------------------------------------------
        public const string TMP_SUFFIX = ".tmp";
        public const string BAK_SUFFIX = ".bak";

        private static readonly Encoding UTF8_NO_BOM = new UTF8Encoding(false);

        /// <summary>Writes text to path atomically. backup keeps the replaced file as path.bak; isGood (optional)
        /// decides whether the old text deserves the backup, so a corrupt file never replaces a good .bak.</summary>
        public static void Write(string path, string text, bool backup = true, Func<string, bool> isGood = null)
        {
            WriteTemp(path, text);
            Commit(path, backup, isGood);
        }

        /// <summary>Step 1: the complete new text in path.tmp, flushed to disk. Returns the .tmp path.</summary>
        public static string WriteTemp(string path, string text)
        {
            if (string.IsNullOrEmpty(path))
            {
                throw new ArgumentException("no file path", nameof(path));
            }
            string folder = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(folder))
            {
                Directory.CreateDirectory(folder);
            }
            string tmp = path + TMP_SUFFIX;
            byte[] bytes = UTF8_NO_BOM.GetBytes(text ?? "");
            using (var stream = new FileStream(tmp, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush(true);                    // through the OS cache, so the rename never points at nothing
            }
            return tmp;
        }

        /// <summary>Step 2: back up the old file (if wanted and good), then put path.tmp in its place.</summary>
        public static void Commit(string path, bool backup = true, Func<string, bool> isGood = null)
        {
            string tmp = path + TMP_SUFFIX;
            if (!File.Exists(tmp))
            {
                throw new FileNotFoundException($"nothing to commit: {tmp} is missing", tmp);
            }
            if (!File.Exists(path))
            {
                File.Move(tmp, path);
                return;
            }
            if (backup)
            {
                string old = ReadOrNull(path);
                if (old != null && (isGood == null || isGood(old)))
                {
                    File.Copy(path, path + BAK_SUFFIX, true);
                }
            }
            try
            {
                File.Replace(tmp, path, null);
            }
            catch (PlatformNotSupportedException)
            {
                File.Delete(path);
                File.Move(tmp, path);
            }
        }

        /// <summary>The file's text (UTF-8, a BOM is skipped), or null when there is no file.</summary>
        public static string ReadOrNull(string path)
        {
            return File.Exists(path) ? File.ReadAllText(path, Encoding.UTF8) : null;
        }
    }
}

// {{FOOTER}}
