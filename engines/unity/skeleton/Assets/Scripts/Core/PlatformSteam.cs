// ---------------------------------------------------------------------------
// PlatformSteam.cs
// Purpose : The Steam backend's mapping for the platform layer (#84, docs/PLATFORM.md): which Steam call each
//           platform call becomes, over the ISteamCalls interface, so EditMode tests run it with a fake. The real
//           ISteamCalls is Assets/Scripts/Steam/SteamworksCalls.cs (Steamworks.NET), compiled only when the project
//           defines GAMEKIT_STEAM.
// Usage   : var backend = new SteamPlatformBackend(defs, dataFolder, calls);   // calls: SteamworksCalls or a fake
// Notes   : No UnityEngine types. Only StoreStats returning false counts as a failed store; a later
//           UserStatsStored_t failure is not seen (verify). The overlay arrives through OverlayChanged (the calls
//           object raises it from Steam's GameOverlayActivated_t callback); Update hands it over once.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;

namespace {{GAME_SLUG}}.Core
{
    /// <summary>The Steam calls the backend needs (ISteamUserStats, ISteamFriends, ISteamRemoteStorage).</summary>
    public interface ISteamCalls
    {
        bool SetAchievement(string id);
        bool GetAchievement(string id, out bool achieved);
        bool SetStat(string id, int value);
        bool SetStat(string id, float value);
        bool GetStat(string id, out int value);
        bool GetStat(string id, out float value);
        bool StoreStats();
        bool IndicateAchievementProgress(string id, uint current, uint max);
        bool ResetAllStats(bool achievementsToo);
        bool SetRichPresence(string key, string value);
        void ClearRichPresence();
        bool FileWrite(string name, byte[] data);
        void RunCallbacks();
        /// <summary>Raised from Steam's overlay callback: true opened, false closed.</summary>
        event Action<bool> OverlayChanged;
    }

    public sealed class SteamPlatformBackend : IPlatformBackend
    {
        private readonly Dictionary<string, object> _defs;
        private readonly string _folder;
        private readonly ISteamCalls _steam;
        private bool? _overlay;

        public SteamPlatformBackend(Dictionary<string, object> defs, string dataFolder, ISteamCalls steam)
        {
            _defs = defs;
            _folder = dataFolder;
            _steam = steam;
            _steam.OverlayChanged += active => _overlay = active;
        }

        public string Name => "steam";
        public bool Available() => true;

        private IEnumerable<Dictionary<string, object>> Items(string key)
        {
            foreach (object o in (List<object>)_defs[key]) yield return (Dictionary<string, object>)o;
        }

        private bool IsInt(string id)
        {
            foreach (var s in Items("stats"))
            {
                if ((string)s["id"] == id) return (string)s["type"] == "int";
            }
            return false;
        }

        public Dictionary<string, object> Remote()
        {
            var unlocked = new List<object>();
            foreach (var a in Items("achievements"))
            {
                if (_steam.GetAchievement((string)a["id"], out bool done) && done) unlocked.Add(a["id"]);
            }
            var stats = new Dictionary<string, object>();
            foreach (var s in Items("stats"))
            {
                string id = (string)s["id"];
                if ((string)s["type"] == "int")
                {
                    if (_steam.GetStat(id, out int i)) stats[id] = (double)i;
                }
                else if (_steam.GetStat(id, out float f))
                {
                    stats[id] = (double)f;
                }
            }
            return new Dictionary<string, object> { { "unlocked", unlocked }, { "stats", stats } };
        }

        public bool Send(List<object> call)
        {
            string name = (string)call[0];
            switch (name)
            {
                case "set_achievement": _steam.SetAchievement((string)call[1]); break;
                case "set_stat":
                    if (IsInt((string)call[1])) _steam.SetStat((string)call[1], (int)Json.ToNumber(call[2]));
                    else _steam.SetStat((string)call[1], (float)Json.ToNumber(call[2]));
                    break;
                case "store_stats": return _steam.StoreStats();
                case "indicate_progress":
                    _steam.IndicateAchievementProgress((string)call[1], (uint)Json.ToNumber(call[2]), (uint)Json.ToNumber(call[3]));
                    break;
                case "reset_all_stats": _steam.ResetAllStats((bool)call[1]); break;
                case "set_presence": _steam.SetRichPresence((string)call[1], (string)call[2]); break;
                case "clear_presence": _steam.ClearRichPresence(); break;
                case "cloud_write":
                    string path = Path.Combine(_folder, (string)call[1]);
                    if (File.Exists(path)) _steam.FileWrite((string)call[1], File.ReadAllBytes(path));
                    break;
            }
            return true;
        }

        public bool? Update()
        {
            _steam.RunCallbacks();
            bool? o = _overlay;
            _overlay = null;
            return o;
        }
    }
}

// {{FOOTER}}
