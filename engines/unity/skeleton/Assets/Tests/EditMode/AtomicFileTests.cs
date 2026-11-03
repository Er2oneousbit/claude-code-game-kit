// ---------------------------------------------------------------------------
// AtomicFileTests.cs
// Purpose : AtomicFile, SaveStore and GameSettings files against the real filesystem (a temp folder per
//           test): the .bak copy, a crash between writing .tmp and the rename, corrupt and newer saves.
// Usage   : python tools/dev.py test              (or --filter AtomicFile)
// Notes   : A crash is simulated by writing the .tmp (AtomicFile.WriteTemp) and never committing it, which is
//           exactly the state a killed process leaves behind. Each test deletes its folder afterwards.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public class AtomicFileTests
    {
        private string _dir;

        [SetUp]
        public void MakeFolder()
        {
            _dir = Path.Combine(Path.GetTempPath(), "gamekit_atomic_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_dir);
        }

        [TearDown]
        public void RemoveFolder()
        {
            try
            {
                Directory.Delete(_dir, true);
            }
            catch (IOException)
            {
                // a virus scanner holding a file: the OS temp cleanup gets it later
            }
        }

        private string FilePath(string name)
        {
            return Path.Combine(_dir, name);
        }

        [Test]
        public void AtomicFile_FirstWriteCreatesTheFileWithoutBackup()
        {
            string path = FilePath("a.json");
            AtomicFile.Write(path, "one");
            Assert.AreEqual("one", File.ReadAllText(path));
            Assert.IsFalse(File.Exists(path + AtomicFile.TMP_SUFFIX), "the .tmp is renamed away");
            Assert.IsFalse(File.Exists(path + AtomicFile.BAK_SUFFIX), "nothing to back up yet");
        }

        [Test]
        public void AtomicFile_SecondWriteKeepsThePreviousAsBak()
        {
            string path = FilePath("a.json");
            AtomicFile.Write(path, "one");
            AtomicFile.Write(path, "two");
            Assert.AreEqual("two", File.ReadAllText(path));
            Assert.AreEqual("one", File.ReadAllText(path + AtomicFile.BAK_SUFFIX));
        }

        [Test]
        public void AtomicFile_WritesIntoAMissingFolder()
        {
            string path = Path.Combine(_dir, "sub", "deeper", "a.json");
            AtomicFile.Write(path, "Í ”quoted”");
            Assert.AreEqual("Í ”quoted”", AtomicFile.ReadOrNull(path));
        }

        [Test]
        public void AtomicFile_CrashBeforeTheRenameLeavesTheOldFileIntact()
        {
            string path = FilePath("a.json");
            AtomicFile.Write(path, "good");
            AtomicFile.WriteTemp(path, "half writ");   // the process dies here: no Commit
            Assert.AreEqual("good", File.ReadAllText(path));
            Assert.IsTrue(File.Exists(path + AtomicFile.TMP_SUFFIX));
            AtomicFile.Write(path, "better");           // the next save overwrites the stale .tmp
            Assert.AreEqual("better", File.ReadAllText(path));
            Assert.AreEqual("good", File.ReadAllText(path + AtomicFile.BAK_SUFFIX));
            Assert.IsFalse(File.Exists(path + AtomicFile.TMP_SUFFIX));
        }

        [Test]
        public void AtomicFile_ABadOldFileDoesNotReplaceAGoodBackup()
        {
            string path = FilePath("a.json");
            AtomicFile.Write(path, "good-1");
            AtomicFile.Write(path, "good-2");           // .bak = good-1
            File.WriteAllText(path, "garbage");          // corrupted outside the game
            AtomicFile.Write(path, "good-3", true, old => old.StartsWith("good", StringComparison.Ordinal));
            Assert.AreEqual("good-3", File.ReadAllText(path));
            Assert.AreEqual("good-1", File.ReadAllText(path + AtomicFile.BAK_SUFFIX));
        }

        [Test]
        public void AtomicFile_CommitWithoutATempFileThrows()
        {
            Assert.Throws<FileNotFoundException>(() => AtomicFile.Commit(FilePath("none.json")));
        }

        [Test]
        public void AtomicFile_ReadOrNullIsNullForAMissingFile()
        {
            Assert.IsNull(AtomicFile.ReadOrNull(FilePath("none.json")));
        }

        // ---- SaveStore on disk ---------------------------------------------------------

        private static Dictionary<string, object> Data(double level)
        {
            return new Dictionary<string, object> { { "level", level }, { "health", 9.0 }, { "difficulty", "hard" } };
        }

        [Test]
        public void SaveStore_SaveThenLoadRoundTrips()
        {
            var saves = new SaveStore(_dir);
            saves.Save(1, Data(3));
            SaveLoadResult r = saves.Load(1);
            Assert.AreEqual(SaveStore.SOURCE_PRIMARY, r.Source);
            Assert.AreEqual(3.0, Json.ToNumber(r.Data["level"]));
            Assert.AreEqual((double)SaveStore.SAVE_VERSION, Json.ToNumber(r.Envelope["version"]));
        }

        [Test]
        public void SaveStore_NothingSavedIsNone()
        {
            SaveLoadResult r = new SaveStore(_dir).Load(7);
            Assert.AreEqual(SaveStore.SOURCE_NONE, r.Source);
            Assert.IsNull(r.Data);
            Assert.AreEqual(2, r.Problems.Count);
        }

        [Test]
        public void SaveStore_CorruptPrimaryFallsBackToTheBackup()
        {
            var saves = new SaveStore(_dir);
            saves.Save(1, Data(3));
            saves.Save(1, Data(4));                     // .bak holds level 3
            File.WriteAllText(saves.PathFor("1"), "{\"format\": \"save\", \"version\": 3, \"data\": {\"lev");
            SaveLoadResult r = saves.Load(1);
            Assert.AreEqual(SaveStore.SOURCE_BACKUP, r.Source);
            Assert.AreEqual(3.0, Json.ToNumber(r.Data["level"]));
        }

        [Test]
        public void SaveStore_CrashMidSaveStillLoadsTheOldSave()
        {
            var saves = new SaveStore(_dir);
            saves.Save(1, Data(3));
            AtomicFile.WriteTemp(saves.PathFor("1"), "{\"format\": \"sa");   // killed while writing the next save
            SaveLoadResult r = saves.Load(1);
            Assert.AreEqual(SaveStore.SOURCE_PRIMARY, r.Source);
            Assert.AreEqual(3.0, Json.ToNumber(r.Data["level"]));
        }

        [Test]
        public void SaveStore_OldSaveOnDiskIsMigrated()
        {
            var saves = new SaveStore(_dir);
            File.WriteAllText(saves.PathFor("2"), "{\"format\": \"save\", \"version\": 1, \"data\": {\"hp\": 7}}");
            SaveLoadResult r = saves.Load(2);
            Assert.AreEqual(7.0, Json.ToNumber(r.Data["health"]));
            Assert.AreEqual("normal", r.Data["difficulty"]);
            Assert.IsFalse(r.Data.ContainsKey("hp"));
        }

        [Test]
        public void SaveStore_NeverOverwritesASaveFromANewerBuild()
        {
            var saves = new SaveStore(_dir);
            string newer = "{\"format\": \"save\", \"version\": 99, \"data\": {\"level\": 50}}";
            File.WriteAllText(saves.PathFor("1"), newer);
            SaveLoadResult r = saves.Load(1);
            Assert.AreEqual(SaveStore.SOURCE_NONE, r.Source);
            Assert.Throws<InvalidOperationException>(() => saves.Save(1, Data(1)));
            Assert.AreEqual(newer, File.ReadAllText(saves.PathFor("1")));
        }

        [Test]
        public void SaveStore_ANewerBackupBlocksSavingToo()
        {
            // a newer build saved twice, then the primary was deleted: the next save after this one would copy the
            // old build's file over the newer .bak, so the slot is refused (no Load first: the rule is on disk)
            var saves = new SaveStore(_dir);
            string newer = "{\"format\": \"save\", \"version\": 99, \"data\": {\"level\": 50}}";
            File.WriteAllText(saves.PathFor("3") + AtomicFile.BAK_SUFFIX, newer);
            Assert.Throws<InvalidOperationException>(() => saves.Save(3, Data(1)));
            Assert.IsFalse(File.Exists(saves.PathFor("3")));
            Assert.AreEqual(newer, File.ReadAllText(saves.PathFor("3") + AtomicFile.BAK_SUFFIX));
        }

        // ---- Settings on disk ------------------------------------------------------------

        [Test]
        public void GameSettings_MissingFileIsDefaultsWithoutProblems()
        {
            SettingsLoadResult r = GameSettings.LoadFile(FilePath(GameSettings.FILE_NAME));
            Assert.AreEqual(0, r.Problems.Count);
            GoldenVectors.AssertClose(r.Settings, GameSettings.Defaults(), 0.0, "defaults");
        }

        [Test]
        public void GameSettings_SaveThenLoadRoundTripsAndKeepsUnknownKeys()
        {
            string path = FilePath(GameSettings.FILE_NAME);
            Dictionary<string, object> s = GameSettings.Defaults();
            ((Dictionary<string, object>)s["audio"])["music"] = 0.25;
            s["mod_settings"] = new Dictionary<string, object> { { "fov", 90.0 } };
            GameSettings.SaveFile(path, s);
            SettingsLoadResult r = GameSettings.LoadFile(path);
            Assert.AreEqual(0, r.Problems.Count, string.Join(" | ", r.Problems));
            GoldenVectors.AssertClose(r.Settings, s, 0.0, "round trip");
        }

        [Test]
        public void GameSettings_UnreadableFileLoadsTheBackup()
        {
            string path = FilePath(GameSettings.FILE_NAME);
            Dictionary<string, object> s = GameSettings.Defaults();
            ((Dictionary<string, object>)s["access"])["shake_scale"] = 0.5;
            GameSettings.SaveFile(path, s);
            GameSettings.SaveFile(path, GameSettings.Defaults());   // .bak = the 0.5 file
            File.WriteAllText(path, "{\"audio\": ");
            SettingsLoadResult r = GameSettings.LoadFile(path);
            Assert.AreEqual(0.5, GameSettings.EffectiveShake(r.Settings), 1e-12);
            Assert.AreEqual(1, r.Problems.Count, "one problem: the main file was unreadable");
        }
    }
}

// {{FOOTER}}
