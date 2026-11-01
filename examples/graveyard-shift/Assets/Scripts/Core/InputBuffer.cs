// ---------------------------------------------------------------------------
// InputBuffer.cs
// Purpose : Remembers a press for a short window, so a jump pressed just before landing (or an attack
//           pressed just before the last one ends) still happens. Checked against data/golden/juice.json
//           ("input_buffer").
// Usage   : var buffer = new InputBuffer();
//           on press:   buffer.Press("jump");
//           each frame: buffer.Update(Time.deltaTime);
//           when able:  if (canJump && buffer.Consume("jump")) { ...jump... }
// Notes   : No UnityEngine types (EditMode tests run it). Actions are plain strings, the same names as the
//           bindings (Bindings.cs). Pair it with CoyoteTimer for forgiving platformer jumps.
//
// Pseudocode:
//   press(a):   pending[a] = window
//   update(dt): every pending -= dt ; at or below EXPIRED it is dropped
//   consume(a): pending and > 0 -> drop it, true ; else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public sealed class InputBuffer
    {
        // ---- Tunables ------------------------------------------------------------
        public const double DEFAULT_WINDOW_S = 0.12;   // seconds a press stays usable
        private const double EXPIRED = 1e-12;          // float leftovers at or below this count as expired

        private readonly Dictionary<string, double> _pending = new Dictionary<string, double>();
        private readonly List<string> _keys = new List<string>();

        public double Window;

        public InputBuffer(double windowSeconds = DEFAULT_WINDOW_S)
        {
            Window = windowSeconds;
        }

        public void Press(string action)
        {
            _pending[action] = Window;
        }

        public void Update(double dt)
        {
            _keys.Clear();
            _keys.AddRange(_pending.Keys);         // a copy: the loop changes the dictionary
            foreach (string action in _keys)
            {
                double left = _pending[action] - dt;
                if (left <= EXPIRED)
                {
                    _pending.Remove(action);
                }
                else
                {
                    _pending[action] = left;
                }
            }
        }

        /// <summary>True (once) when the action was pressed within the window.</summary>
        public bool Consume(string action)
        {
            if (_pending.TryGetValue(action, out double left) && left > 0.0)
            {
                _pending.Remove(action);
                return true;
            }
            return false;
        }

        public bool IsPending(string action)
        {
            return _pending.ContainsKey(action);
        }

        public void Clear()
        {
            _pending.Clear();
        }
    }
}
