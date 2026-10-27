// ---------------------------------------------------------------------------
// GhostAgent.cs
// Purpose : One ghost: perception (cone and range from Core/Perception, line of sight by raycast against
//           Cover), the state machine (Core/GhostBrain) and movement (NavMeshAgent), plus its tell: a
//           glow in the state's color (pillar 2: read the ghosts).
// Usage   : ghost.Init(id, tuning, route, setup, startWaypoint); each frame ghost.Think(dt, keeper, god)
// Notes   : SOP-14 layers: perception in (Sees), decision (GhostBrain.Tick), movement out (the agent).
//           Colors: blue patrol and return, yellow suspicious and search, red hunt.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): a tired ghost never catches (GhostBrain.CanCatch); the agent
//           re-paths only when the destination moves RepathDistance or it has no path (SetDestination every frame
//           restarted a partial path that never finished computing, so a hunting ghost stood still).
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using graveyard_shift.Core;
using UnityEngine;
using UnityEngine.AI;

namespace graveyard_shift.Game
{
    public sealed class GhostAgent : MonoBehaviour
    {
        private const float EyeHeight = 1.3f;
        private const float FaceSpeed = 360f;   // degrees per second while suspicious
        private const float GlowRange = 6f;
        private const float GlowIntensity = 3f;
        private const float BodyGlow = 0.9f;    // emission strength of the state color on the body
        private const float RepathDistance = 0.25f;   // m the destination moves before the agent asks for a new path
        public static readonly Color Calm = new Color(0.35f, 0.6f, 1f);
        public static readonly Color Wary = new Color(1f, 0.85f, 0.3f);
        public static readonly Color Hunting = new Color(1f, 0.25f, 0.2f);

        private GameTuning _t;
        private NavMeshAgent _agent;
        private Light _glow;
        private CharacterAnimator _anim;
        private readonly List<Material> _bodyMaterials = new List<Material>();
        private Vector3 _pathTo;                  // the destination last given to the agent
        private bool _hasPathTo;

        public int Id { get; private set; }
        public GhostBrain Brain { get; private set; }
        public bool SeesKeeper { get; private set; }
        public V2 Ground => LevelBuilder.ToGround(transform.position);
        public V2 Forward => new V2(transform.forward.x, transform.forward.z);
        public V2 Velocity => _agent == null ? new V2(0, 0) : new V2(_agent.velocity.x, _agent.velocity.z);

        // lightScale: the difficulty's scale on the light the ghost casts (0: none; its body still glows its state)
        public void Init(int id, GameTuning tuning, List<V2> route, GraveyardSetup setup, int startWaypoint, float lightScale = 1f)
        {
            Id = id;
            _t = tuning;
            Brain = new GhostBrain(tuning, route, startWaypoint + 1);
            var body = Instantiate(setup.Find("character-ghost"), transform);
            body.transform.localScale = Vector3.one * Level.WorldScale;
            _anim = new CharacterAnimator(body);
            // The body glows in the state color (own material copies, so the shared model is untouched)
            foreach (var r in body.GetComponentsInChildren<Renderer>())
            {
                foreach (var m in r.materials)
                {
                    m.EnableKeyword("_EMISSION");
                    _bodyMaterials.Add(m);
                }
            }
            _glow = LevelBuilder.AddLight(transform, new Vector3(0f, 1.4f, 0f), Calm, GlowRange * lightScale, GlowIntensity);
            _glow.enabled = lightScale > 0f;

            _agent = gameObject.AddComponent<NavMeshAgent>();
            _agent.radius = 0.45f;
            _agent.height = 1.8f;
            _agent.angularSpeed = 540f;
            _agent.acceleration = 24f;
            _agent.stoppingDistance = 0.1f;
            _agent.autoBraking = false;
            _agent.Warp(LevelBuilder.ToWorld(route[startWaypoint % route.Count]));
        }

        // One frame. Returns true when this ghost touches the keeper.
        public bool Think(float dt, KeeperController keeper, out bool stateChanged)
        {
            SeesKeeper = Perception.Sees(_t, Ground, Forward, keeper.Ground, keeper.LanternLit, LineOfSight(keeper));
            var order = Brain.Tick(dt, SeesKeeper, keeper.Ground, Ground, out stateChanged);

            Drive(order.Destination, order.Speed);
            if (order.FaceKeeper)
            {
                var to = keeper.transform.position - transform.position;
                to.y = 0f;
                if (to.sqrMagnitude > 0.01f)
                    transform.rotation = Quaternion.RotateTowards(transform.rotation, Quaternion.LookRotation(to), FaceSpeed * dt);
            }

            var color = GlowColor(Brain.State);
            _glow.color = color;
            foreach (var m in _bodyMaterials) m.SetColor("_EmissionColor", color * BodyGlow);
            _anim.Play(order.Speed > 0f ? "walk" : "idle", order.Speed > 0f ? order.Speed / _t.PatrolSpeed * 0.6f : 1f);
            return Brain.CanCatch(Ground, keeper.Ground);
        }

        // Movement out: toward destination at speed (0 stands still). A new path only when the destination moved or
        // the agent has none: a path is computed over several frames, and asking again every frame restarts it.
        public void Drive(V2 destination, float speed)
        {
            _agent.speed = speed;
            _agent.isStopped = speed <= 0f;
            if (_agent.isStopped) return;
            if (_agent.pathPending) return;   // let the path being computed finish (the agent keeps its old one meanwhile)
            var to = LevelBuilder.ToWorld(destination);
            bool moved = !_hasPathTo || (to - _pathTo).sqrMagnitude > RepathDistance * RepathDistance;
            if (!moved && _agent.hasPath) return;
            _agent.SetDestination(to);
            _pathTo = to;
            _hasPathTo = true;
        }

        public static Color GlowColor(GhostState s)
        {
            switch (s)
            {
                case GhostState.Hunt: return Hunting;
                case GhostState.Suspicious:
                case GhostState.Search: return Wary;
                default: return Calm;
            }
        }

        // Clear line from the ghost's eyes to the keeper's chest, unless Cover is in the way
        public bool CanSee(KeeperController keeper) => LineOfSight(keeper);

        private bool LineOfSight(KeeperController keeper)
        {
            var eye = transform.position + Vector3.up * EyeHeight;
            foreach (var hit in Physics.RaycastAll(eye, keeper.Chest - eye, Vector3.Distance(eye, keeper.Chest)))
            {
                if (hit.collider.GetComponent<Cover>() != null) return false;
            }
            return true;
        }
    }
}
