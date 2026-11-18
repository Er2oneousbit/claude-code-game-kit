// ---------------------------------------------------------------------------
// PlatformBackends.cs
// Purpose : Picks the platform layer's backend for this build (docs/PLATFORM.md): the null backend, which every
//           game runs by default.
// Usage   : Shell.StartPlatform: new PlatformService(DataDir, text, PlatformBackends.Make(Smoke))
// Notes   : null means "the null backend" (PlatformService makes one). A smoke run never asks a store.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class PlatformBackends
    {
        /// <summary>The store backend, or null for the null backend.</summary>
        public static IPlatformBackend Make(bool smoke)
        {
            return null;
        }
    }
}

// {{FOOTER}}
