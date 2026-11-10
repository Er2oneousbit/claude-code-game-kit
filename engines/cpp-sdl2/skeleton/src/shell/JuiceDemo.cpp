// ---------------------------------------------------------------------------
// JuiceDemo.cpp
// Purpose : Implementation of the juice demo (see JuiceDemo.hpp).
// Usage   : compiled into game_lib; the shell creates it for its juice screen.
// Notes   : World space is pixels on a floor kWorldW wide; the screen shows it around the camera, plus the shake's
//           offset. World content is drawn with ui = false (the access report does not take it for a panel), the
//           HUD outlined over it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "shell/JuiceDemo.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "core/Analog.hpp"
#include "core/Ease.hpp"
#include "core/Settings.hpp"
#include "shell/Draw.hpp"
#include "shell/Shell.hpp"

namespace shell {

namespace {

// ---- Tunables: the demo's fallback colours when data/access/colours.json lacks one ----
constexpr Rgb kPlayerColour{242, 191, 76};
constexpr Rgb kTargetColour{89, 204, 115};
constexpr Rgb kHitColour{255, 76, 64};
constexpr Rgb kFloorColour{64, 69, 82};
constexpr Rgb kDeadzoneColour{102, 179, 255};
const char* kIntroLine = "guide.welcome";
const char* kHitBark = "box.ouch";
const char* kHitCaption = "box_hit";
const char* kHudActions[] = {"move_left", "move_right", "jump", "attack", "interact", "pause"};
constexpr double kFloorMarkGap = 80;          // floor marks every this many px, so camera motion shows

std::string fixed2(double v) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.2f", v);
    return buf;
}

}  // namespace

JuiceDemo::JuiceDemo(Shell& shell) : shell_(shell) {}

void JuiceDemo::enter() {
    shell_.set_objective(shell_.t("juice.objective"));   // what "What now?" on the pause menu says (#167)
    shell_.say_line(kIntroLine);
}

void JuiceDemo::hit() {
    if (std::abs((x_ + kPlayer / 2) - (kTargetX + kTarget / 2)) > kHitRange) {
        return;
    }
    ++hits_;
    shake_.add_trauma(kHitTrauma);
    hitstop_.hit(kHitStopS);
    spring_.x = kHitSquash;
    pop_ = kPopS;
    if (limiter_.request(real_time_)) {                   // real time: always rate-limited
        flash_ = kFlashS;
        flash_peak_ = shell_.access_flag("flash_limit") ? kFlashGentle : kFlashFull;
    } else {
        ++refused_;
    }
    shell_.caption(kHitCaption);
    shell_.say_line(kHitBark);
}

bool JuiceDemo::action(const std::string& name) {
    if (name == "jump") {
        buffer_.press("jump");
        return true;
    }
    if (name == "attack") {
        hit();
        return true;
    }
    return name == "interact";                            // the guard reads the button itself (update)
}

void JuiceDemo::update(double real_dt) {
    real_time_ += real_dt;
    flash_ = std::max(0.0, flash_ - real_dt);
    const double dt = hitstop_.scaled_dt(real_dt) * shell_.game_speed();   // game time from here on
    // walk: the held move actions and the analog stick, deadzone and all (#274)
    vx_ = shell_.move_vector().x * kSpeed;
    x_ = std::clamp(x_ + vx_ * dt, 0.0, kWorldW - kPlayer);
    vy_ += kGravity * dt;
    y_ += vy_ * dt;
    const bool on_floor = y_ >= kFloorY - kPlayer;
    if (on_floor) {
        y_ = kFloorY - kPlayer;
        vy_ = 0;
    }
    // access.timing_scale (#166): every timing window, longer by the player's factor
    const double k = shell_.timing_scale();
    buffer_.set_window(core::scaled_window(core::kInputBufferWindow, k));
    coyote_.set_window(core::scaled_window(core::kCoyoteWindow, k));
    if (shell_.access_flag("auto_repeat") && attack_repeat_.update(dt, shell_.is_down("attack"))) {
        hit();
    }
    coyote_.update(dt, on_floor);
    buffer_.update(dt);
    if (coyote_.can_jump() && buffer_.consume("jump")) {
        vy_ = -kJumpSpeed;
        coyote_.consume();
    }
    guarding_ = guard_.update(shell_.is_down("interact"), shell_.access_flag("hold_to_toggle"));
    cam_.update(dt, x_ + kPlayer / 2, y_, vx_, 0);
    offset_ = shake_.update(dt, core::effective_shake(shell_.settings()));
    spring_.update(dt);
    pop_ = std::max(0.0, pop_ - dt);
}

void JuiceDemo::draw(Draw& d) {
    const double W = style::kBaseW;
    const double H = style::kBaseH;
    // world -> screen: around the camera, plus the shake
    const double ox = std::floor(W / 2 - cam_.x()) + offset_.x;
    const double oy = std::floor(H / 2 - cam_.y()) + offset_.y;
    d.fill(-200 + ox, kFloorY + oy, kWorldW + 400, 200, shell_.palette("floor", kFloorColour), 255, false);
    for (double gx = 0; gx <= kWorldW; gx += kFloorMarkGap) {
        d.fill(gx + ox, kFloorY + 6 + oy, 2, 8, style::kPanelEdge, 255, false);
    }
    const core::SquashScale s = core::squash(spring_.x);
    const double tw = kTarget * s.sx;
    const double th = kTarget * s.sy;
    d.fill(kTargetX + (kTarget - tw) / 2 + ox, kFloorY - th + oy, tw, th, shell_.palette("target", kTargetColour), 255, false);
    const Rgb player = shell_.palette("player", kPlayerColour);
    d.fill(x_ + ox, y_ + oy, kPlayer, kPlayer, player, 255, false);
    if (guarding_) {                                      // a ring, not only a colour: the guard's shape cue
        d.circle(x_ + kPlayer / 2 + ox, y_ + kPlayer / 2 + oy, kPlayer, player, 2);
    }
    if (pop_ > 0) {                                       // an eased "hit" ring on the box
        const double e = core::ease(core::Ease::OutBack, 1 - pop_ / kPopS);
        d.circle(kTargetX + kTarget / 2 + ox, kFloorY - kTarget / 2 + oy, 10 + 30 * e, shell_.palette("hit", kHitColour), 2);
    }
    d.rect(cam_.x() - 48 + ox, cam_.y() - 32 + oy, 96, 64, shell_.palette("deadzone", kDeadzoneColour));
    if (flash_ > 0) {
        const double a = flash_peak_ * (flash_ / kFlashS);
        d.fill(0, 0, W, H, shell_.palette("hit", kHitColour), static_cast<Uint8>(std::lround(std::clamp(a, 0.0, 1.0) * 255)), false);
    }
    draw_hud(d);
}

void JuiceDemo::draw_hud(Draw& d) {
    const double W = style::kBaseW;
    TextOpts title;
    title.outline = true;
    title.color = style::kAccent;
    d.text("juice.title", shell_.t("juice.title"), 12, 8, W - 24, d.line_h(), title);
    // the controls with their prompts, wrapping to another row when a language or a large text size makes them long
    const double row = d.line_h() + 4;
    double x = 12;
    double y = 8 + d.line_h() + 4;
    for (const char* action : kHudActions) {
        const std::string key = shell_.prompt(action).second;
        const std::string text = shell_.t(std::string("action.") + action);
        const double kw = d.text_width(key);
        const double aw = d.text_width(text);
        if (x + kw + 6 + aw > W - 12 && x > 12) {
            x = 12;
            y += row + 2;
        }
        TextOpts cap;
        cap.outline = true;
        cap.raw = true;                                   // a key name, not UI copy
        d.text("juice.glyph." + std::string(action), key, x, y, kw + 1, row, cap);
        TextOpts label;
        label.outline = true;
        label.color = style::kDim;
        d.text("juice.action." + std::string(action), text, x + kw + 6, y, aw + 1, row, label);
        x += kw + 6 + aw + 16;
    }
    y += row + 4;
    const std::string stats = shell_.t("juice.stats", {{"hits", std::to_string(hits_)},
                                                       {"trauma", fixed2(shake_.trauma())},
                                                       {"shake", fixed2(core::effective_shake(shell_.settings()))},
                                                       {"refused", std::to_string(refused_)},
                                                       {"speed", std::to_string(std::lround(shell_.game_speed() * 100))}});
    const std::size_t fit = static_cast<std::size_t>(std::max(1, d.chars_fit(W - 24)));
    const double stats_h = static_cast<double>(core::wrap_chars(stats, fit).size()) * d.line_h();
    TextOpts so;
    so.outline = true;
    so.wrap = true;
    so.color = style::kDim;
    d.text("juice.stats", stats, 12, y, W - 24, stats_h, so);
    if (guarding_) {
        TextOpts g;
        g.outline = true;
        g.color = style::kAccent;
        d.text("juice.guard", shell_.t("juice.guard"), 12, y + stats_h, W - 24, d.line_h(), g);
    }
}

}  // namespace shell

// {{FOOTER}}
