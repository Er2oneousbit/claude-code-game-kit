// ---------------------------------------------------------------------------
// CrashText.cs
// Purpose : The text of a crash file and of the F8 bug report's info file, the log tail both carry, and the file names
//           they use (#275: the files Godot, LÖVE and web already write). The Shell side (Shell/ShellReports.cs)
//           hooks Unity's log and writes them into the user-data folder.
// Usage   : var tail = new LogTail(200);  tail.Add("[INFO][shell] screen: title");  string text = tail.Text(50);
//           string body = CrashText.Text(new CrashInfo { Game = "My Game", Version = "0.1.0", Error = "boom", ... });
//           string name = CrashText.FileName("20261110_101500", n => File.Exists(dir + n));   // crash_<stamp>[_n].txt
// Notes   : No UnityEngine types (EditMode tests run it). LogTail is safe to fill from Unity's threaded log callback
//           (one lock). Text never throws on missing fields: a crash report must not hide the crash.
//
// Pseudocode:
//   LogTail.Add: append; past capacity drop the oldest
//   Text: header lines (game, engine, time, seed, screen, error) + stack + settings + log tail
//   FileName: crash_<stamp>.txt, else crash_<stamp>_2.txt ... (several crashes in one second), at most MAX_SAME_SECOND
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Text;

namespace graveyard_shift.Core
{
    /// <summary>The last N log lines, oldest first.</summary>
    public sealed class LogTail
    {
        private readonly int _capacity;
        private readonly Queue<string> _lines = new Queue<string>();
        private readonly object _lock = new object();

        public LogTail(int capacity)
        {
            _capacity = Math.Max(1, capacity);
        }

        public int Count
        {
            get
            {
                lock (_lock)
                {
                    return _lines.Count;
                }
            }
        }

        /// <summary>Adds a log entry; a multi-line one counts as several lines.</summary>
        public void Add(string entry)
        {
            lock (_lock)
            {
                foreach (string line in (entry ?? "").Replace("\r\n", "\n").Split('\n'))
                {
                    _lines.Enqueue(line);
                    while (_lines.Count > _capacity)
                    {
                        _lines.Dequeue();
                    }
                }
            }
        }

        /// <summary>The last n lines joined with \n ("" when empty).</summary>
        public string Text(int n)
        {
            lock (_lock)
            {
                var all = new List<string>(_lines);
                int start = Math.Max(0, all.Count - Math.Max(0, n));
                return string.Join("\n", all.GetRange(start, all.Count - start));
            }
        }
    }

    /// <summary>What a crash file says. Every field may be null.</summary>
    public sealed class CrashInfo
    {
        public string Game;
        public string Version;
        public string Engine;        // "Unity 6000.6.6f1 (debug build), Windows 11"
        public string Time;          // ISO 8601, UTC
        public string Seed;
        public string Screen;
        public string Error;
        public string Stack;
        public string Settings;      // the settings tree as JSON
        public string LogTail;
    }

    public static class CrashText
    {
        // ---- Tunables ------------------------------------------------------------
        public const string DIR = "crashes";
        public const int CRASH_LOG_LINES = 50;       // log lines in a crash file
        public const int BUG_LOG_LINES = 200;        // log lines in a bug report
        public const int MAX_SAME_SECOND = 50;       // crash_<stamp>_2.txt ... when several crashes share a second

        public static string Text(CrashInfo c)
        {
            var sb = new StringBuilder();
            sb.Append("crash report\n");
            sb.Append($"game: {Or(c.Game, "game")} {Or(c.Version, "unknown")}\n");
            sb.Append($"engine: {Or(c.Engine, "unknown")}\n");
            sb.Append($"time: {Or(c.Time, "unknown")}\n");
            sb.Append($"seed: {Or(c.Seed, "none")}\n");
            sb.Append($"screen: {Or(c.Screen, "none")}\n");
            sb.Append($"error: {Or(c.Error, "?")}\n");
            sb.Append("\nstack trace:\n");
            sb.Append(Or(c.Stack, "(none)").TrimEnd()).Append('\n');
            sb.Append("\nsettings:\n");
            sb.Append(Or(c.Settings, "(not loaded)").TrimEnd()).Append('\n');
            sb.Append($"\nlog tail (last {CRASH_LOG_LINES} lines):\n");
            sb.Append(Or(c.LogTail, "(no log lines)").TrimEnd()).Append('\n');
            return sb.ToString();
        }

        /// <summary>The bug report's info.txt.</summary>
        public static string Info(string game, string version, string engine, string time, string screen, string seed, string locale)
        {
            return $"game: {Or(game, "game")} {Or(version, "unknown")}\nengine: {Or(engine, "unknown")}\ntime: {Or(time, "unknown")}\n"
                   + $"screen: {Or(screen, "none")}\nseed: {Or(seed, "none")}\nlocale: {Or(locale, "en")}\n";
        }

        /// <summary>A free crash file name for this stamp: crash_<stamp>.txt, then _2, _3 ... (the last one when all are taken).</summary>
        public static string FileName(string stamp, Func<string, bool> exists)
        {
            string name = $"crash_{stamp}.txt";
            for (int n = 2; exists != null && exists(name) && n <= MAX_SAME_SECOND; n++)
            {
                name = $"crash_{stamp}_{n}.txt";
            }
            return name;
        }

        private static string Or(string s, string fallback)
        {
            return string.IsNullOrEmpty(s) ? fallback : s;
        }
    }
}
