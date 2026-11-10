// ---------------------------------------------------------------------------
// CrashTextTests.cs
// Purpose : The crash file's text, its free file name and the log tail (Core/CrashText.cs, #275).
// Usage   : python tools/dev.py test --filter CrashText
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public class CrashTextTests
    {
        [Test]
        public void CrashText_TextCarriesVersionErrorStackSettingsAndTail()
        {
            string text = CrashText.Text(new CrashInfo
            {
                Game = "Ícaro’s Game", Version = "0.2.0", Engine = "Unity 6000.6.6f1 (debug build), Windows",
                Time = "2026-11-10T10:00:00Z", Screen = "main_menu", Error = "InvalidOperationException: boom",
                Stack = "FrontEnd.Update ()\n", Settings = "{\"version\": 1}", LogTail = "[INFO][shell] screen: title",
            });
            StringAssert.StartsWith("crash report\n", text);
            StringAssert.Contains("game: Ícaro’s Game 0.2.0\n", text);
            StringAssert.Contains("screen: main_menu\n", text);
            StringAssert.Contains("error: InvalidOperationException: boom\n", text);
            StringAssert.Contains("stack trace:\nFrontEnd.Update ()\n", text);
            StringAssert.Contains("settings:\n{\"version\": 1}\n", text);
            StringAssert.Contains("[INFO][shell] screen: title\n", text);
        }

        [Test]
        public void CrashText_MissingFieldsNeverThrow()
        {
            string text = CrashText.Text(new CrashInfo());
            StringAssert.Contains("seed: none", text);
            StringAssert.Contains("(no log lines)", text);
            StringAssert.Contains("(not loaded)", text);
        }

        [Test]
        public void CrashText_FileNameSkipsTakenNames()
        {
            var taken = new HashSet<string> { "crash_20261110_100000.txt", "crash_20261110_100000_2.txt" };
            Assert.AreEqual("crash_20261110_100000_3.txt", CrashText.FileName("20261110_100000", taken.Contains));
            Assert.AreEqual("crash_20261110_100001.txt", CrashText.FileName("20261110_100001", taken.Contains));
        }

        [Test]
        public void LogTail_KeepsTheLastLinesAndSplitsEntries()
        {
            var tail = new LogTail(3);
            tail.Add("one");
            tail.Add("two\nthree");
            tail.Add("four");
            Assert.AreEqual(3, tail.Count);
            Assert.AreEqual("two\nthree\nfour", tail.Text(10));
            Assert.AreEqual("four", tail.Text(1));
            Assert.AreEqual("", new LogTail(5).Text(5));
        }
    }
}

// {{FOOTER}}
