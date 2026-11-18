// ---------------------------------------------------------------------------
// SteamworksCalls.cs
// Purpose : ISteamCalls on Steamworks.NET (MIT, rlabrecque), and the factory that gives the shell a Steam backend
//           (docs/PLATFORM.md). Compiled only when the project defines GAMEKIT_STEAM (Game.Steam.asmdef's define
//           constraint) and Steamworks.NET is installed (its assembly com.rlabrecque.steamworks.net).
// Usage   : Project Settings > Player > Scripting Define Symbols: GAMEKIT_STEAM; install Steamworks.NET (its UPM git
//           URL or .unitypackage); put steam_appid.txt (480 while testing) next to the editor / dev build only.
// Notes   : Calls follow Steamworks.NET's names (SteamAPI.Init, SteamUserStats.SetAchievement / GetAchievement /
//           SetStat / GetStat / StoreStats / IndicateAchievementProgress / ResetAllStats,
//           SteamFriends.SetRichPresence / ClearRichPresence, SteamRemoteStorage.FileWrite, SteamAPI.RunCallbacks,
//           Callback<GameOverlayActivated_t>) (verify against the installed version; not compiled on the kit's test
//           machine, which has no Steamworks.NET). A smoke run never starts Steam.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using Steamworks;
using UnityEngine;
using {{GAME_SLUG}}.Core;
using {{GAME_SLUG}}.Shell;

namespace {{GAME_SLUG}}.Steam
{
    public sealed class SteamworksCalls : ISteamCalls
    {
        public event Action<bool> OverlayChanged;
        private readonly Callback<GameOverlayActivated_t> _overlay;

        private SteamworksCalls()
        {
            _overlay = Callback<GameOverlayActivated_t>.Create(e => OverlayChanged?.Invoke(e.m_bActive != 0));
        }

        /// <summary>Registers the factory before the first scene loads, so Shell.StartPlatform finds it.</summary>
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Register()
        {
            PlatformBackends.Factory = (defs, folder) =>
            {
                if (!SteamAPI.Init())
                {
                    Debug.LogWarning("[WARN][platform] built with Steam, but Steam did not start: the null backend runs");
                    return null;
                }
                Application.quitting += SteamAPI.Shutdown;
                return new SteamPlatformBackend(defs, folder, new SteamworksCalls());
            };
        }

        public bool SetAchievement(string id) => SteamUserStats.SetAchievement(id);
        public bool GetAchievement(string id, out bool achieved) => SteamUserStats.GetAchievement(id, out achieved);
        public bool SetStat(string id, int value) => SteamUserStats.SetStat(id, value);
        public bool SetStat(string id, float value) => SteamUserStats.SetStat(id, value);
        public bool GetStat(string id, out int value) => SteamUserStats.GetStat(id, out value);
        public bool GetStat(string id, out float value) => SteamUserStats.GetStat(id, out value);
        public bool StoreStats() => SteamUserStats.StoreStats();
        public bool IndicateAchievementProgress(string id, uint current, uint max) => SteamUserStats.IndicateAchievementProgress(id, current, max);
        public bool ResetAllStats(bool achievementsToo) => SteamUserStats.ResetAllStats(achievementsToo);
        public bool SetRichPresence(string key, string value) => SteamFriends.SetRichPresence(key, value);
        public void ClearRichPresence() => SteamFriends.ClearRichPresence();
        public bool FileWrite(string name, byte[] data) => SteamRemoteStorage.FileWrite(name, data, data.Length);
        public void RunCallbacks() => SteamAPI.RunCallbacks();
    }
}

// {{FOOTER}}
