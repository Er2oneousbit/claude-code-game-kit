// ---------------------------------------------------------------------------
// GhostBrain.cs
// Purpose : The ghosts' finite state machine (ADR 0003): patrol, suspicious, hunt, search, return.
//           Engine-free: perception comes in, an order (where to go, how fast) goes out.
// Usage   : var brain = new GhostBrain(tuning);
//           each frame: GhostOrder o = brain.Tick(dt, seesKeeper, keeperPos, ghostPos, out bool changed);
//           then a NavMeshAgent drives to o.Destination at o.Speed (GhostAgent.cs).
// Notes   : Fairness on purpose (SOP-14): every hunt starts with a "?" pause, and a hunted keeper can
//           still escape by breaking line of sight for LoseSightSeconds.
//
// Pseudocode:
//   Patrol      : next waypoint at patrol speed          ; sees -> Suspicious
//   Suspicious  : stop, face the keeper                  ; after SuspiciousSeconds: sees -> Hunt, else -> Search
//   Hunt        : chase the keeper at hunt speed         ; unseen LoseSightSeconds -> Search
//                 HuntMaxSeconds -> tired: Return, and ignore the keeper for TiredSeconds
//   Search      : go to the last seen spot, look around   ; sees -> Suspicious ; SearchSeconds there -> Return
//                 SearchMaxSeconds in all (the spot may be off the NavMesh) -> Return
//   Return      : back to the patrol route               ; sees -> Suspicious ; arrived -> Patrol
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): Search ends after SearchMaxSeconds even when the last seen
//           spot cannot be reached (it searched a doorway forever); CanCatch: a tired ghost never catches.
// ---------------------------------------------------------------------------
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public enum GhostState { Patrol, Suspicious, Hunt, Search, Return }

    public struct GhostOrder
    {
        public V2 Destination;
        public float Speed;          // 0 = stand still
        public bool FaceKeeper;      // turn toward the keeper in place
    }

    public sealed class GhostBrain
    {
        public const float Arrive = 0.8f;   // m: a destination counts as reached

        private readonly GameTuning _t;
        private readonly IReadOnlyList<V2> _route;
        private int _waypoint;
        private float _unseen;
        private float _tired;        // s left during which a tired ghost ignores the keeper
        private float _searching;    // s in this Search, walk to the spot included

        public GhostState State { get; private set; } = GhostState.Patrol;
        public float StateTime { get; private set; }
        public V2 LastSeen { get; private set; }

        public GhostBrain(GameTuning tuning, IReadOnlyList<V2> route, int startWaypoint = 0)
        {
            _t = tuning;
            _route = route;
            _waypoint = startWaypoint % route.Count;
        }

        public V2 CurrentWaypoint => _route[_waypoint];

        // One frame of thinking. `changed` is true when the state changed (for sounds and logs).
        public GhostOrder Tick(float dt, bool sees, V2 keeper, V2 ghost, out bool changed)
        {
            GhostState before = State;
            StateTime += dt;
            _tired = System.Math.Max(0f, _tired - dt);
            if (_tired > 0f) sees = false;   // tired: it does not notice the keeper for a while
            if (sees) LastSeen = keeper;

            switch (State)
            {
                case GhostState.Patrol:
                    if (sees) { Go(GhostState.Suspicious); break; }
                    if (V2.Distance(ghost, _route[_waypoint]) < Arrive) _waypoint = (_waypoint + 1) % _route.Count;
                    break;
                case GhostState.Suspicious:
                    if (StateTime >= _t.SuspiciousSeconds) Go(sees ? GhostState.Hunt : GhostState.Search);
                    break;
                case GhostState.Hunt:
                    _unseen = sees ? 0f : _unseen + dt;
                    if (StateTime >= _t.HuntMaxSeconds)
                    {
                        _tired = _t.TiredSeconds;   // gave up: back to the route, blind to the keeper for a while
                        Go(GhostState.Return);
                    }
                    else if (_unseen >= _t.LoseSightSeconds) Go(GhostState.Search);
                    break;
                case GhostState.Search:
                    if (sees) { Go(GhostState.Suspicious); break; }
                    _searching += dt;
                    if (_searching >= _t.SearchMaxSeconds) { Go(GhostState.Return); break; }
                    // The search clock only counts once it reached the last seen spot
                    if (V2.Distance(ghost, LastSeen) > Arrive * 2f) StateTime = 0f;
                    else if (StateTime >= _t.SearchSeconds) Go(GhostState.Return);
                    break;
                case GhostState.Return:
                    if (sees) { Go(GhostState.Suspicious); break; }
                    if (V2.Distance(ghost, _route[_waypoint]) < Arrive) Go(GhostState.Patrol);
                    break;
            }
            changed = State != before;
            return Order(ghost);
        }

        public bool Tired => _tired > 0f;

        // A touch is a catch unless the ghost is tired: it gave up, or it just caught the keeper
        public bool CanCatch(V2 ghost, V2 keeper) => !Tired && V2.Distance(ghost, keeper) < _t.CatchRadius;

        // After a catch: back to the route, ignoring the keeper for TiredSeconds (no catch right at the gate)
        public void Tire()
        {
            _tired = _t.TiredSeconds;
            Go(GhostState.Return);
        }

        private void Go(GhostState next)
        {
            State = next;
            StateTime = 0f;
            _unseen = 0f;
            _searching = 0f;
            if (next == GhostState.Return) _waypoint = Nearest();
        }

        private GhostOrder Order(V2 ghost)
        {
            switch (State)
            {
                case GhostState.Suspicious: return new GhostOrder { Destination = ghost, Speed = 0f, FaceKeeper = true };
                case GhostState.Hunt: return new GhostOrder { Destination = LastSeen, Speed = _t.HuntSpeed };
                case GhostState.Search: return new GhostOrder { Destination = LastSeen, Speed = _t.PatrolSpeed * 1.4f };
                default: return new GhostOrder { Destination = _route[_waypoint], Speed = _t.PatrolSpeed };
            }
        }

        private int Nearest()
        {
            // The route point closest to the last seen spot: where the ghost is when it gives up
            int best = 0;
            for (int i = 1; i < _route.Count; i++)
            {
                if (V2.Distance(_route[i], LastSeen) < V2.Distance(_route[best], LastSeen)) best = i;
            }
            return best;
        }
    }
}
