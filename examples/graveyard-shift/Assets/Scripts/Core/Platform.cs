// ---------------------------------------------------------------------------
// Platform.cs
// Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
//           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null backend
//           (it records every call); the Steamworks.NET adapter (Assets/Scripts/Shell/PlatformSteam.cs, compiled only
//           with the GAMEKIT_STEAM scripting define) replaces it in a store build. Checked against
//           data/golden/platform.json (every case).
// Usage   : Shell.Instance.Platform.Unlock("first_win"); Shell.Instance.Platform.AddStat("enemies_defeated", 1);
//           Shell.Instance.Platform.Flush();                     // at checkpoints (the shell flushes on pause, quit)
//           Shell.Instance.Platform.SetPresence("status", "In the crypt");
//           pure parts: PlatformRules.AchievementsLoad(text), CloudPartition(path), OverlayAction(active, screen),
//           new PlatformRules(defs, new NullPlatformBackend(), online, cloud), PlatformRules.StateLoad(defs, text)
// Notes   : No UnityEngine types (EditMode tests run it). Values are Json.cs's tree (Dictionary, List, double,
//           string, bool, null) and calls are lists (["set_stat", "coins", 7.0]), so tests compare them with the
//           vectors as they are; SetStat takes an object so a string or a bool is refused by the rules, never by a
//           cast. Comparisons are ordinal (never the culture: a Turkish locale must not change "SETTINGS.JSON").
//           With no data/achievements.json every call is "unknown" and nothing is written, so a game without
//           achievements runs exactly as before. The state file is a cache, written atomically only when it changed.
//
// Pseudocode:
//   rules op -> update local state -> online: send calls to the backend one at a time, in order
//   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
//          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
//   service: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
//          connect(backend.remote()) ; after every op: write the state file when it changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): TakeStoreFailure and StoreFailed: a store that failed after
//           it was accepted (Steam's UserStatsStored) goes back on the queue; PlatformStart (Steam starts without
//           achievements too)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace graveyard_shift.Core
{
    /// <summary>The backend interface (PLATFORM.md section 4). Send returns false only for a refused store_stats.</summary>
    public interface IPlatformBackend
    {
        string Name { get; }
        bool Available();
        /// <summary>{"unlocked": [...], "stats": {...}} as the store holds them.</summary>
        Dictionary<string, object> Remote();
        bool Send(List<object> call);
        /// <summary>Each frame: run the SDK's callbacks; true/false when the store overlay opened/closed, else null.</summary>
        bool? Update();
        /// <summary>A store that failed after Send(["store_stats"]) returned true (Steam's UserStatsStored): its
        /// set_stat and set_achievement calls, oldest first; null when none.</summary>
        List<object> TakeStoreFailure() => null;
    }

    /// <summary>The start rule (docs/PLATFORM.md section 6): an enabled store backend starts whether or not the game
    /// has achievements, since presence, the overlay and cloud saves need it too; a smoke run never asks.</summary>
    public static class PlatformStart
    {
        public static IPlatformBackend Make(bool smoke, Dictionary<string, object> defs, string dataFolder,
                                            Func<Dictionary<string, object>, string, IPlatformBackend> factory)
        {
            return smoke || factory == null ? null : factory(defs, dataFolder);
        }
    }

    /// <summary>The backend every game runs by default: records every call and keeps what a store would hold.</summary>
    public sealed class NullPlatformBackend : IPlatformBackend
    {
        public readonly List<object> Calls = new List<object>();
        public List<object> Unlocked = new List<object>();
        public Dictionary<string, object> Stats = new Dictionary<string, object>();
        public SortedDictionary<string, string> Presence = new SortedDictionary<string, string>(StringComparer.Ordinal);
        public readonly List<object> Cloud = new List<object>();
        /// <summary>Test hook: the next N store_stats fail (a failed store lands nothing).</summary>
        public int FailStores;
        private List<string> _stagedUnlocks = new List<string>();
        private Dictionary<string, object> _stagedStats = new Dictionary<string, object>();

        public string Name => "null";
        public bool Available() => true;
        public bool? Update() => null;

        public Dictionary<string, object> Remote()
        {
            return new Dictionary<string, object> { { "unlocked", new List<object>(Unlocked) }, { "stats", new Dictionary<string, object>(Stats) } };
        }

        public List<object> PresenceList()
        {
            return Presence.Select(p => (object)new List<object> { p.Key, p.Value }).ToList();
        }

        public bool Send(List<object> call)
        {
            Calls.Add(new List<object>(call));
            string name = call[0] as string;
            switch (name)
            {
                case "set_achievement":
                    if (!_stagedUnlocks.Contains((string)call[1])) _stagedUnlocks.Add((string)call[1]);
                    break;
                case "set_stat":
                    _stagedStats[(string)call[1]] = call[2];
                    break;
                case "store_stats":
                    if (FailStores > 0)
                    {
                        FailStores--;
                        return false;
                    }
                    foreach (string u in _stagedUnlocks)
                    {
                        if (!Unlocked.Contains(u)) Unlocked.Add(u);
                    }
                    foreach (var kv in _stagedStats) Stats[kv.Key] = kv.Value;
                    _stagedUnlocks = new List<string>();
                    _stagedStats = new Dictionary<string, object>();
                    break;
                case "reset_all_stats":
                    Unlocked = new List<object>();
                    Stats = new Dictionary<string, object>();
                    _stagedUnlocks = new List<string>();
                    _stagedStats = new Dictionary<string, object>();
                    break;
                case "set_presence":
                    if ((string)call[2] == "") Presence.Remove((string)call[1]);
                    else Presence[(string)call[1]] = (string)call[2];
                    break;
                case "clear_presence":
                    Presence.Clear();
                    break;
                case "cloud_write":
                    if (!Cloud.Contains(call[1])) Cloud.Add(call[1]);
                    break;
            }
            return true;
        }
    }

    /// <summary>A status word (null for a test hook step) and the calls sent during the operation, in order.</summary>
    public struct PlatformOut
    {
        public object Out;
        public List<object> Calls;
    }

    /// <summary>The rules (PLATFORM.md section 3).</summary>
    public sealed class PlatformRules
    {
        // ---- Tunables (the same in every engine: data/golden/platform.json "names and limits") ------
        public const string FORMAT = "platform_state";
        public const int STATE_VERSION = 1;
        public const string STATE_FILE = "platform_state.json";
        public const string ACHIEVEMENTS_FILE = "achievements.json";   // under data/
        public const int ID_MAX = 64;
        public static readonly string[] STAT_TYPES = { "int", "float" };
        public const int PRESENCE_MAX_KEYS = 30;                       // Steam's rich presence limits (verify)
        public const int PRESENCE_MAX_VALUE_BYTES = 255;
        public static readonly string[] CLOUD_MODES = { "auto", "api" };
        public static readonly string[] CLOUD_LOCAL_NAMES = { "settings.json", STATE_FILE, "telemetry.csv", "log_tail.txt" };
        public static readonly string[] CLOUD_LOCAL_SUFFIXES = { ".tmp", ".log" };
        public static readonly string[] CLOUD_LOCAL_DIRS = { "logs", "crashes", "captures" };
        public static readonly string[] OVERLAY_PAUSE_SCREENS = { "play" };
        /// <summary>"auto" (Steam Auto-Cloud, no code, preferred) or "api" (the adapter writes cloud files itself).</summary>
        public const string CLOUD_MODE = "auto";

        // ---- small rules ---------------------------------------------------------------

        /// <summary>An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first.</summary>
        public static bool IdOk(object v)
        {
            if (!(v is string s) || s.Length == 0 || s.Length > ID_MAX) return false;
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                bool letter = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
                if (i == 0 && !letter) return false;
                if (!(letter || (c >= '0' && c <= '9') || c == '_')) return false;
            }
            return true;
        }

        private static bool NumOk(object v) => Json.IsNumber(v) && !double.IsNaN(Json.ToNumber(v)) && !double.IsInfinity(Json.ToNumber(v));
        private static bool Whole(object v) => NumOk(v) && Math.Floor(Json.ToNumber(v)) == Json.ToNumber(v);
        private static bool OkFor(string kind, object v) => kind == "int" ? Whole(v) : NumOk(v);
        private static double N(object v) => Json.ToNumber(v);

        /// <summary>Python's dict.get(key, default): a key holding null is null, not the default.</summary>
        private static object Get(Dictionary<string, object> o, string key, object dflt)
        {
            return o != null && o.TryGetValue(key, out object v) ? v : dflt;
        }

        private static double Clamp(Dictionary<string, object> sdef, double v)
        {
            v = Math.Max(v, N(sdef["min"]));
            return sdef["max"] == null ? v : Math.Min(v, N(sdef["max"]));
        }

        private static double Initial(Dictionary<string, object> sdef) => Clamp(sdef, 0);

        private static Dictionary<string, object> EmptyDefs()
        {
            return new Dictionary<string, object> { { "version", (double)STATE_VERSION }, { "stats", new List<object>() }, { "achievements", new List<object>() } };
        }

        /// <summary>data/achievements.json text (null or "" = no file) -> the definitions; problems counts dropped entries.</summary>
        public static Dictionary<string, object> AchievementsLoad(string text, out int problems)
        {
            problems = 0;
            if (string.IsNullOrEmpty(text)) return EmptyDefs();
            if (!Json.TryParse(text, out object parsed) || !(parsed is Dictionary<string, object> raw))
            {
                problems = 1;
                return EmptyDefs();
            }
            var stats = new List<object>();
            var byId = new Dictionary<string, Dictionary<string, object>>(StringComparer.Ordinal);
            if (!(Get(raw, "stats", new List<object>()) is List<object> rawStats))
            {
                rawStats = new List<object>();
                problems++;
            }
            foreach (object item in rawStats)
            {
                var s = item as Dictionary<string, object>;
                bool ok = s != null && IdOk(Get(s, "id", null)) && !byId.ContainsKey((string)s["id"]);
                object kind = null, lo = null, hi = null, inc = null;
                if (ok)
                {
                    kind = Get(s, "type", "int");
                    lo = Get(s, "min", 0.0);
                    hi = Get(s, "max", null);
                    inc = Get(s, "increment_only", false);
                    ok = kind is string k && STAT_TYPES.Contains(k) && OkFor(k, lo) && (hi == null || (OkFor(k, hi) && N(hi) >= N(lo))) && inc is bool;
                }
                if (!ok)
                {
                    problems++;
                    continue;
                }
                var sdef = new Dictionary<string, object>
                {
                    { "id", s["id"] }, { "type", kind }, { "min", N(lo) }, { "max", hi == null ? null : (object)N(hi) }, { "increment_only", inc },
                };
                byId[(string)s["id"]] = sdef;
                stats.Add(sdef);
            }
            var achievements = new List<object>();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            if (!(Get(raw, "achievements", new List<object>()) is List<object> rawAch))
            {
                rawAch = new List<object>();
                problems++;
            }
            foreach (object item in rawAch)
            {
                var a = item as Dictionary<string, object>;
                bool ok = a != null && IdOk(Get(a, "id", null)) && !seen.Contains((string)a["id"]) && Get(a, "name", null) is string name
                          && name.Length > 0 && Get(a, "description", "") is string;
                object stat = null, threshold = null, every = null;
                Dictionary<string, object> sdef = null;
                if (ok)
                {
                    stat = Get(a, "stat", null);
                    threshold = Get(a, "threshold", null);
                    every = Get(a, "progress_every", null);
                    if (stat != null)
                    {
                        if (stat is string sid) byId.TryGetValue(sid, out sdef);
                        string k = sdef != null ? (string)sdef["type"] : "float";
                        ok = sdef != null && OkFor(k, threshold) && N(threshold) > Initial(sdef)
                             && (sdef["max"] == null || N(threshold) <= N(sdef["max"]))
                             && (every == null || (OkFor(k, every) && N(every) > 0 && N(every) < N(threshold)));
                    }
                    else
                    {
                        ok = threshold == null && every == null;   // a threshold without a stat is a mistake
                    }
                }
                if (!ok)
                {
                    problems++;
                    continue;
                }
                seen.Add((string)a["id"]);
                achievements.Add(new Dictionary<string, object>
                {
                    { "id", a["id"] }, { "name", a["name"] }, { "description", Get(a, "description", "") }, { "stat", stat },
                    { "threshold", stat == null ? null : (object)N(threshold) }, { "progress_every", every == null ? null : (object)N(every) },
                });
            }
            return new Dictionary<string, object> { { "version", (double)STATE_VERSION }, { "stats", stats }, { "achievements", achievements } };
        }

        /// <summary>Which user-data file syncs: "cloud" or "local" (ASCII-only folding, never the culture's).</summary>
        public static string CloudPartition(string path)
        {
            var folded = new StringBuilder(path.Length);
            foreach (char c in path) folded.Append(c >= 'A' && c <= 'Z' ? (char)(c + 32) : c);
            string[] parts = folded.ToString().Replace('\\', '/').Split('/').Where(p => p.Length > 0 && p != ".").ToArray();
            if (parts.Length == 0) return "local";
            string name = parts[parts.Length - 1];
            if ((parts.Length > 1 && CLOUD_LOCAL_DIRS.Contains(parts[0])) || CLOUD_LOCAL_NAMES.Contains(name)
                || CLOUD_LOCAL_SUFFIXES.Any(s => name.EndsWith(s, StringComparison.Ordinal)))
            {
                return "local";
            }
            return "cloud";
        }

        /// <summary>The store overlay opened (active) or closed over screen: "pause" opens the pause menu; closing never resumes.</summary>
        public static string OverlayAction(bool active, string screen)
        {
            return active && OVERLAY_PAUSE_SCREENS.Contains(screen) ? "pause" : "none";
        }

        // ---- the rules ----------------------------------------------------------------------

        public readonly Dictionary<string, object> Defs;
        public readonly IPlatformBackend Backend;
        public bool Online;
        public string Cloud;
        public List<string> Unlocked = new List<string>();
        public Dictionary<string, object> StatValues = new Dictionary<string, object>(StringComparer.Ordinal);
        public List<string> PendingStats = new List<string>();
        public List<string> PendingUnlocks = new List<string>();
        public List<string> PendingCloud = new List<string>();
        public readonly SortedDictionary<string, string> Presence = new SortedDictionary<string, string>(StringComparer.Ordinal);
        private readonly List<Dictionary<string, object>> _stats;
        private readonly List<Dictionary<string, object>> _ach;
        private List<object> _sent = new List<object>();

        public PlatformRules(Dictionary<string, object> defs, IPlatformBackend backend = null, bool online = false, string cloud = "auto")
        {
            Defs = defs;
            Backend = backend ?? new NullPlatformBackend();
            Online = online;
            Cloud = cloud;
            _stats = ((List<object>)defs["stats"]).Cast<Dictionary<string, object>>().ToList();
            _ach = ((List<object>)defs["achievements"]).Cast<Dictionary<string, object>>().ToList();
            ResetLocal();
        }

        private Dictionary<string, object> StatDef(string id) => _stats.FirstOrDefault(s => (string)s["id"] == id);
        public bool HasAchievement(string id) => _ach.Any(a => (string)a["id"] == id);

        private void ResetLocal()
        {
            Unlocked = new List<string>();
            StatValues = new Dictionary<string, object>(StringComparer.Ordinal);
            foreach (var s in _stats) StatValues[(string)s["id"]] = Initial(s);
            PendingStats = new List<string>();
            PendingUnlocks = new List<string>();
            PendingCloud = new List<string>();
        }

        /// <summary>What the state file holds (and what the golden steps compare).</summary>
        public Dictionary<string, object> State()
        {
            return new Dictionary<string, object>
            {
                { "format", FORMAT }, { "version", (double)STATE_VERSION }, { "unlocked", Unlocked.Cast<object>().ToList() },
                { "stats", new Dictionary<string, object>(StatValues) },
                { "pending", new Dictionary<string, object>
                    {
                        { "stats", _stats.Select(s => (string)s["id"]).Where(PendingStats.Contains).Cast<object>().ToList() },
                        { "unlocks", PendingUnlocks.Cast<object>().ToList() }, { "cloud", PendingCloud.Cast<object>().ToList() },
                    }
                },
            };
        }

        /// <summary>Takes over a loaded state (StateLoad's), e.g. at start.</summary>
        public void Restore(Dictionary<string, object> st)
        {
            var pending = (Dictionary<string, object>)st["pending"];
            Unlocked = ((List<object>)st["unlocked"]).Cast<string>().ToList();
            foreach (var kv in (Dictionary<string, object>)st["stats"]) StatValues[kv.Key] = kv.Value;
            PendingStats = ((List<object>)pending["stats"]).Cast<string>().ToList();
            PendingUnlocks = ((List<object>)pending["unlocks"]).Cast<string>().ToList();
            PendingCloud = ((List<object>)pending["cloud"]).Cast<string>().ToList();
        }

        /// <summary>The presence map as [[key, value], ...], keys sorted.</summary>
        public List<object> PresenceList()
        {
            return Presence.Select(p => (object)new List<object> { p.Key, p.Value }).ToList();
        }

        private bool Send(params object[] call)
        {
            var list = call.ToList();
            _sent.Add(list);
            return Backend.Send(list);
        }

        private PlatformOut Done(string outWord)
        {
            var r = new PlatformOut { Out = outWord, Calls = _sent };
            _sent = new List<object>();
            return r;
        }

        private void UnlockLocal(string id)
        {
            Unlocked.Add(id);
            PendingUnlocks.Add(id);
        }

        public PlatformOut Unlock(string id)
        {
            if (!HasAchievement(id)) return Done("unknown");
            if (Unlocked.Contains(id)) return Done("already");
            UnlockLocal(id);
            if (Online) FlushInner();
            return Done("unlocked");
        }

        private bool Check(string sid, double old, double now, bool notify)
        {
            bool did = false;
            foreach (var a in _ach)
            {
                string id = (string)a["id"];
                if (!(a["stat"] is string st) || st != sid || Unlocked.Contains(id)) continue;
                if (now >= N(a["threshold"]))
                {
                    UnlockLocal(id);
                    did = true;
                }
                else if (notify && Online && a["progress_every"] != null)
                {
                    double step = N(a["progress_every"]);
                    if (Math.Floor(now / step) > Math.Floor(old / step)) Send("indicate_progress", id, now, a["threshold"]);
                }
            }
            return did;
        }

        /// <summary>v may be anything a caller (or a JSON file) passes: a non-number is refused, never coerced.</summary>
        public PlatformOut SetStat(string id, object v)
        {
            var s = StatDef(id);
            if (s == null) return Done("unknown");
            if (!OkFor((string)s["type"], v)) return Done("refused");
            double c = Clamp(s, N(v));
            double old = N(StatValues[id]);
            if ((bool)s["increment_only"] && c < old) return Done("refused");
            if (c == old) return Done("same");
            StatValues[id] = c;
            if (!PendingStats.Contains(id)) PendingStats.Add(id);
            if (Check(id, old, c, true) && Online) FlushInner();
            return Done(c != N(v) ? "clamped" : "ok");
        }

        public PlatformOut AddStat(string id, object d)
        {
            var s = StatDef(id);
            if (s == null) return Done("unknown");
            if (!OkFor((string)s["type"], d)) return Done("refused");
            return SetStat(id, N(StatValues[id]) + N(d));
        }

        private string FlushInner()
        {
            if (!Online) return "offline";
            if (PendingStats.Count == 0 && PendingUnlocks.Count == 0 && PendingCloud.Count == 0) return "nothing";
            if (PendingStats.Count > 0 || PendingUnlocks.Count > 0)
            {
                foreach (var s in _stats)
                {
                    string id = (string)s["id"];
                    if (PendingStats.Contains(id)) Send("set_stat", id, StatValues[id]);
                }
                foreach (string id in PendingUnlocks) Send("set_achievement", id);
                if (!Send("store_stats"))
                {
                    Online = false;   // the store said no: keep everything, wait for Connect()
                    return "failed";
                }
                PendingStats = new List<string>();
                PendingUnlocks = new List<string>();
            }
            foreach (string p in PendingCloud) Send("cloud_write", p);
            PendingCloud = new List<string>();
            return "sent";
        }

        public PlatformOut Flush() => Done(FlushInner());

        public PlatformOut SetPresence(object key, object value)
        {
            if (!IdOk(key) || !(value is string v) || Encoding.UTF8.GetByteCount(v) > PRESENCE_MAX_VALUE_BYTES) return Done("refused");
            string k = (string)key;
            if (v.Length == 0)
            {
                if (!Presence.Remove(k)) return Done("same");
            }
            else
            {
                if (Presence.TryGetValue(k, out string old) && old == v) return Done("same");
                if (!Presence.ContainsKey(k) && Presence.Count >= PRESENCE_MAX_KEYS) return Done("refused");
                Presence[k] = v;
            }
            if (Online) Send("set_presence", k, v);
            return Done("ok");
        }

        public PlatformOut ClearPresence()
        {
            if (Presence.Count == 0) return Done("same");
            Presence.Clear();
            if (Online) Send("clear_presence");
            return Done("ok");
        }

        /// <summary>The save code calls this after its atomic write succeeded; path is relative to the data folder.</summary>
        public PlatformOut Saved(string path)
        {
            string part = CloudPartition(path);
            if (part == "cloud" && Cloud == "api")
            {
                if (Online) Send("cloud_write", path);
                else if (!PendingCloud.Contains(path)) PendingCloud.Add(path);
            }
            return Done(part);
        }

        public PlatformOut Connect(Dictionary<string, object> remote)
        {
            Online = true;
            if (Get(remote, "unlocked", null) is List<object> ru)
            {
                foreach (object o in ru)
                {
                    if (!(o is string id)) continue;
                    if (HasAchievement(id) && !Unlocked.Contains(id)) Unlocked.Add(id);
                    PendingUnlocks.Remove(id);
                }
            }
            var rs = Get(remote, "stats", null) as Dictionary<string, object> ?? new Dictionary<string, object>();
            foreach (var s in _stats)
            {
                string sid = (string)s["id"];
                object r0 = Get(rs, sid, null);
                if (!OkFor((string)s["type"], r0)) continue;
                double r = Clamp(s, N(r0));
                double old = N(StatValues[sid]);
                bool pend = PendingStats.Contains(sid);
                double now;
                if ((bool)s["increment_only"])
                {
                    if (r >= old && pend) PendingStats.Remove(sid);
                    now = Math.Max(old, r);
                }
                else
                {
                    now = pend ? old : r;
                }
                StatValues[sid] = now;
                Check(sid, old, now, false);
            }
            FlushInner();
            if (Online)
            {
                foreach (var kv in Presence.ToList()) Send("set_presence", kv.Key, kv.Value);
            }
            return Done(Online ? "online" : "failed");
        }

        public PlatformOut Disconnect()
        {
            Online = false;
            return Done("offline");
        }

        /// <summary>A store the backend accepted failed later: the same as a refused store_stats. The batch's stats
        /// and unlocks are pending again and the layer is offline until Connect().</summary>
        public PlatformOut StoreFailed(List<object> batch)
        {
            Online = false;
            foreach (object o in batch)
            {
                var call = (List<object>)o;
                string id = (string)call[1];
                if ((string)call[0] == "set_stat" && StatDef(id) != null && !PendingStats.Contains(id)) PendingStats.Add(id);
                else if ((string)call[0] == "set_achievement" && Unlocked.Contains(id) && !PendingUnlocks.Contains(id)) PendingUnlocks.Add(id);
            }
            return Done("failed");
        }

        /// <summary>Testing only: refused offline (a reset is never queued).</summary>
        public PlatformOut ResetAll()
        {
            if (!Online) return Done("offline");
            ResetLocal();
            Send("reset_all_stats", true);
            return Done("reset");
        }

        /// <summary>platform_state.json text (null or "" = no file) -> the state; problems counts dropped entries.</summary>
        public static Dictionary<string, object> StateLoad(Dictionary<string, object> defs, string text, out int problems)
        {
            var p = new PlatformRules(defs);
            problems = 0;
            if (string.IsNullOrEmpty(text)) return p.State();
            if (!Json.TryParse(text, out object parsed) || !(parsed is Dictionary<string, object> raw)
                || !(Get(raw, "format", null) is string f) || f != FORMAT || !Whole(Get(raw, "version", null)) || N(raw["version"]) != STATE_VERSION)
            {
                problems = 1;
                return p.State();
            }
            int bad = 0;
            List<object> L(object v)
            {
                if (v is List<object> l) return l;
                if (v != null) bad++;
                return new List<object>();
            }
            Dictionary<string, object> D(object v)
            {
                if (v is Dictionary<string, object> d) return d;
                if (v != null) bad++;
                return new Dictionary<string, object>();
            }
            foreach (object o in L(Get(raw, "unlocked", null)))
            {
                if (o is string id && p.HasAchievement(id) && !p.Unlocked.Contains(id)) p.Unlocked.Add(id);
                else bad++;
            }
            foreach (var kv in D(Get(raw, "stats", null)))
            {
                var s = p.StatDef(kv.Key);
                if (s == null || !OkFor((string)s["type"], kv.Value))
                {
                    bad++;
                    continue;
                }
                p.StatValues[kv.Key] = Clamp(s, N(kv.Value));
            }
            var pending = D(Get(raw, "pending", null));
            foreach (object o in L(Get(pending, "stats", null)))
            {
                if (o is string id && p.StatDef(id) != null && !p.PendingStats.Contains(id)) p.PendingStats.Add(id);
                else bad++;
            }
            foreach (object o in L(Get(pending, "unlocks", null)))
            {
                if (o is string id && p.Unlocked.Contains(id) && !p.PendingUnlocks.Contains(id)) p.PendingUnlocks.Add(id);
                else bad++;
            }
            foreach (object o in L(Get(pending, "cloud", null)))
            {
                if (o is string path && CloudPartition(path) == "cloud" && !p.PendingCloud.Contains(path)) p.PendingCloud.Add(path);
                else bad++;
            }
            problems = bad;
            return p.State();
        }
    }

    /// <summary>The rules, the backend and the cached state file: what the shell owns (Shell.Instance.Platform).</summary>
    public sealed class PlatformService
    {
        public readonly PlatformRules Rules;
        public readonly IPlatformBackend Backend;
        /// <summary>False without data/achievements.json (or with an empty one): nothing is ever written.</summary>
        public readonly bool Active;
        /// <summary>Problems found while loading (the shell logs them).</summary>
        public readonly List<string> Problems = new List<string>();
        private readonly string _file;
        private string _last = "";

        /// <param name="achievementsText">data/achievements.json (null = none).</param>
        /// <param name="backend">null = a NullPlatformBackend.</param>
        public PlatformService(string dataFolder, string achievementsText, IPlatformBackend backend = null, string cloud = PlatformRules.CLOUD_MODE)
        {
            _file = Path.Combine(dataFolder, PlatformRules.STATE_FILE);
            Backend = backend ?? new NullPlatformBackend();
            var defs = PlatformRules.AchievementsLoad(achievementsText, out int problems);
            if (problems > 0) Problems.Add($"data/achievements.json: {problems} problem(s), those entries were dropped");
            Active = ((List<object>)defs["stats"]).Count > 0 || ((List<object>)defs["achievements"]).Count > 0;
            Rules = new PlatformRules(defs, Backend, false, cloud);
            if (Active)
            {
                string text = AtomicFile.ReadOrNull(_file);
                var st = PlatformRules.StateLoad(defs, text, out int n);
                if (n > 0) Problems.Add($"{PlatformRules.STATE_FILE}: {n} problem(s), the store's copy wins");
                Rules.Restore(st);
                _last = text ?? "";
            }
            if (Backend.Available()) Rules.Connect(Backend.Remote());
            Persist();
        }

        private void Persist()
        {
            if (!Active) return;
            string text = Json.Stringify(Rules.State(), 1) + "\n";
            if (text == _last) return;
            try
            {
                AtomicFile.Write(_file, text, false);
                _last = text;
            }
            catch (Exception e)
            {
                Problems.Add($"{PlatformRules.STATE_FILE} not written: {e.Message}");
            }
        }

        private string After(PlatformOut r)
        {
            Persist();
            return r.Out as string;
        }

        public string Unlock(string id) => After(Rules.Unlock(id));
        public string SetStat(string id, double v) => After(Rules.SetStat(id, v));
        public string AddStat(string id, double d) => After(Rules.AddStat(id, d));
        /// <summary>At checkpoints: level end, pause, quit.</summary>
        public string Flush() => After(Rules.Flush());
        public string SetPresence(string key, string value) => After(Rules.SetPresence(key, value));
        public string ClearPresence() => After(Rules.ClearPresence());
        /// <summary>After an atomic save: its cloud partition (and, in api mode, the cloud write or its queue).</summary>
        public string Saved(string path) => After(Rules.Saved(path));
        /// <summary>The store overlay opened or closed over screen: "pause" means open the pause menu.</summary>
        public string Overlay(bool active, string screen) => PlatformRules.OverlayAction(active, screen);
        /// <summary>Each frame: the backend's callbacks; true/false when the store overlay opened/closed.</summary>
        public bool? Update()
        {
            bool? overlay = Backend.Update();
            for (List<object> batch = Backend.TakeStoreFailure(); batch != null; batch = Backend.TakeStoreFailure())
            {
                Problems.Add("a store the backend accepted failed later: kept for the next connect");
                After(Rules.StoreFailed(batch));
            }
            return overlay;
        }
    }
}
