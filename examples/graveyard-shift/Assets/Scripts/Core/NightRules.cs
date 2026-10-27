// ---------------------------------------------------------------------------
// NightRules.cs
// Purpose : The rules of one night: the clock to dawn, souls collected, the gate, getting caught, the outcome.
// Usage   : var night = new NightRules(tuning, soulCount);
//           each frame: night.Tick(dt, keeperPos, soulPositions, gatePos, caught) -> events
// Notes   : Engine-free. The clock starts on the first move (reading the ghosts first is free) and the
//           gate only lets you out with every soul. Caught costs time, not the night: the keeper wakes at
//           the gate and the last soul collected slips back to its grave (with every soul in hand, that shuts the
//           open gate again: GateShut; collecting it again opens it: AllSouls). Dawn is the only way to lose.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): a catch starts CatchGraceSeconds of grace during which
//           touches are ignored (a ghost near the start caught the respawned keeper every frame: 35 in a second).
// ---------------------------------------------------------------------------
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public enum Outcome { Playing, Escaped, Dawn }
    public enum NightEvent { Started, SoulCollected, AllSouls, LowTime, Escaped, Caught, Dawn, GateShut }

    public sealed class NightRules
    {
        private readonly GameTuning _t;
        private readonly bool[] _collected;
        private bool _lowTimeSent;
        private readonly List<int> _order = new List<int>();   // souls in the order collected
        private float _grace;                                   // s left in which a touch is not a catch

        public Outcome Outcome { get; private set; } = Outcome.Playing;
        public bool Started { get; private set; }
        public float Elapsed { get; private set; }
        public float TimeLeft => _t.NightSeconds - Elapsed;
        public int Collected { get; private set; }
        public int Catches { get; private set; }
        public int LastLostSoul { get; private set; } = -1;    // the soul that slipped back on the last catch
        public int SoulCount => _collected.Length;
        public bool AllCollected => Collected == _collected.Length;
        public bool InGrace => _grace > 0f;                    // just caught: ghosts cannot catch again yet
        public bool IsCollected(int i) => _collected[i];

        public NightRules(GameTuning tuning, int soulCount)
        {
            _t = tuning;
            _collected = new bool[soulCount];
        }

        // gateOpen: the gate has finished opening (GateSwing.IsOpen); every soul and an open gate let you out
        public List<NightEvent> Tick(float dt, bool moved, V2 keeper, IReadOnlyList<V2> souls, V2 gate, bool caught,
                                     bool gateOpen = true)
        {
            var events = new List<NightEvent>();
            if (Outcome != Outcome.Playing) return events;
            if (!Started && moved)
            {
                Started = true;
                events.Add(NightEvent.Started);
            }
            if (Started) Elapsed += dt;
            _grace = System.Math.Max(0f, _grace - dt);
            if (_grace > 0f) caught = false;   // the respawned keeper is not caught again on the spot

            for (int i = 0; i < souls.Count; i++)
            {
                if (_collected[i] || V2.Distance(keeper, souls[i]) > _t.SoulPickupRadius) continue;
                _collected[i] = true;
                _order.Add(i);
                Collected++;
                events.Add(NightEvent.SoulCollected);
                if (AllCollected) events.Add(NightEvent.AllSouls);
            }

            if (caught)
            {
                Catches++;
                _grace = _t.CatchGraceSeconds;
                LastLostSoul = -1;
                bool wasOpen = AllCollected;
                if (_order.Count > 0)
                {
                    LastLostSoul = _order[_order.Count - 1];
                    _order.RemoveAt(_order.Count - 1);
                    _collected[LastLostSoul] = false;
                    Collected--;
                }
                events.Add(NightEvent.Caught);   // the game moves the keeper back to the gate
                if (wasOpen && !AllCollected) events.Add(NightEvent.GateShut);
            }
            else if (AllCollected && gateOpen && V2.Distance(keeper, gate) <= _t.GateRadius)
            {
                Outcome = Outcome.Escaped;
                events.Add(NightEvent.Escaped);
            }
            else if (Started && TimeLeft <= 0f)
            {
                Outcome = Outcome.Dawn;
                events.Add(NightEvent.Dawn);
            }
            else if (Started && !_lowTimeSent && TimeLeft <= _t.LowTimeSeconds)
            {
                _lowTimeSent = true;
                events.Add(NightEvent.LowTime);
            }
            return events;
        }
    }
}
