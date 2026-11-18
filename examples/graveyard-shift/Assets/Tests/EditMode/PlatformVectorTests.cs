// ---------------------------------------------------------------------------
// PlatformVectorTests.cs
// Purpose : Runs every case of data/golden/platform.json through Core/Platform.cs (achievements and stats, rich
//           presence, the overlay's pause hook, cloud saves, the state file, the null backend): one test per case;
//           then the PlatformService the shell owns (the cached state file, the save hook, nothing written without
//           data/achievements.json).
// Usage   : python tools/dev.py test              (or --filter Platform)
// Notes   : The expected values come from the file at test time. A case type without a runner fails. A step's
//           calls are what the rules sent to their backend during that step; "fail_store" is the null backend's
//           hook (its next store_stats fails).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using System.IO;
using System.Linq;
using NUnit.Framework;
using graveyard_shift.Core;
using G = graveyard_shift.Tests.GoldenVectors;

namespace graveyard_shift.Tests
{
    public class PlatformVectorTests
    {
        private const string FILE = "platform.json";
        private const string SAMPLE = "{\"stats\": [{\"id\": \"kills\", \"max\": 100, \"increment_only\": true}], \"achievements\": [{\"id\": \"first\", \"name\": \"First\"}, {\"id\": \"kills_10\", \"name\": \"Ten\", \"stat\": \"kills\", \"threshold\": 10}]}";

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Platform");
        }

        private static void Same(object actual, object expected, double tol, string where)
        {
            string d = G.Diff(actual, expected, tol);
            Assert.IsNull(d, $"{where}: {d}");
        }

        private static List<object> L(IEnumerable<string> items) => items.Cast<object>().ToList();

        [TestCaseSource(nameof(Cases))]
        public void Platform(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            double tol = G.Tolerance(FILE);
            switch (G.Str(c, "type"))
            {
                case "platform_format":
                    var mine = new Dictionary<string, object>(c)
                    {
                        ["state_format"] = PlatformRules.FORMAT, ["state_file"] = PlatformRules.STATE_FILE,
                        ["state_version"] = (double)PlatformRules.STATE_VERSION, ["id_max"] = (double)PlatformRules.ID_MAX,
                        ["stat_types"] = L(PlatformRules.STAT_TYPES), ["presence_max_keys"] = (double)PlatformRules.PRESENCE_MAX_KEYS,
                        ["presence_max_value_bytes"] = (double)PlatformRules.PRESENCE_MAX_VALUE_BYTES,
                        ["cloud_modes"] = L(PlatformRules.CLOUD_MODES), ["cloud_local_names"] = L(PlatformRules.CLOUD_LOCAL_NAMES),
                        ["cloud_local_suffixes"] = L(PlatformRules.CLOUD_LOCAL_SUFFIXES),
                        ["cloud_local_dirs"] = L(PlatformRules.CLOUD_LOCAL_DIRS),
                        ["overlay_pause_screens"] = L(PlatformRules.OVERLAY_PAUSE_SCREENS),
                    };
                    Same(mine, c, tol, "format");
                    break;
                case "achievements_load":
                    foreach (List<object> p in G.List(c, "points"))
                    {
                        var defs = PlatformRules.AchievementsLoad(p[1] as string, out int problems);
                        Same(defs, p[2], tol, $"{p[0]}: defs");
                        Same((double)problems, p[3], tol, $"{p[0]}: problems");
                    }
                    break;
                case "cloud_partition":
                    foreach (List<object> p in G.List(c, "points"))
                    {
                        Same(PlatformRules.CloudPartition((string)p[0]), p[1], tol, $"\"{p[0]}\"");
                    }
                    break;
                case "overlay":
                    foreach (List<object> p in G.List(c, "points"))
                    {
                        Same(PlatformRules.OverlayAction((bool)p[0], (string)p[1]), p[2], tol, $"{p[0]} {p[1]}");
                    }
                    break;
                case "platform_script":
                    RunScript(c, tol);
                    break;
                case "platform_state_load":
                    foreach (List<object> p in G.List(c, "points"))
                    {
                        var state = PlatformRules.StateLoad(G.Obj(c, "defs"), p[1] as string, out int problems);
                        Same(state, p[2], tol, $"{p[0]}: state");
                        Same((double)problems, p[3], tol, $"{p[0]}: problems");
                    }
                    break;
                case "null_backend":
                    RunNullBackend(c, tol);
                    break;
                default:
                    Assert.Fail($"no runner for case type '{G.Str(c, "type")}': port it, then add it here");
                    break;
            }
        }

        private static PlatformOut Step(PlatformRules p, NullPlatformBackend nb, List<object> op)
        {
            switch ((string)op[0])
            {
                case "fail_store":
                    nb.FailStores++;
                    return new PlatformOut { Out = null, Calls = new List<object>() };
                case "overlay":
                    return new PlatformOut { Out = PlatformRules.OverlayAction((bool)op[1], (string)op[2]), Calls = new List<object>() };
                case "unlock": return p.Unlock((string)op[1]);
                case "set_stat": return p.SetStat((string)op[1], op[2]);
                case "add_stat": return p.AddStat((string)op[1], op[2]);
                case "flush": return p.Flush();
                case "set_presence": return p.SetPresence(op[1], op[2]);
                case "clear_presence": return p.ClearPresence();
                case "saved": return p.Saved((string)op[1]);
                case "connect": return p.Connect((Dictionary<string, object>)op[1]);
                case "disconnect": return p.Disconnect();
                case "reset_all": return p.ResetAll();
            }
            Assert.Fail($"unknown step {op[0]}");
            return default;
        }

        private static void RunScript(Dictionary<string, object> c, double tol)
        {
            var nb = new NullPlatformBackend();
            var p = new PlatformRules(G.Obj(c, "defs"), nb, G.Bool(c, "online"), G.Str(c, "cloud"));
            int i = 0;
            foreach (Dictionary<string, object> s in G.List(c, "steps"))
            {
                var op = G.List(s, "op");
                PlatformOut r = Step(p, nb, op);
                string w = $"{G.Str(c, "name")} step {i++} {op[0]}";
                Same(r.Out, s["out"], tol, w + ": out");
                Same(r.Calls, s["calls"], tol, w + ": calls");
                Same(p.State(), s["state"], tol, w + ": state");
                Same(p.PresenceList(), s["presence"], tol, w + ": presence");
                Same(p.Online, s["online"], tol, w + ": online");
            }
        }

        private static void RunNullBackend(Dictionary<string, object> c, double tol)
        {
            var nb = new NullPlatformBackend();
            int i = 0;
            foreach (List<object> s in G.List(c, "sends"))
            {
                var call = (List<object>)s[0];
                object got = null;
                if (call.Count == 1 && (string)call[0] == "fail_next_store")
                {
                    nb.FailStores++;
                }
                else
                {
                    got = nb.Send(call);
                }
                string w = $"send {i++} {call[0]}";
                Same(got, s[1], tol, w + ": ok");
                Same(nb.Remote(), s[2], tol, w + ": remote");
                Same(nb.PresenceList(), s[3], tol, w + ": presence");
                Same(nb.Cloud, s[4], tol, w + ": cloud");
            }
            Same(nb.Calls, c["calls"], tol, "calls");
        }

        private static string Scratch()
        {
            string dir = Path.Combine(Path.GetTempPath(), "gamekit-platform-Í-" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            return dir;
        }

        [Test]
        public void Platform_ServiceWritesNothingWithoutAchievements()
        {
            string dir = Scratch();
            var ps = new PlatformService(dir, null);
            Assert.IsFalse(ps.Active);
            Assert.AreEqual("unknown", ps.Unlock("first"));
            Assert.AreEqual("nothing", ps.Flush());
            Assert.AreEqual("cloud", ps.Saved("save_1.json"));
            Assert.AreEqual(0, Directory.GetFiles(dir).Length);
            Directory.Delete(dir, true);
        }

        [Test]
        public void Platform_ServiceCachesItsStateFile()
        {
            string dir = Scratch();
            var ps = new PlatformService(dir, SAMPLE);
            Assert.AreEqual("ok", ps.AddStat("kills", 12));
            Assert.AreEqual("unlocked", ps.Unlock("first"));
            var again = new PlatformService(dir, SAMPLE);
            CollectionAssert.AreEqual(new[] { "kills_10", "first" }, again.Rules.Unlocked);
            Assert.AreEqual("already", again.Unlock("first"));
            Assert.IsFalse(File.Exists(Path.Combine(dir, PlatformRules.STATE_FILE + ".tmp")));
            Directory.Delete(dir, true);
        }

        [Test]
        public void Platform_ASaveReachesSaved()
        {
            string dir = Scratch();
            var ps = new PlatformService(dir, SAMPLE, null, "api");
            var seen = new List<string>();
            var saves = new SaveStore(dir) { OnSaved = name => { seen.Add(name); ps.Saved(name); } };
            saves.Save(1, new Dictionary<string, object> { { "level", 1.0 } });
            CollectionAssert.AreEqual(new[] { "save_1.json" }, seen);
            CollectionAssert.AreEqual(new object[] { "save_1.json" }, ((NullPlatformBackend)ps.Backend).Cloud);
            Directory.Delete(dir, true);
        }

        private sealed class FakeSteam : ISteamCalls
        {
            public readonly List<string> Log = new List<string>();
            public bool StoreOk = true;
            public event System.Action<bool> OverlayChanged;
            public event System.Action<bool> StatsStored;
            public void Overlay(bool active) => OverlayChanged?.Invoke(active);
            public void Stored(bool ok) => StatsStored?.Invoke(ok);
            public bool SetAchievement(string id) { Log.Add("SetAchievement " + id); return true; }
            public bool GetAchievement(string id, out bool achieved) { achieved = id == "first"; return true; }
            public bool SetStat(string id, int value) { Log.Add($"SetStat {id} {value}"); return true; }
            public bool SetStat(string id, float value) { Log.Add($"SetStatF {id}"); return true; }
            public bool GetStat(string id, out int value) { value = 4; return true; }
            public bool GetStat(string id, out float value) { value = 0f; return true; }
            public bool StoreStats() { Log.Add("StoreStats"); return StoreOk; }
            public bool IndicateAchievementProgress(string id, uint current, uint max) => true;
            public bool ResetAllStats(bool achievementsToo) => true;
            public bool SetRichPresence(string key, string value) { Log.Add($"SetRichPresence {key} {value}"); return true; }
            public void ClearRichPresence() { }
            public bool FileWrite(string name, byte[] data) { Log.Add("FileWrite " + name); return true; }
            public void RunCallbacks() => Log.Add("RunCallbacks");
        }

        [Test]
        public void Platform_SteamStartsWithoutAchievements()
        {
            // docs/PLATFORM.md section 6: an enabled backend starts whether or not data/achievements.json exists
            string dir = Scratch();
            var fake = new FakeSteam();
            var none = PlatformRules.AchievementsLoad(null, out _);
            IPlatformBackend b = PlatformStart.Make(false, none, dir, (d, f) => new SteamPlatformBackend(d, f, fake));
            Assert.IsNotNull(b, "no achievements file: Steam still starts");
            var ps = new PlatformService(dir, null, b);
            Assert.AreEqual("ok", ps.SetPresence("status", "Menu"));
            CollectionAssert.AreEqual(new[] { "SetRichPresence status Menu" }, fake.Log);
            Assert.IsNull(PlatformStart.Make(true, none, dir, (d, f) => new SteamPlatformBackend(d, f, fake)), "smoke: null");
            Directory.Delete(dir, true);
        }

        [Test]
        public void Platform_ALateUserStatsStoredFailureRequeuesTheStore()
        {
            string dir = Scratch();
            var fake = new FakeSteam();
            var defs = PlatformRules.AchievementsLoad(SAMPLE, out _);
            var ps = new PlatformService(dir, SAMPLE, new SteamPlatformBackend(defs, dir, fake));
            Assert.AreEqual("ok", ps.AddStat("kills", 12));   // the store had 4: 16, kills_10 unlocks and flushes
            Assert.IsTrue(ps.Rules.Online);
            fake.Stored(false);                                // UserStatsStored_t: failed
            ps.Update();
            Assert.IsFalse(ps.Rules.Online, "a late failure takes the layer offline");
            Same(ps.Rules.State()["pending"], Json.Parse("{\"stats\": [\"kills\"], \"unlocks\": [\"kills_10\"], \"cloud\": []}"), 0, "queued again");
            fake.Log.Clear();
            ps.Rules.Connect(new Dictionary<string, object>());
            CollectionAssert.AreEqual(new[] { "SetStat kills 16", "SetAchievement kills_10", "StoreStats" }, fake.Log);
            fake.Stored(true);
            ps.Update();
            Assert.IsTrue(ps.Rules.Online);
            Directory.Delete(dir, true);
        }

        [Test]
        public void Platform_SteamBackendMapsCallsAndARefusedStore()
        {
            string dir = Scratch();
            var fake = new FakeSteam();
            var defs = PlatformRules.AchievementsLoad(SAMPLE, out _);
            var steam = new SteamPlatformBackend(defs, dir, fake);
            Same(steam.Remote(), Json.Parse("{\"unlocked\": [\"first\"], \"stats\": {\"kills\": 4}}"), 0, "remote");
            var ps = new PlatformService(dir, SAMPLE, steam);
            Assert.AreEqual("ok", ps.AddStat("kills", 12));   // the store had 4: 16, and kills_10 unlocks
            CollectionAssert.AreEqual(new[] { "SetStat kills 16", "SetAchievement kills_10", "StoreStats" }, fake.Log);
            fake.Log.Clear();
            fake.StoreOk = false;
            Assert.AreEqual("ok", ps.SetStat("kills", 20));
            Assert.AreEqual("failed", ps.Flush());
            Assert.IsFalse(ps.Rules.Online, "a refused StoreStats takes the layer offline");
            fake.Overlay(true);
            Assert.AreEqual(true, ps.Update());
            Assert.AreEqual(null, ps.Update());
            Assert.AreEqual("RunCallbacks", fake.Log[fake.Log.Count - 1]);
            Directory.Delete(dir, true);
        }
    }
}
