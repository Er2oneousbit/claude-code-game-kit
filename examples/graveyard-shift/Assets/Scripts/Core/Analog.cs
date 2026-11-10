// ---------------------------------------------------------------------------
// Analog.cs
// Purpose : Analog input shaping (#274, the rules of Bevy's logic/analog.rs since #265): the left stick and the
//           triggers as the game reads them, after the player's deadzone and invert_y, so a racer steers by how far
//           the stick leans and brakes by how far a trigger is in.
// Usage   : (double x, double y) = Analog.Stick(rawX, rawY, GameSettings.Number(s, "input", "deadzone"), invertY);
//           double gas = Analog.Trigger(rawR2, Analog.TRIGGER_DEADZONE);
//           List<string> moves = Analog.StickActions(rawX, rawY, deadzone, invertY);   // move_left ... held by the stick
// Notes   : No UnityEngine types (EditMode tests run it). The stick deadzone is radial (the length of the vector, not
//           each axis), and what is left is rescaled to 0..1, so a stick just past the deadzone gives a small value
//           instead of jumping to the deadzone's size; the direction never changes. Up is +y; invert_y flips it.
//           Triggers have their own small fixed deadzone: input.deadzone is the "Stick dead zone" setting, and a
//           trigger that rests at 0.1 would otherwise lose a fifth of its travel. NaN and infinities count as 0.
//
// Pseudocode:
//   Stick(x, y, dz, inv): y = -y if inv -> len = |(x, y)| -> len <= dz: (0, 0)
//   -> scale = min((len - dz) / (1 - dz), 1) / len -> (x * scale, y * scale)
//   Trigger(v, dz): v = clamp(v, 0, 1) -> v <= dz: 0 -> (v - dz) / (1 - dz)
//   StickActions: lean past max(dz, STICK_HOLD_MIN) on an axis (invert_y applied) holds that move_* action
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class Analog
    {
        // ---- Tunables ------------------------------------------------------------
        public const double TRIGGER_DEADZONE = 0.05;   // trigger travel ignored at rest (0 to 1)
        public const double MAX_DEADZONE = 0.95;       // the largest deadzone accepted (settings clamp to 0.9); keeps the rescale finite
        public const double STICK_HOLD_MIN = 0.2;      // raw stick lean that also holds a move_* action; never below the deadzone

        /// <summary>The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1.</summary>
        public static (double X, double Y) Stick(double x, double y, double deadzone, bool invertY)
        {
            x = Finite(x);
            y = Finite(y);
            if (invertY)
            {
                y = -y;
            }
            double dz = Clamp(Finite(deadzone), 0.0, MAX_DEADZONE);
            double len = Math.Sqrt(x * x + y * y);
            if (len <= dz || len == 0.0)
            {
                return (0.0, 0.0);
            }
            double scale = Math.Min((len - dz) / (1.0 - dz), 1.0) / len;
            return (x * scale, y * scale);
        }

        /// <summary>A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1.</summary>
        public static double Trigger(double value, double deadzone)
        {
            double v = Clamp(Finite(value), 0.0, 1.0);
            double dz = Clamp(Finite(deadzone), 0.0, MAX_DEADZONE);
            return v <= dz ? 0.0 : (v - dz) / (1.0 - dz);
        }

        /// <summary>The move_* actions the raw stick holds: a lean past the deadzone (at least STICK_HOLD_MIN) on
        /// that axis, invert_y honoured. Order: left, right, up, down.</summary>
        public static List<string> StickActions(double x, double y, double deadzone, bool invertY)
        {
            double on = Math.Max(Finite(deadzone), STICK_HOLD_MIN);
            x = Finite(x);
            y = invertY ? -Finite(y) : Finite(y);
            var output = new List<string>();
            if (-x > on) output.Add("move_left");
            if (x > on) output.Add("move_right");
            if (y > on) output.Add("move_up");
            if (-y > on) output.Add("move_down");
            return output;
        }

        /// <summary>The direction the held move_* actions ask for plus the shaped stick, clamped to length 1: keyboard
        /// play gives unit directions, a half-leaned stick half speed.</summary>
        public static (double X, double Y) MoveVector(bool left, bool right, bool up, bool down, double stickX, double stickY)
        {
            double hx = (right ? 1.0 : 0.0) - (left ? 1.0 : 0.0);
            double hy = (up ? 1.0 : 0.0) - (down ? 1.0 : 0.0);
            double hl = Math.Sqrt(hx * hx + hy * hy);
            if (hl > 0.0)
            {
                hx /= hl;
                hy /= hl;
            }
            double x = hx + Finite(stickX), y = hy + Finite(stickY);
            double len = Math.Sqrt(x * x + y * y);
            return len > 1.0 ? (x / len, y / len) : (x, y);
        }

        private static double Finite(double v)
        {
            return double.IsNaN(v) || double.IsInfinity(v) ? 0.0 : v;
        }

        private static double Clamp(double v, double lo, double hi)
        {
            return v < lo ? lo : v > hi ? hi : v;
        }
    }
}
