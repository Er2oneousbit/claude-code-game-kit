// ---------------------------------------------------------------------------
// Difficulty.cs
// Purpose : The four difficulties: how dark the night is and how many extra ghosts walk the yard. Easy is the
//           lighting the game always had; each step darker, and Insane is black outside the lantern's light.
// Usage   : var d = DifficultySettings.For(Difficulty.Hard);  d.ExtraGhosts, d.AmbientScale, ...
//           Difficulty parsed = DifficultySettings.Parse("insane");   // the command line and the save
// Notes   : Engine-free numbers (scales and flags); LevelBuilder, GhostAgent and KeeperController apply them.
//           Difficulty never changes the yard or its fairness checks: extra ghosts share the yard's checked
//           loops (GraveyardGame), and darkness only changes what a person can see. The ghosts' rules (sight in
//           meters, GameTuning) are the same at every level, so the bot trio measures the same game.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
namespace graveyard_shift.Core
{
    public enum Difficulty { Easy, Normal, Hard, Insane }

    public sealed class DifficultySettings
    {
        public Difficulty Level;
        public string Blurb;              // one line on the title screen
        public int ExtraGhosts;           // on top of one per patrol loop
        public float AmbientScale;        // of the night's ambient light
        public float MoonScale;           // of the moon's intensity
        public float FogDensity;
        public float SoulLightScale;      // range of each soul's own light (0: none)
        public bool SoulGlows;            // the orb itself glows (off: find souls by their whispers)
        public float GhostLightScale;     // range of the light each ghost casts (its body still shows its state)
        public float DarkGlowScale;       // the keeper's faint glow with the lantern out (0: black)
        public bool GateLamps;            // the two lamps by the gate and the light above it

        private static readonly DifficultySettings[] All =
        {
            new DifficultySettings
            {
                Level = Difficulty.Easy, Blurb = "Moonlit. The yard as it always was.", ExtraGhosts = 0,
                AmbientScale = 1f, MoonScale = 1f, FogDensity = 0.035f, SoulLightScale = 1f, SoulGlows = true,
                GhostLightScale = 1f, DarkGlowScale = 1f, GateLamps = true,
            },
            new DifficultySettings
            {
                Level = Difficulty.Normal, Blurb = "A darker night, two more ghosts.", ExtraGhosts = 2,
                AmbientScale = 0.45f, MoonScale = 0.4f, FogDensity = 0.045f, SoulLightScale = 1f, SoulGlows = true,
                GhostLightScale = 0.8f, DarkGlowScale = 0.8f, GateLamps = true,
            },
            new DifficultySettings
            {
                Level = Difficulty.Hard, Blurb = "Barely a moon, four more ghosts.", ExtraGhosts = 4,
                AmbientScale = 0.15f, MoonScale = 0.12f, FogDensity = 0.06f, SoulLightScale = 0.6f, SoulGlows = true,
                GhostLightScale = 0.6f, DarkGlowScale = 0.5f, GateLamps = true,
            },
            new DifficultySettings
            {
                Level = Difficulty.Insane, Blurb = "Pitch black outside your lantern. Six more ghosts. Listen for the souls.",
                ExtraGhosts = 6, AmbientScale = 0f, MoonScale = 0f, FogDensity = 0.08f, SoulLightScale = 0f,
                SoulGlows = false, GhostLightScale = 0f, DarkGlowScale = 0f, GateLamps = false,
            },
        };

        public static DifficultySettings For(Difficulty d) => All[(int)d];

        // "easy", "Normal", "HARD", "insane"; anything else is Normal
        public static Difficulty Parse(string name)
        {
            foreach (var s in All)
                if (string.Equals(s.Level.ToString(), name?.Trim(), System.StringComparison.OrdinalIgnoreCase)) return s.Level;
            return Difficulty.Normal;
        }
    }
}
