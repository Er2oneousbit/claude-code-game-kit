// ---------------------------------------------------------------------------
// Game.cpp
// Purpose : Implementation of game::Game (see Game.hpp).
// Usage   : created once in main.cpp; main feeds it events, fixed-step update() calls and render().
// Notes   : PROTOTYPE bouncing box behind the kit's shell. The shell routes Escape (pause) and the menus; the play
//           screen gets the game actions (attack flashes the box, jump hops it, interact guards). Window close quits.
//           Motor access (#166): the jump's input buffer and coyote time are stretched by access.timing_scale, and
//           the guard is held, or toggled with access.hold_to_toggle (core/MotorAccess.hpp). Everything in the
//           world, those windows included, runs on game time (dt times access.game_speed).
//
// Pseudocode (play_update):
//   windows = base * timing_scale; guarding = guard.update(interact held, hold_to_toggle)
//   move sideways, bounce off the walls; fall; land on the floor
//   coyote.update(on floor); buffer.update; can jump and a buffered jump -> jump
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): the shell's screens (#168)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): jump and guard use timing_scale and hold_to_toggle (#269);
//           the new drives in --help (#275)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the game's Dotwork packs load at init and show on the
//           play screen (#60, DotworkShowcase)
// ---------------------------------------------------------------------------
#include "game/Game.hpp"

#include "core/Log.hpp"

namespace game {

namespace {

// ---- Tunables: the play screen's fallback colours when data/access/colours.json lacks one ----
constexpr shell::Rgb kPlayer{242, 191, 76};
constexpr shell::Rgb kHit{255, 76, 64};
constexpr shell::Rgb kFloor{64, 69, 82};
constexpr shell::Rgb kGuard{89, 204, 115};
constexpr const char* kAssetsDir = "assets";   // the game's art (Dotwork packs: assets/dotwork/*.assets.json)

}  // namespace

Game::Game() {
    options_.game_name = "{{GAME_NAME}}";
    options_.game_slug = "{{GAME_SLUG}}";
    options_.version = GAME_VERSION;
}

Game::~Game() = default;

bool Game::configure(const std::vector<std::string>& args) {
    for (std::size_t i = 0; i < args.size(); ++i) {
        const std::string& a = args[i];
        std::string* target = a == "--drive" ? &options_.drive : a == "--data-dir" ? &options_.data_dir
                            : a == "--locale" ? &options_.locale : nullptr;
        if (target) {
            if (i + 1 >= args.size()) {
                LOG_ERROR("game", a << " needs a value (see --help)");
                return false;
            }
            *target = args[++i];
            continue;
        }
        // a game adds its own options here (an autoplay mode, a seed), before this line
        LOG_ERROR("game", "unknown game option: " << a << " (see --help)");
        return false;
    }
    if (!options_.drive.empty() && !options_.automated) {
        LOG_ERROR("game", "--drive runs only in a smoke run (python tools/dev.py smoke --drive " << options_.drive << ")");
        return false;
    }
    return true;
}

const char* Game::options_help() {
    return "  --drive SCENARIO   (smoke) a scripted path through the shell: menus, crash, pseudo, pseudo-plant, bug,\n"
           "                     access[:res=WxH,scale=N,pad,read], show:<title|menu|settings|pause|subtitle|play|juice>;\n"
           "                     dev.py smoke --drive passes it\n"
           "  --data-dir DIR     keep settings.json in this folder (default: the user's preferences folder)\n"
           "  --locale LANG      language for the run (data/i18n/<LANG>.json)\n"
           "  (the game's own options go in Game::configure)\n";
}

bool Game::init(SDL_Window* window, SDL_Renderer* renderer) {
    shell_ = std::make_unique<shell::Shell>(options_);
    shell_->play.enter = [this] { play_enter(); };
    shell_->play.update = [this](double dt) { play_update(dt); };
    shell_->play.draw = [this](shell::Draw& draw) { play_draw(draw); };
    shell_->play.action = [this](const std::string& action) { return play_action(action); };
    if (!shell_->init(window, renderer)) {
        return false;
    }
    art_.load(renderer, shell_->game_dir() / kAssetsDir);   // nothing to show without Dotwork packs
    return true;
}

void Game::handle_event(const SDL_Event& event) {
    if (shell_) {
        shell_->handle_event(event);
    } else if (event.type == SDL_EVENT_QUIT) {
        quit_ = true;
    }
}

void Game::update(double dt) {
    if (shell_) {
        shell_->update(dt);
    }
}

void Game::render(SDL_Renderer* renderer) {
    if (shell_) {
        shell_->render(renderer);
    }
}

// ---- The play screen (PROTOTYPE) -----------------------------------------------------------------------------
void Game::play_enter() {
    jump_buffer_.clear();
    guard_.reset();
    guarding_ = false;
    shell_->set_objective(shell_->t("play.objective"));   // "What now?" on the pause menu (#167)
    shell_->say_line("guide.welcome");                     // the sample line: a subtitle, and the history
}

void Game::hit() {
    hit_t_ = kHitS;
}

bool Game::play_action(const std::string& action) {
    if (action == "attack") {
        hit();
        return true;
    }
    if (action == "jump") {
        jump_buffer_.press("jump");                        // used in play_update once the box can jump
        return true;
    }
    return action == "interact";                           // the guard reads the button itself (play_update)
}

void Game::play_update(double dt) {
    const double step = dt * shell_->game_speed();        // access.game_speed slows the world, not the menus
    if (shell_->access_flag("auto_repeat") && repeat_.update(dt, shell_->is_down("attack"))) {
        hit();                                             // hold to mash (#166)
    }
    hit_t_ = std::max(0.0, hit_t_ - dt);
    // Motor access (#166): longer timing windows, and the guard held or toggled
    const double k = shell_->timing_scale();
    jump_buffer_.set_window(core::scaled_window(core::kInputBufferWindow, k));
    coyote_.set_window(core::scaled_window(core::kCoyoteWindow, k));
    guarding_ = guard_.update(shell_->is_down("interact"), shell_->access_flag("hold_to_toggle"));
    // Move sideways and bounce off the walls; fall and land on the floor.
    x_ += vx_ * step;
    vy_ += kGravity * step;
    y_ += vy_ * step;
    bool bounced = false;
    const double bottom = Game::kHeight - kFloorH - kBoxSize;
    if (x_ < 0.0) { x_ = 0.0; vx_ = -vx_; bounced = true; }
    if (y_ < 0.0) { y_ = 0.0; vy_ = 0.0; }
    if (x_ > kWidth - kBoxSize) { x_ = kWidth - kBoxSize; vx_ = -vx_; bounced = true; }
    const bool was_on_floor = on_floor_;
    on_floor_ = y_ >= bottom;
    if (on_floor_) {
        y_ = bottom;
        vy_ = 0.0;
        bounced = bounced || !was_on_floor;                // a landing thuds too
    }
    // Jump: a press buffered a moment ago, taken while on the floor or just after leaving it
    coyote_.update(step, on_floor_);
    jump_buffer_.update(step);
    if (coyote_.can_jump() && jump_buffer_.consume("jump")) {
        vy_ = -kJumpSpeed;
        coyote_.consume();
    }
    if (bounced) {
        shell_->caption("box_hit");                        // "[thud]" with captions_sfx on
    }
    art_.update(step);
}

void Game::play_draw(shell::Draw& draw) {
    // game content: ui = false, so the access report does not take it for a panel
    draw.fill(0, kHeight - kFloorH, kWidth, kFloorH, shell_->palette("floor", kFloor), 255, false);
    art_.draw(static_cast<float>(kHeight - kFloorH), options_.game_name);   // Dotwork art standing on the floor
    const shell::Rgb box = hit_t_ > 0 ? shell_->palette("hit", kHit) : shell_->palette("player", kPlayer);
    draw.fill(x_, y_, kBoxSize, kBoxSize, box, 255, false);
    if (guarding_) {                                       // a frame, not only a colour: the guard's shape cue
        draw.rect(x_ - kGuardGap, y_ - kGuardGap, kBoxSize + 2 * kGuardGap, kBoxSize + 2 * kGuardGap,
                  shell_->palette("target", kGuard), 2.0);
    }
}

}  // namespace game

// {{FOOTER}}
