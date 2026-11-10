// ---------------------------------------------------------------------------
// JuiceDemo.hpp
// Purpose : The juice demo (debug builds, main menu > Juice demo; #275): a box you hit (attack) that shakes the
//           camera with trauma, freezes the game for a hitstop, squashes on a spring and flashes the screen through
//           the FlashLimiter; a follow camera with a visible deadzone; an input-buffered jump with coyote time; a
//           guard (interact) held or toggled with hold_to_toggle; walking by the held move actions or the analog
//           stick (Shell::move_vector, #274); a subtitle line, a bark and a caption; the accessibility settings live.
// Usage   : the shell owns it: main menu > Juice demo, or python tools/dev.py smoke --drive show:juice --screenshot
//           captures/juice.bmp. A game copies the parts it wants into its play screen (src/game/Game.cpp).
// Notes   : The same demo as the LOVE and Godot shells. Time: the hitstop and the flash limiter run on REAL time
//           (the shell's dt); everything else (shake, follow, spring, input buffer, coyote) on GAME time = the
//           hitstop-scaled dt times access.game_speed. The limiter is always on (at most 3 flashes per real
//           second); access.flash_limit only tones each flash down to kFlashGentle. Shake intensity is
//           core::effective_shake (0 with reduce motion). SDL's renderer draws no rotated rectangles, so the
//           shake's angle is not shown (a game rotates its sprites with SDL_RenderTextureRotated).
//
// Pseudocode (update):
//   real time += dt; flash fades; game dt = hitstop.scaled_dt(dt) * game_speed
//   walk by move_vector().x; fall; land; windows * timing_scale; (auto_repeat: held attack hits)
//   coyote + buffer -> jump; guard held or toggled; camera follows; shake, spring, "hit" ring advance
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <string>

#include "core/CoyoteTimer.hpp"
#include "core/FlashLimiter.hpp"
#include "core/FollowCamera.hpp"
#include "core/Hitstop.hpp"
#include "core/InputBuffer.hpp"
#include "core/MotorAccess.hpp"
#include "core/Shake.hpp"
#include "core/ShellLogic.hpp"
#include "core/Spring.hpp"

namespace shell {

class Shell;
class Draw;

class JuiceDemo {
public:
    explicit JuiceDemo(Shell& shell);

    void enter();                                  // the goal and the intro line (the shell makes a fresh demo first)
    void update(double real_dt);
    void draw(Draw& d);
    bool action(const std::string& name);          // true when the demo used the action
    int hits() const { return hits_; }

    // ---- Tunables ----
    static constexpr double kWorldW = 1600;
    static constexpr double kFloorY = 300;
    static constexpr double kPlayer = 20;
    static constexpr double kTarget = 40;
    static constexpr double kTargetX = 440;
    static constexpr double kStartX = 380;
    static constexpr double kSpeed = 160;          // px per second at a full lean
    static constexpr double kGravity = 900;
    static constexpr double kJumpSpeed = 340;
    static constexpr double kHitRange = 80;        // px between centres
    static constexpr double kHitTrauma = 0.55;
    static constexpr double kHitStopS = 0.09;
    static constexpr double kHitSquash = 0.45;     // spring displacement on a hit
    static constexpr double kFlashS = 0.12;        // a flash fades out over this (real time)
    static constexpr double kFlashFull = 0.85;     // peak opacity ...
    static constexpr double kFlashGentle = 0.3;    // ... and with access.flash_limit
    static constexpr double kPopS = 0.25;          // the "hit" ring eases out over this

private:
    Shell& shell_;
    double x_ = kStartX;
    double y_ = kFloorY - kPlayer;
    double vx_ = 0;
    double vy_ = 0;
    core::Shake shake_{10.0, 0.04};
    core::ShakeOffset offset_;
    core::Hitstop hitstop_;
    core::FollowCamera cam_{96.0, 64.0, 0.2, 6.0, kStartX, kFloorY - 80};
    core::InputBuffer buffer_;
    core::CoyoteTimer coyote_;
    core::AutoRepeat attack_repeat_;
    core::HeldAction guard_;
    core::Spring spring_{4.0, 0.35};
    core::FlashLimiter limiter_;
    bool guarding_ = false;
    double real_time_ = 0;
    double flash_ = 0;
    double flash_peak_ = 0;
    double pop_ = 0;
    int hits_ = 0;
    int refused_ = 0;

    void hit();
    void draw_hud(Draw& d);
};

}  // namespace shell

// {{FOOTER}}
