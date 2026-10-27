// ---------------------------------------------------------------------------
// KeeperBot.cs
// Purpose : Autoplay drivers for the scenario trio (SOP-14 step 6): Careful dims the lantern near
//           ghosts, AlwaysLit never does, AlwaysDark never lights it. Careful must escape, AlwaysLit must
//           be caught (light gets you seen), AlwaysDark must run out of night (darkness has a cost).
// Usage   : var bot = new KeeperBot(BotMode.Careful); each frame bot.Think(game) -> bot.Direction, bot.Lantern
// Notes   : All three share one movement brain (wait for a ghost to pass, slip away from one coming closer,
//           break line of sight when spotted), so the lantern policy is the only difference: the trio isolates pillar 1.
//           Paths come from the NavMesh (NavMesh.CalculatePath), re-planned every RepathSeconds. The bot
//           reads ghost positions and states directly; a player reads the same from their glow.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using graveyard_shift.Core;
using UnityEngine;
using UnityEngine.AI;

namespace graveyard_shift.Game
{
    public enum BotMode { Careful, AlwaysLit, AlwaysDark }

    public sealed class KeeperBot
    {
        private const float RepathSeconds = 0.5f;
        private const float Arrive = 0.6f;
        private const float SnapRadius = 2f;    // m: how far a point may be from the NavMesh and still count
        private const float LookAhead = 3f;     // m: the bot checks this far along its path
        private const float KeepMargin = 2f;    // m beyond a ghost's sight of me: wait while one is that close to the way ahead
        private const float BackOffMargin = 1f; // m beyond its sight: slip away from one coming my way
        private const int HideSamples = 16;
        private static readonly float[] HideRadii = { 4f, 7f, 10f };
        private const float HiddenBonus = 20f;
        private const float EscapeCommit = 1.5f;  // s: once it starts hiding it keeps going
        private const float MaxDetour = 1.6f;      // a hiding path may be this many times the straight distance
        private const float EdgeMargin = 3f;       // m from the yard's walls counts as a dead end
        private const float EdgePenalty = 15f;
        private const float PathClearance = 3f;    // m: a hiding path must stay this far from every ghost
        private static readonly NavMeshPath Scratch = new NavMeshPath();

        private readonly NavMeshPath _path = new NavMeshPath();
        private readonly List<Vector3> _corners = new List<Vector3>();
        private float _repath;
        private V2 _goalUsed;
        private V2 _escapeGoal;
        private float _escapeTime;
        private readonly Dictionary<string, float> _time = new Dictionary<string, float>();

        public BotMode Mode { get; }
        public Vector2 Direction { get; private set; }
        public bool Lantern { get; private set; } = true;
        public string Reason { get; private set; } = "";
        public string PathInfo => $"path {_path.status} corners={_corners.Count} next={(_corners.Count > 0 ? LevelBuilder.ToGround(_corners[0]).ToString() : "-")}";

        public KeeperBot(BotMode mode) => Mode = mode;

        public void Think(float dt, GameTuning tuning, KeeperController keeper, NightRules night, IReadOnlyList<V2> souls,
                          V2 gate, IReadOnlyList<GhostAgent> ghosts, Level yard)
        {
            V2 me = keeper.Ground;
            string move = "GO";
            V2 goal = Target(me, night, souls, gate);
            bool spotted = false;
            foreach (var g in ghosts)
            {
                if (g.SeesKeeper && (g.Brain.State == GhostState.Hunt || g.Brain.State == GhostState.Suspicious)) spotted = true;
            }

            // The lantern first: it is the only thing the three bots do differently
            switch (Mode)
            {
                case BotMode.AlwaysLit:
                    Lantern = true;
                    break;
                case BotMode.AlwaysDark:
                    Lantern = false;
                    break;
                default:
                    // Spotted: light up and run (speed beats stealth now). Otherwise lit only while no ghost is
                    // anywhere within lit sight (plus a margin), whichever way it faces: then dim and sneak.
                    // Near me, or near where I am heading: lit, the shared brain would stop and wait for that ghost
                    // with an 11 m berth; dark, it can creep on (the 4x yard showed careful waiting a minute a night)
                    bool ghostNear = false;
                    V2 heading = me + new V2(Direction.x, Direction.y) * LookAhead;
                    foreach (var g in ghosts)
                    {
                        if (V2.Distance(g.Ground, me) <= tuning.SightLit + KeepMargin ||
                            V2.Distance(g.Ground, heading) <= tuning.SightLit + KeepMargin) ghostNear = true;
                    }
                    Lantern = spotted || !ghostNear;
                    break;
            }

            // How close a ghost may get depends on how far it could see me now (the game's own rule)
            float sight = Perception.SightRange(tuning, Lantern);
            float keepAway = sight + KeepMargin;
            float backOff = sight + BackOffMargin;

            // Shared movement, the same in every mode, so the lantern is the only difference between the bots.
            // 1. Spotted, or a ghost too close: commit to a hidden spot for a moment (no dithering)
            GhostAgent threat = null;
            foreach (var g in ghosts)
            {
                if (g.SeesKeeper && (g.Brain.State == GhostState.Hunt || g.Brain.State == GhostState.Suspicious)) threat = g;
            }
            if (threat == null)
            {
                foreach (var g in ghosts)
                {
                    if (V2.Distance(g.Ground, me) < backOff && Approaching(g, me)) threat = g;
                }
            }
            if (threat != null && _escapeTime <= 0f)
            {
                _escapeGoal = HideSpot(keeper, threat, ghosts, yard);
                _escapeTime = EscapeCommit;
            }
            if (_escapeTime > 0f)
            {
                _escapeTime -= dt;
                goal = _escapeGoal;
                move = spotted ? "FLEE" : "BACK OFF";
            }

            // 2. Follow a NavMesh path to the goal
            Steer(dt, keeper, goal);

            // 3. A ghost near the way ahead but not coming at me: let it pass
            if (move == "GO")
            {
                V2 ahead = me + new V2(Direction.x, Direction.y) * LookAhead;
                foreach (var g in ghosts)
                {
                    if (V2.Distance(g.Ground, ahead) < keepAway || V2.Distance(g.Ground, me) < backOff)
                    {
                        Direction = Vector2.zero;
                        move = "WAIT";
                    }
                }
            }

            Reason = $"{move}, lantern {(Lantern ? "lit" : "out")}";
            string key = $"{move}/{(Lantern ? "lit" : "out")}";
            _time.TryGetValue(key, out float spent);
            _time[key] = spent + dt;
        }

        // Seconds spent per decision ("WAIT/out": 12.3), for tuning and the scenario test log
        public string Stats()
        {
            var parts = new List<string>();
            foreach (var kv in _time) parts.Add($"{kv.Key} {kv.Value:0.0}s");
            return string.Join(", ", parts);
        }

        private void Steer(float dt, KeeperController keeper, V2 goal)
        {
            V2 me = keeper.Ground;
            _repath -= dt;
            if (_repath <= 0f || _corners.Count == 0 || V2.Distance(goal, _goalUsed) > 1f)
            {
                _repath = RepathSeconds;
                _goalUsed = goal;
                _corners.Clear();
                // CalculatePath does not snap its ends to the NavMesh (SetDestination does): sample them first,
                // or every call is PathInvalid and the bot walks straight into gravestones
                if (NavMesh.SamplePosition(keeper.transform.position, out NavMeshHit from, SnapRadius, NavMesh.AllAreas) &&
                    NavMesh.SamplePosition(LevelBuilder.ToWorld(goal), out NavMeshHit to, SnapRadius, NavMesh.AllAreas) &&
                    NavMesh.CalculatePath(from.position, to.position, NavMesh.AllAreas, _path))
                    _corners.AddRange(_path.corners);
            }
            while (_corners.Count > 1 && V2.Distance(me, LevelBuilder.ToGround(_corners[0])) < Arrive) _corners.RemoveAt(0);
            V2 next = _corners.Count > 0 ? LevelBuilder.ToGround(_corners[0]) : goal;
            V2 dir = V2.Distance(me, next) < Arrive * 0.5f ? new V2(0, 0) : (next - me).Normalized;
            Direction = new Vector2(dir.X, dir.Z);
        }

        // Does the path run within PathClearance of any ghost (checked at corners and segment middles)?
        private static bool PassesNear(NavMeshPath path, IReadOnlyList<GhostAgent> ghosts)
        {
            var c = path.corners;
            for (int i = 0; i < c.Length; i++)
            {
                foreach (var g in ghosts)
                {
                    var gp = g.transform.position;
                    if (Vector3.Distance(c[i], gp) < PathClearance) return true;
                    if (i > 0 && Vector3.Distance((c[i] + c[i - 1]) * 0.5f, gp) < PathClearance) return true;
                }
            }
            return false;
        }

        private static float PathLength(NavMeshPath path)
        {
            float length = 0f;
            for (int i = 1; i < path.corners.Length; i++) length += Vector3.Distance(path.corners[i - 1], path.corners[i]);
            return length;
        }

        // Is the ghost heading my way?
        private static bool Approaching(GhostAgent g, V2 me)
        {
            V2 v = g.Velocity;
            return v.Length > 0.2f && V2.Dot(v.Normalized, (me - g.Ground).Normalized) > 0.3f;
        }

        // A spot on the NavMesh, near enough to reach, that the threat cannot see and that is far from it
        private static V2 HideSpot(KeeperController keeper, GhostAgent threat, IReadOnlyList<GhostAgent> ghosts, Level yard)
        {
            Vector3 me = keeper.transform.position;
            Vector3 eye = threat.transform.position + Vector3.up * 1.3f;
            V2 best = keeper.Ground + (keeper.Ground - threat.Ground).Normalized * 5f;
            float bestScore = float.MinValue;
            foreach (float radius in HideRadii)
            {
                for (int i = 0; i < HideSamples; i++)
                {
                    float a = i * Mathf.PI * 2f / HideSamples;
                    var probe = me + new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a)) * radius;
                    if (!NavMesh.SamplePosition(probe, out NavMeshHit hit, 0.8f, NavMesh.AllAreas)) continue;
                    // Reachable by a real path that is not much longer than the straight line
                    if (!NavMesh.SamplePosition(me, out NavMeshHit from, SnapRadius, NavMesh.AllAreas) ||
                        !NavMesh.CalculatePath(from.position, hit.position, NavMesh.AllAreas, Scratch) ||
                        Scratch.status != NavMeshPathStatus.PathComplete || PathLength(Scratch) > radius * MaxDetour ||
                        PassesNear(Scratch, ghosts)) continue;
                    bool hidden = Physics.Linecast(eye, hit.position + Vector3.up * 1.1f, out RaycastHit block) &&
                                  block.collider.GetComponent<Cover>() != null;
                    // Corners and edges are dead ends: a ghost coming round traps you there
                    float edge = yard.EdgeDistance(LevelBuilder.ToGround(hit.position), EdgeMargin);
                    float nearest = float.MaxValue;   // every ghost counts, not only the one that saw me
                    foreach (var g in ghosts) nearest = Mathf.Min(nearest, Vector3.Distance(hit.position, g.transform.position));
                    float score = nearest - 0.5f * radius +
                                  (hidden ? HiddenBonus : 0f) - (edge < EdgeMargin ? EdgePenalty : 0f);
                    if (score > bestScore)
                    {
                        bestScore = score;
                        best = LevelBuilder.ToGround(hit.position);
                    }
                }
            }
            return best;
        }

        private static V2 Target(V2 me, NightRules night, IReadOnlyList<V2> souls, V2 gate)
        {
            if (night.AllCollected) return gate;
            V2 best = gate;
            float bestD = float.MaxValue;
            for (int i = 0; i < souls.Count; i++)
            {
                if (night.IsCollected(i)) continue;
                float d = V2.Distance(me, souls[i]);
                if (d < bestD)
                {
                    bestD = d;
                    best = souls[i];
                }
            }
            return best;
        }
    }
}
