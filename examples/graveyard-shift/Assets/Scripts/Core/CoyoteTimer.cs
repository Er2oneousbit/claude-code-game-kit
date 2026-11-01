// ---------------------------------------------------------------------------
// CoyoteTimer.cs
// Purpose : Grants a short grace window to still jump after leaving a ledge ("coyote time"). Same rules as
//           the Godot and web CoyoteTimer; checked against data/golden/juice.json ("coyote").
// Usage   : var coyote = new CoyoteTimer(0.1);
//           each FixedUpdate: coyote.Update(Time.fixedDeltaTime, isGrounded);
//           on jump pressed:  if (coyote.CanJump()) { ...jump...; coyote.Consume(); }
// Notes   : No UnityEngine types (EditMode tests run it). A window of 0 means "no coyote time", not
//           "no jumping": grounded jumps always work. A negative window from bad tuning data counts as 0.
//           This file is a TEMPLATE example. Delete it if the game has no jump.
//
// Pseudocode:
//   on floor   -> grounded, time_left = window; a landing re-arms a consumed jump
//   off floor  -> not grounded, time_left = max(0, time_left - dt)
//   can_jump() -> not consumed and (grounded or time_left > 0)
//   consume()  -> consumed until the next landing
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class CoyoteTimer
    {
        // ---- Tunables ------------------------------------------------------------
        public const double DEFAULT_WINDOW_S = 0.1;    // seconds after leaving a ledge that a jump still works

        public double Window { get; }
        public double TimeLeft { get; private set; }
        public bool Grounded { get; private set; }

        private bool _consumed;

        public CoyoteTimer(double windowSeconds = DEFAULT_WINDOW_S)
        {
            Window = Math.Max(windowSeconds, 0.0);
        }

        public void Update(double dt, bool onFloor)
        {
            if (onFloor)
            {
                if (!Grounded)
                {
                    _consumed = false;             // landed: the next jump is available again
                }
                Grounded = true;
                TimeLeft = Window;
            }
            else
            {
                Grounded = false;
                TimeLeft = Math.Max(TimeLeft - dt, 0.0);
            }
        }

        public bool CanJump()
        {
            return !_consumed && (Grounded || TimeLeft > 0.0);
        }

        public void Consume()
        {
            _consumed = true;
            TimeLeft = 0.0;
        }
    }
}
