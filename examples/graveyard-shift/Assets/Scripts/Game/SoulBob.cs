// ---------------------------------------------------------------------------
// SoulBob.cs
// Purpose : Souls bob gently so they read as alive from across the yard.
// Usage   : added by LevelBuilder to each soul orb
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class SoulBob : MonoBehaviour
    {
        private const float Height = 0.15f;  // m
        private const float Speed = 2f;      // rad/s
        private Vector3 _base;
        private float _phase;

        private void Start()
        {
            _base = transform.position;
            _phase = transform.position.x * 0.37f;
        }

        private void Update()
        {
            transform.position = _base + Vector3.up * (Mathf.Sin(Time.time * Speed + _phase) * Height);
        }
    }
}
