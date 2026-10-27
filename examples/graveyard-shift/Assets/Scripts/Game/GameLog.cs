// ---------------------------------------------------------------------------
// GameLog.cs
// Purpose : The small Log wrapper the Unity ENGINE.md asks for: channels and levels, no stray
//           Debug.Log calls. The INFO lines double as markers for `dev.py smoke --until/--fail-on`.
// Usage   : GameLog.Info("game", "ESCAPED time=93"); GameLog.Warn("save", "...");
// Notes   : Error logs fail Unity Test Framework tests, so Error is reserved for real bugs.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEngine;

namespace graveyard_shift.Game
{
    public static class GameLog
    {
        public static bool DebugEnabled;

        public static void Debug(string channel, string msg)
        {
            if (DebugEnabled) UnityEngine.Debug.Log($"[DEBUG][{channel}] {msg}");
        }

        public static void Info(string channel, string msg) => UnityEngine.Debug.Log($"[INFO][{channel}] {msg}");
        public static void Warn(string channel, string msg) => UnityEngine.Debug.LogWarning($"[WARN][{channel}] {msg}");
        public static void Error(string channel, string msg) => UnityEngine.Debug.LogError($"[ERROR][{channel}] {msg}");
    }
}
