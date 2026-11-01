// ---------------------------------------------------------------------------
// FollowCamera.hpp
// Purpose : Camera follow for 2D games: a deadzone box around the camera, look-ahead along the target's
//           velocity, and frame-rate independent exponential smoothing. Pure logic, no SDL.
// Usage   : core::FollowCamera cam;   // or FollowCamera(deadzone_w, deadzone_h, lookahead, smoothing, x, y)
//           each tick: const auto c = cam.update(dt, player.x, player.y, player.vx, player.vy);
//                      draw the world offset by (screen_w / 2 - c.x, screen_h / 2 - c.y)
// Notes   : smoothing is a rate per second (higher follows tighter); 0 snaps. The same dt split into more
//           steps lands in about the same place, because the blend is 1 - exp(-smoothing * dt).
//           Matches tools/golden_vectors.py (Follow), checked against data/golden/juice.json.
//
// Pseudocode:
//   per axis: goal = camera, or the deadzone edge the target pushed past; goal += velocity * lookahead
//   k = 1 - exp(-smoothing * dt)  (1 when smoothing is 0)
//   camera += (goal - camera) * k
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <cmath>

namespace core {

// ---- Tunables ----
constexpr double kFollowDeadzoneW = 64.0;   // pixels the target can move sideways before the camera follows
constexpr double kFollowDeadzoneH = 48.0;
constexpr double kFollowLookahead = 0.25;   // seconds of velocity to look ahead
constexpr double kFollowSmoothing = 8.0;    // per second; 0 = snap

struct CameraPos {
    double x = 0.0;
    double y = 0.0;
};

class FollowCamera {
public:
    explicit FollowCamera(double deadzone_w = kFollowDeadzoneW, double deadzone_h = kFollowDeadzoneH,
                          double lookahead = kFollowLookahead, double smoothing = kFollowSmoothing,
                          double x = 0.0, double y = 0.0)
        : dw_(deadzone_w), dh_(deadzone_h), lookahead_(lookahead), smoothing_(smoothing), x_(x), y_(y) {}

    // Moves the camera toward target (tx, ty) moving at (vx, vy) and returns the new position.
    CameraPos update(double dt, double tx, double ty, double vx = 0.0, double vy = 0.0) {
        const double gx = axis(x_, tx, dw_ / 2.0) + vx * lookahead_;
        const double gy = axis(y_, ty, dh_ / 2.0) + vy * lookahead_;
        const double k = smoothing_ > 0.0 ? 1.0 - std::exp(-smoothing_ * dt) : 1.0;
        x_ += (gx - x_) * k;
        y_ += (gy - y_) * k;
        return {x_, y_};
    }

    // Jumps straight to a position (level start, respawn, cutscene cut).
    void snap_to(double x, double y) {
        x_ = x;
        y_ = y;
    }

    double x() const { return x_; }
    double y() const { return y_; }

private:
    // Where the camera wants to be on one axis: unchanged while the target is inside the deadzone.
    static double axis(double cam, double target, double half) {
        if (target > cam + half) {
            return target - half;
        }
        if (target < cam - half) {
            return target + half;
        }
        return cam;
    }

    double dw_;
    double dh_;
    double lookahead_;
    double smoothing_;
    double x_;
    double y_;
};

}  // namespace core
