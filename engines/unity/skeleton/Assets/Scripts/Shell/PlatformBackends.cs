// ---------------------------------------------------------------------------
// PlatformBackends.cs
// Purpose : Picks the platform layer's backend for this build (docs/PLATFORM.md): the null backend, which every
//           game runs by default, or the one a store assembly registered in Factory.
// Usage   : Shell.StartPlatform: new PlatformService(DataDir, text, PlatformBackends.Make(Smoke, defs, DataDir))
//           Assets/Scripts/Steam/SteamworksCalls.cs sets Factory when the project defines GAMEKIT_STEAM
// Notes   : null means "the null backend" (PlatformService makes one). A smoke run never asks a store. The Steam
//           assembly (Game.Steam) has the define constraint GAMEKIT_STEAM, so without the define Unity does not
//           compile it and Factory stays null.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): Make goes through Core's PlatformStart (the start rule)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class PlatformBackends
    {
        /// <summary>(defs, data folder) -> a store backend, or null when the store did not start. Set by a store
        /// assembly before the shell boots (RuntimeInitializeOnLoadMethod, BeforeSceneLoad).</summary>
        public static Func<Dictionary<string, object>, string, IPlatformBackend> Factory;

        /// <summary>The store backend, or null for the null backend.</summary>
        public static IPlatformBackend Make(bool smoke, Dictionary<string, object> defs, string dataFolder)
        {
            return PlatformStart.Make(smoke, defs, dataFolder, Factory);
        }
    }
}

// {{FOOTER}}
