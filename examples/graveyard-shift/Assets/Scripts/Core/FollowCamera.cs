// ---------------------------------------------------------------------------
// FollowCamera.cs
// Purpose : Camera follow with a deadzone box, look-ahead along the target's velocity, and frame-rate
//           independent exponential smoothing. Checked against data/golden/juice.json ("follow").
// Usage   : var follow = new FollowCamera(x: start.x, y: start.y);
//           each frame: var c = follow.Update(Time.deltaTime, player.x, player.y, velocity.x, velocity.y);
//                       camera position = (c.X, c.Y)
// Notes   : No UnityEngine types (EditMode tests run it). The target moves freely inside the deadzone without
//           moving the camera; past an edge the camera follows so the target sits on that edge. smoothing is
//           a rate per second (1 - e^(-smoothing*dt) of the gap closes each frame, the same at 30 or 144 fps);
//           0 snaps. Units are whatever the game uses (pixels in the defaults).
//
// Pseudocode:
//   axis(cam, target, half): target past cam+half -> target-half ; past cam-half -> target+half ; else cam
//   desired = axis(...) + velocity * lookahead, per axis
//   k = smoothing > 0 ? 1 - exp(-smoothing*dt) : 1 ; position += (desired - position) * k
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class FollowCamera
    {
        // ---- Tunables ------------------------------------------------------------
        public const double DEFAULT_DEADZONE_W = 64.0; // box the target can move in without moving the camera
        public const double DEFAULT_DEADZONE_H = 48.0;
        public const double DEFAULT_LOOKAHEAD = 0.25;  // seconds of velocity to lead by
        public const double DEFAULT_SMOOTHING = 8.0;   // per second; 0 = snap

        public double DeadzoneW;
        public double DeadzoneH;
        public double Lookahead;
        public double Smoothing;
        public double X;
        public double Y;

        public FollowCamera(double deadzoneW = DEFAULT_DEADZONE_W, double deadzoneH = DEFAULT_DEADZONE_H,
                            double lookahead = DEFAULT_LOOKAHEAD, double smoothing = DEFAULT_SMOOTHING,
                            double x = 0.0, double y = 0.0)
        {
            DeadzoneW = deadzoneW;
            DeadzoneH = deadzoneH;
            Lookahead = lookahead;
            Smoothing = smoothing;
            X = x;
            Y = y;
        }

        /// <summary>Moves the camera toward the target (tx, ty) moving at (vx, vy); returns the new position.</summary>
        public (double X, double Y) Update(double dt, double tx, double ty, double vx = 0.0, double vy = 0.0)
        {
            double dx = Axis(X, tx, DeadzoneW / 2.0) + vx * Lookahead;
            double dy = Axis(Y, ty, DeadzoneH / 2.0) + vy * Lookahead;
            double k = Smoothing > 0.0 ? 1.0 - Math.Exp(-Smoothing * dt) : 1.0;
            X += (dx - X) * k;
            Y += (dy - Y) * k;
            return (X, Y);
        }

        private static double Axis(double cam, double target, double half)
        {
            if (target > cam + half)
            {
                return target - half;
            }
            if (target < cam - half)
            {
                return target + half;
            }
            return cam;
        }
    }
}
