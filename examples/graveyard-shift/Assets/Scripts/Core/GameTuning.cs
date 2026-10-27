// ---------------------------------------------------------------------------
// GameTuning.cs
// Purpose : Every number that defines how Graveyard Shift plays, in one place (GDD "Tunables").
// Usage   : new GameTuning() gives the defaults; the game reads them from the GraveyardConfig
//           ScriptableObject (Assets/Config), which holds one of these and shows it in the Inspector.
// Notes   : Plain C# so EditMode tests use the same defaults. Meters, seconds, degrees.
//           After a change run `python tools/dev.py test` (rules) and `smoke` (the bot trio: the careful
//           keeper must win, the always-lit one get caught, the always-dark one run out of night).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): CatchGraceSeconds (no catch cascade at the start) and
//           SearchMaxSeconds (a search for a spot no ghost can reach ends).
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    [Serializable]
    public class GameTuning
    {
        // The night
        public float NightSeconds = 300f;       // until dawn (the 4x yard: 150 s on the old one)
        public float LowTimeSeconds = 40f;      // the HUD warns

        // The keeper
        public float LitSpeed = 4.2f;           // m/s with the lantern lit
        public float DarkSpeed = 2.4f;          // m/s in the dark: stumbling between graves
        public float SoulPickupRadius = 1.4f;
        // The escape: within this of the gate point (1 m inside the wall line), once the gate is fully open. Under the
        // 2 m from the gate to the start, so the start is not an escape and LevelCheck's gate check means something
        // (Kimi audit: at 2.2 m a keeper escaped 3 m inside the wall while the leaves were still swinging).
        public float GateRadius = 1.2f;

        // Ghost perception: the lantern decides how far they see you (pillar 1: see and be seen)
        public float SightLit = 9f;            // m, inside the cone, lantern lit
        public float SightDark = 4f;            // m, inside the cone, in the dark
        public float SenseLit = 3.5f;             // m, all around (they feel the light)
        public float SenseDark = 1.5f;          // m, all around
        public float ConeHalfAngle = 60f;       // degrees

        // Ghost behavior (finite state machine, ADR 0003)
        public float PatrolSpeed = 2.0f;
        public float HuntSpeed = 4.6f;          // faster than a lit keeper: once hunted, break line of sight
        public float SuspiciousSeconds = 1.2f;  // the "?" before a hunt: the keeper's chance to vanish
        public float HuntMaxSeconds = 6f;       // ghosts tire: after a hunt this long they go back to their route...
        public float TiredSeconds = 5f;         // ...and ignore the keeper this long (outrun them with the light)
        public float LoseSightSeconds = 1.4f;   // unseen this long while hunting: search (an escape must be possible)
        public float SearchSeconds = 3.5f;
        public float SearchMaxSeconds = 12f;    // a whole search, walk included: a last seen spot off the NavMesh ends it
        public float CatchRadius = 1.0f;
        public float CatchGraceSeconds = 1.5f;  // after a catch, touches are ignored this long (the keeper wakes at the start)
    }
}
