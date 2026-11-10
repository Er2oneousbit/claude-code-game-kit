// ---------------------------------------------------------------------------
// Game.cpp
// Purpose : Implementation of game::Game (see Game.hpp).
// Usage   : created once in main.cpp; main feeds it events, fixed-step update() calls and render().
// Notes   : PROTOTYPE bouncing box behind the kit's shell. The shell routes Escape (pause) and the menus; the play
//           screen gets the game actions (attack flashes the box). Window close quits.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): the shell's screens (#168)
// ---------------------------------------------------------------------------
#include "game/Game.hpp"

#include "core/Log.hpp"

namespace game {

namespace {

// ---- Tunables: the play screen's fallback colours when data/access/colours.json lacks one ----
constexpr shell::Rgb kPlayer{242, 191, 76};
constexpr shell::Rgb kHit{255, 76, 64};
constexpr shell::Rgb kFloor{64, 69, 82};

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
    return "  --drive SCENARIO   (smoke) a scripted path through the shell: menus, access[:res=WxH,scale=N,pad,read],\n"
           "                     show:<title|menu|settings|pause|subtitle|play>; dev.py smoke --drive passes it\n"
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
    return shell_->init(window, renderer);
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
    return false;
}

void Game::play_update(double dt) {
    const double step = dt * shell_->game_speed();        // access.game_speed slows the world, not the menus
    if (shell_->access_flag("auto_repeat") && repeat_.update(dt, shell_->is_down("attack"))) {
        hit();                                             // hold to mash (#166)
    }
    hit_t_ = std::max(0.0, hit_t_ - dt);
    // Move, then bounce off the walls by flipping velocity and clamping position.
    x_ += vx_ * step;
    y_ += vy_ * step;
    bool bounced = false;
    const double bottom = Game::kHeight - kFloorH - kBoxSize;
    if (x_ < 0.0) { x_ = 0.0; vx_ = -vx_; bounced = true; }
    if (y_ < 0.0) { y_ = 0.0; vy_ = -vy_; bounced = true; }
    if (x_ > kWidth - kBoxSize) { x_ = kWidth - kBoxSize; vx_ = -vx_; bounced = true; }
    if (y_ > bottom) { y_ = bottom; vy_ = -vy_; bounced = true; }
    if (bounced) {
        shell_->caption("box_hit");                        // "[thud]" with captions_sfx on
    }
}

void Game::play_draw(shell::Draw& draw) {
    // game content: ui = false, so the access report does not take it for a panel
    draw.fill(0, kHeight - kFloorH, kWidth, kFloorH, shell_->palette("floor", kFloor), 255, false);
    const shell::Rgb box = hit_t_ > 0 ? shell_->palette("hit", kHit) : shell_->palette("player", kPlayer);
    draw.fill(x_, y_, kBoxSize, kBoxSize, box, 255, false);
}

}  // namespace game

// {{FOOTER}}
