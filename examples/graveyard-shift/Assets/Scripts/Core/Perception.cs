// ---------------------------------------------------------------------------
// Perception.cs
// Purpose : Can a ghost see the keeper? Range and cone depend on the lantern (pillar 1: light is a
//           choice). Line of sight is passed in, so Unity does the raycast and this stays testable.
// Usage   : bool seen = Perception.Sees(t, ghostPos, ghostForward, keeperPos, lanternLit, lineOfSight);
// Notes   : Two zones: the cone (long, in front) and a short all-around "sense" radius, so walking into
//           a ghost's back is not free. Cover blocks both (lineOfSight false).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
namespace graveyard_shift.Core
{
    public static class Perception
    {
        public static float SightRange(GameTuning t, bool lit) => lit ? t.SightLit : t.SightDark;
        public static float SenseRange(GameTuning t, bool lit) => lit ? t.SenseLit : t.SenseDark;

        public static bool Sees(GameTuning t, V2 ghost, V2 forward, V2 keeper, bool lit, bool lineOfSight)
        {
            if (!lineOfSight) return false;
            V2 to = keeper - ghost;
            float d = to.Length;
            if (d <= SenseRange(t, lit)) return true;
            if (d > SightRange(t, lit)) return false;
            return V2.AngleBetween(forward, to) <= t.ConeHalfAngle;
        }
    }
}
