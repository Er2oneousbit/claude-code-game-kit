// ---------------------------------------------------------------------------
// GateSwing.cs
// Purpose : The graveyard's iron gate: two leaves that stay shut (their colliders block the opening) until
//           Open() swings them outward, away from the yard; Close() swings them back.
// Usage   : built by LevelBuilder.BuildGate; GraveyardGame calls built.Gate.Open() when every soul is collected
//           and built.Gate.Shut() when a catch takes one away again; Close() swings them back slowly.
// Notes   : A leaf turns about its hinge on the wall line. Unity's +yaw turns +x toward -z, so the west leaf
//           (pointing +x from its hinge) opens with +OpenAngle and the east leaf with -OpenAngle: both outward.
//           The escape counts once the gate IsOpen and the keeper stands in its doorway (GameTuning.GateRadius).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): Shut() closes the leaves in the same frame. After a catch the
//           keeper wakes 3 m inside, and a lit keeper running for the gate got out while it swung shut (1.6 s).
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class GateSwing : MonoBehaviour
    {
        private const float OpenAngle = 100f;     // degrees each leaf turns
        private const float OpenSeconds = 1.6f;

        private readonly List<(Transform Hinge, int Side)> _hinges = new List<(Transform, int)>();
        private float _t;                         // 0 shut .. 1 open
        private float _target;                    // where the leaves are heading: 0 or 1

        public bool IsOpen => _t >= 1f;
        public bool IsOpening => _target > 0f;    // opening or open
        public bool IsShut => _t <= 0f;

        // side: -1 the west hinge (its leaf points east), +1 the east hinge
        public void AddHinge(Transform hinge, int side) => _hinges.Add((hinge, side));

        public void Open() => _target = 1f;
        public void Close() => _target = 0f;

        // Shut now: the closed rotation this frame, and the colliders moved with it before anybody's next move
        public void Shut()
        {
            _target = 0f;
            _t = 0f;
            Pose();
            Physics.SyncTransforms();
        }

        // Angle of one hinge right now (for tests): 0 shut, +-OpenAngle open
        public float Angle(int index) => Mathf.DeltaAngle(0f, _hinges[index].Hinge.localEulerAngles.y);

        private void Update()
        {
            if (_t == _target) return;
            _t = Mathf.MoveTowards(_t, _target, Time.deltaTime / OpenSeconds);
            Pose();
        }

        private void Pose()
        {
            float eased = 1f - (1f - _t) * (1f - _t);    // starts quick, settles
            foreach (var (hinge, side) in _hinges)
                hinge.localRotation = Quaternion.Euler(0f, -side * OpenAngle * eased, 0f);
        }
    }
}
