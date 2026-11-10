// ---------------------------------------------------------------------------
// Game.cpp
// Purpose : Implementation of game::Game (see Game.hpp).
// Usage   : created once in main.cpp; main feeds it events, fixed-step update() calls and render().
// Notes   : Console markers for dev.py smoke: RUN_START, WAVE_START, RAIDER_DESTROYED, RUN_WON, PLAYER_DESTROYED.
//           With --autoplay the game quits a moment after the fight ends, so a smoke run stops by itself.
//           The shell owns the screens: a new fight starts each time the play screen is entered (play_enter),
//           Escape and Start pause (the shell's "pause" action), R or the pad's Back button restart a fight.
//           Motor access (#166, #269): fire is held, or toggled with access.hold_to_toggle (auto-fire), and a tap
//           made while the gun reloads waits kInputBufferWindow times access.timing_scale for the next shot. The
//           fight has no other timing windows. The left stick goes through shell_->stick() (the player's
//           deadzone and invert_y, #274). The bots' controls skip all of this.
//
// Pseudocode (one frame):
//   update: shell.update -> (play screen on top) play_update: control = bot or player_controls (keyboard + mouse
//           + gamepad, then fire: buffer.update; firing = fire_hold.update(held, hold_to_toggle);
//           a new press -> buffer it when firing, else clear; fire = firing or a buffered tap)
//           -> sim.step, once per update at game speed 1 (speed_acc_ owes whole steps below that)
//           -> a player shot uses up the buffered tap
//           -> sounds, captions and log lines
//   render: shell.render -> (play screen) play_draw: logical presentation to 1280x720 -> ground tiles -> cover,
//           scrap, wrecks and tanks sorted by depth (hull + turret rows from the sprite sheets) -> shells ->
//           intent labels and hp bars over raiders -> HUD -> debug overlay -> presentation back to the shell's
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): Scrap Tanks (sim, bots, sprites, HUD)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): --seed rejects negative and out-of-range numbers
// Updated : 2026-11-10 with Claude (Fable 5.1, claude-fable-5-1): the shell's screens (#168): the fight behind the
//           title and menus, the shell's options, game speed, the attack binding, sound captions, the welcome line
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): kit 0.14.4: fire uses hold_to_toggle and
//           timing_scale (#269), the left stick and right trigger go through the shell's analog input (#274), the
//           seed is named in crash files, the new drives in --help (#275)
// ---------------------------------------------------------------------------
#include "game/Game.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <sstream>

#include "core/EnemyBrain.hpp"
#include "core/Log.hpp"
#include "core/Tuning.hpp"
#include "core/View.hpp"

namespace game {

namespace {

// Tunables: presentation only (gameplay numbers live in src/core/Tuning.hpp)
constexpr double kEndPause = 1.5;           // s an autoplay run lingers on the result before quitting
constexpr int kHudLeft = 200;               // px: the HUD starts right of the shell's "Pause" hint
constexpr int kMessageBottom = 215;         // px above the bottom for the big message, clear of the subtitles
constexpr double kTurretMountHeight = 1.4;  // m: the turret sits on the tractor's cab roof
constexpr double kTurretMountBack = 0.35;   // m behind the hull's origin
constexpr double kShellHeight = 1.0;        // m above ground where shells fly
constexpr double kLabelHeight = 2.6;        // m above a raider for its intent label
constexpr int kPadDeadZone = 8000;          // the right stick (aim); the left stick uses the player's deadzone
constexpr double kTriggerFire = 0.5;        // right trigger travel (0..1, past its own deadzone) that fires
constexpr double kWreckStay = 3.0;         // s a wreck stays fully visible
constexpr double kWreckFade = 2.0;         // s it takes to fade out
constexpr int kGroundInset = 10;          // px trimmed from each side of the 64 px ground tile
constexpr SDL_Color kWhite{251, 247, 238, 255};
constexpr SDL_Color kAttack{255, 77, 77, 255};
constexpr SDL_Color kDefend{127, 178, 255, 255};
constexpr SDL_Color kInk{29, 36, 51, 255};
constexpr SDL_Color kGold{242, 193, 78, 255};

SDL_FRect cell_rect(view::Point at, int cell) {
    const float half = static_cast<float>(cell) / 2.0f;
    return {static_cast<float>(at.x) - half, static_cast<float>(at.y) - half, static_cast<float>(cell),
            static_cast<float>(cell)};
}

void blit_row(SDL_Renderer* r, const Sheet& s, int row, view::Point at) {
    const SDL_FRect src{0.0f, static_cast<float>(row * s.cell), static_cast<float>(s.cell), static_cast<float>(s.cell)};
    const SDL_FRect dst = cell_rect(at, s.cell);
    SDL_RenderTexture(r, s.texture.get(), &src, &dst);
}

void fill(SDL_Renderer* r, SDL_Color c, float x, float y, float w, float h) {
    SDL_SetRenderDrawColor(r, c.r, c.g, c.b, c.a);
    const SDL_FRect rect{x, y, w, h};
    SDL_RenderFillRect(r, &rect);
}

bool is_attack(const std::string& intent) { return intent == "FIRE" || intent == "FLANK"; }

}  // namespace

Game::Game() {
    // main.cpp starts SDL's gamepad subsystem; hot-plug events arrive as SDL_EVENT_GAMEPAD_ADDED
    options_.game_name = "Scrap Tanks";
    options_.game_slug = "scrap_tanks";
    options_.version = GAME_VERSION;
}

Game::~Game() {
    assets_.reset();  // free textures and close audio while SDL is still up
    if (pad_) SDL_CloseGamepad(pad_);
}

const char* Game::options_help() {
    return "  --autoplay skilled|reckless  a bot plays (scenario checks: skilled fights from cover, reckless charges)\n"
           "  --seed N                     fight number N (raider spawns); same seed, same fight\n"
           "  --god                        the player takes no damage\n"
           "  --debug-ai                   draw raider paths, chosen spots, who can hit you, and the bot's reason\n"
           "  --drive SCENARIO   (smoke) a scripted path through the shell: menus, crash, pseudo, pseudo-plant, bug,\n"
           "                     access[:res=WxH,scale=N,pad,read], show:<title|menu|settings|pause|subtitle|play|juice>;\n"
           "                     dev.py smoke --drive passes it\n"
           "  --data-dir DIR     keep settings.json in this folder (default: the user's preferences folder)\n"
           "  --locale LANG      language for the run (data/i18n/<LANG>.json)\n";
}

bool Game::configure(const std::vector<std::string>& args) {
    for (size_t i = 0; i < args.size(); ++i) {
        const std::string& a = args[i];
        const bool has_value = i + 1 < args.size();
        // the shell's options first (the kit's), then the game's
        std::string* shell_opt = a == "--drive" ? &options_.drive : a == "--data-dir" ? &options_.data_dir
                               : a == "--locale" ? &options_.locale : nullptr;
        if (shell_opt) {
            if (!has_value) {
                LOG_ERROR("game", a << " needs a value (see --help)");
                return false;
            }
            *shell_opt = args[++i];
        } else if (a == "--autoplay" && has_value) {
            const std::string& m = args[++i];
            if (m == "skilled") {
                autoplay_ = core::BotMode::Skilled;
            } else if (m == "reckless") {
                autoplay_ = core::BotMode::Reckless;
            } else {
                LOG_ERROR("game", "--autoplay takes skilled or reckless, got: " << m);
                return false;
            }
        } else if (a == "--seed" && has_value) {
            char* end = nullptr;
            const std::string& v = args[++i];
            // strtoull wraps "-1" to 2^64-1 and saturates on overflow: reject both rather than play a surprise seed
            errno = 0;
            const unsigned long long n = std::strtoull(v.c_str(), &end, 10);
            if (v.find('-') != std::string::npos || end == v.c_str() || *end != '\0' || errno == ERANGE) {
                LOG_ERROR("game", "--seed needs a whole number from 0 to 18446744073709551615, got: " << v);
                return false;
            }
            seed_ = n;
            seed_given_ = true;
        } else if (a == "--god") {
            god_ = true;
        } else if (a == "--debug-ai") {
            debug_ai_ = true;
        } else {
            LOG_ERROR("game", "unknown game option: " << a << " (see --help)");
            return false;
        }
    }
    if (!options_.drive.empty() && !options_.automated) {
        LOG_ERROR("game", "--drive runs only in a smoke run (python tools/dev.py smoke --drive " << options_.drive << ")");
        return false;
    }
    return true;
}

bool Game::init(SDL_Window* window, SDL_Renderer* renderer) {
    renderer_ = renderer;
    shell_ = std::make_unique<shell::Shell>(options_);
    shell_->play.enter = [this] { play_enter(); };
    shell_->play.update = [this](double dt) { play_update(dt); };
    shell_->play.draw = [this](shell::Draw& draw) { play_draw(draw); };
    shell_->play.action = [this](const std::string& action) { return play_action(action); };
    return shell_->init(window, renderer);
}

bool Game::playing() const {
    const shell::Screen* top = shell_ ? shell_->top() : nullptr;
    return top && top->id == shell::ScreenId::Play;
}

// Entering the play screen (from the main menu, each time) starts a fresh fight
void Game::play_enter() {
    shell_->set_objective(shell_->t("play.objective"));   // "What now?" on the pause menu
    shell_->say_line("yard.welcome");                      // the radio's welcome: a subtitle, and the history
    restart();
}

void Game::restart() {
    // A new seed per human restart, the given seed for the first run (and every autoplay run)
    const std::uint64_t seed = (runs_ == 0 || seed_given_) ? seed_ : seed_ + static_cast<std::uint64_t>(runs_);
    sim_ = std::make_unique<core::Sim>(seed, god_);
    bot_.reset();
    if (autoplay_) bot_.emplace(*autoplay_);
    end_timer_ = 0.0;
    fire_hold_.reset();                    // a new fight starts with the gun quiet, even with auto-fire on
    fire_buffer_.clear();
    fire_was_held_ = false;
    shell_->set_run_seed(std::to_string(seed));   // named in crash files and bug reports (#275)
    ++runs_;
    LOG_INFO("game", "RUN_START seed=" << seed << (autoplay_ ? (*autoplay_ == core::BotMode::Skilled ? " autoplay=skilled" : " autoplay=reckless") : "")
                                       << (god_ ? " god" : ""));
}

void Game::handle_event(const SDL_Event& event) {
    // The shell first: quit, its menus, pause (Escape, Start) and the bindings (shell_->is_down)
    if (shell_) {
        shell_->handle_event(event);
    } else if (event.type == SDL_EVENT_QUIT) {
        quit_ = true;
    }
    switch (event.type) {
        case SDL_EVENT_KEY_DOWN:
            if (event.key.key == SDLK_R && !event.key.repeat && playing()) restart();
            break;
        case SDL_EVENT_MOUSE_MOTION:  // main.cpp converts every event to the shell's render space; the fight's is 2x
            mouse_x_ = event.motion.x * kViewScale;
            mouse_y_ = event.motion.y * kViewScale;
            pad_used_ = false;
            break;
        case SDL_EVENT_MOUSE_BUTTON_DOWN:
        case SDL_EVENT_MOUSE_BUTTON_UP:
            if (event.button.button == SDL_BUTTON_LEFT) mouse_fire_ = event.type == SDL_EVENT_MOUSE_BUTTON_DOWN;
            break;
        case SDL_EVENT_GAMEPAD_ADDED:  // the shell opens it too: SDL counts the opens, so both closes are needed
            if (!pad_) pad_ = SDL_OpenGamepad(event.gdevice.which);
            break;
        case SDL_EVENT_GAMEPAD_REMOVED:
            if (pad_ && !SDL_GamepadConnected(pad_)) {
                SDL_CloseGamepad(pad_);
                pad_ = nullptr;
            }
            break;
        case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
            pad_used_ = true;
            // Start is the shell's pause; Back restarts the fight
            if (event.gbutton.button == SDL_GAMEPAD_BUTTON_BACK && playing()) restart();
            break;
        default:
            break;
    }
}

bool Game::play_action(const std::string& action) {
    (void)action;   // the fight reads its controls each step (read_controls); nothing is used as a press
    return false;
}

core::Control Game::read_controls() const {
    const core::Tank& me = sim_->player();
    core::Control c;
    const bool* keys = SDL_GetKeyboardState(nullptr);
    c.throttle = (keys[SDL_SCANCODE_W] || keys[SDL_SCANCODE_UP] ? 1.0 : 0.0) -
                 (keys[SDL_SCANCODE_S] || keys[SDL_SCANCODE_DOWN] ? 1.0 : 0.0);
    c.turn = (keys[SDL_SCANCODE_D] || keys[SDL_SCANCODE_RIGHT] ? 1.0 : 0.0) -
             (keys[SDL_SCANCODE_A] || keys[SDL_SCANCODE_LEFT] ? 1.0 : 0.0);
    c.aim = view::to_world(mouse_x_, mouse_y_ + kTurretMountHeight * view::kHeight * view::kPixelsPerMeter);
    c.fire = mouse_fire_ || keys[SDL_SCANCODE_SPACE] || shell_->is_down("attack");   // the rebindable attack too
    // Left stick: the shell's analog input (#274), so the Stick deadzone and Invert vertical stick settings apply.
    // Its length is 0..1 past the deadzone: half a lean drives and turns at half speed. +y is down (forward is up).
    const core::analog::Vec2 stick = shell_->stick();   // the kit's analog type, not the game's core::Vec2
    if (stick.x != 0.0 || stick.y != 0.0) {
        c.turn = stick.x;
        c.throttle = -stick.y;
    }
    c.fire = c.fire || shell_->right_trigger() > kTriggerFire;
    if (pad_) {
        const auto axis = [this](SDL_GamepadAxis a) {
            const int v = SDL_GetGamepadAxis(pad_, a);
            return std::abs(v) < kPadDeadZone ? 0.0 : v / 32767.0;
        };
        const double rx = axis(SDL_GAMEPAD_AXIS_RIGHTX);
        const double ry = axis(SDL_GAMEPAD_AXIS_RIGHTY);
        if (rx != 0.0 || ry != 0.0) c.aim = me.pos + core::normalized({rx, ry / view::kDepth}) * 8.0;
        else if (pad_used_) c.aim = me.pos + core::from_angle(me.turret) * 8.0;  // keep the gun where it is
        c.fire = c.fire || SDL_GetGamepadButton(pad_, SDL_GAMEPAD_BUTTON_SOUTH);
    }
    return c;
}

// The player's controls for one sim step: the devices, then motor access on fire (#166, #269).
//   Hold mode (default): fire while the button is held, as before; a tap made while the gun reloads still fires
//   when it is ready, if that is within the buffer window (kInputBufferWindow times access.timing_scale).
//   Toggle mode (access.hold_to_toggle): one press starts auto-fire, the next stops it.
core::Control Game::player_controls() {
    core::Control c = read_controls();
    const bool held = c.fire;
    fire_buffer_.set_window(core::scaled_window(core::kInputBufferWindow, shell_->timing_scale()));
    fire_buffer_.update(tuning::kStep);    // the buffer runs on sim time, like the reload it waits for
    const bool firing = fire_hold_.update(held, shell_->access_flag("hold_to_toggle"));
    if (held && !fire_was_held_) {
        if (firing) {
            fire_buffer_.press("fire");
        } else {
            fire_buffer_.clear();          // the press that toggled auto-fire off: no stray shot after it
        }
    }
    fire_was_held_ = held;
    c.fire = firing || fire_buffer_.pending("fire");
    return c;
}

void Game::update(double dt) {
    if (shell_) shell_->update(dt);   // runs play_update while the play screen is on top
}

void Game::play_update(double dt) {
    if (!sim_) restart();
    if (sim_->outcome() != core::Outcome::Playing) {
        end_timer_ += dt;
        if (autoplay_ && end_timer_ >= kEndPause) quit_ = true;  // smoke runs stop by themselves
        return;
    }
    // The sim's step is fixed, so a slower game speed (access.game_speed, 0.5 to 1) skips whole steps: at 1 it
    // is exactly one step per update, as before the shell
    speed_acc_ += shell_->game_speed();
    while (speed_acc_ >= 1.0 && sim_->outcome() == core::Outcome::Playing) {
        speed_acc_ -= 1.0;
        const core::Control control = bot_ ? bot_->think(*sim_) : player_controls();
        on_events(sim_->step(control));
    }
}

void Game::on_events(const std::vector<core::Event>& events) {
    for (const core::Event& e : events) {
        switch (e.type) {
            case core::EventType::WaveStart:
                LOG_INFO("game", "WAVE_START " << e.a << "/" << core::Sim::waves_total() << " raiders=" << sim_->raiders_alive());
                break;
            case core::EventType::Fire:
                if (e.team == core::Team::Player) fire_buffer_.consume("fire");   // the buffered tap is spent
                if (assets_) assets_->play(e.team == core::Team::Player ? "fire_player" : "fire_raider", 40);
                shell_->caption(e.team == core::Team::Player ? "fire_player" : "fire_raider");   // with captions_sfx on
                break;
            case core::EventType::Hit:
                if (assets_) assets_->play("hit", 50);
                shell_->caption("hit");
                LOG_DEBUG("game", "hit tank " << e.a);
                break;
            case core::EventType::TankDestroyed:
                if (assets_) assets_->play("destroyed", 70);
                shell_->caption("destroyed");
                if (e.team == core::Team::Raider) LOG_INFO("game", "RAIDER_DESTROYED id=" << e.a << " left=" << sim_->raiders_alive());
                break;
            case core::EventType::Pickup:
                if (assets_) assets_->play("pickup", 60);
                shell_->caption("pickup");
                LOG_INFO("game", "SCRAP_PICKUP hp=" << static_cast<int>(sim_->player().hp));
                break;
            case core::EventType::RunWon:
                if (!best_time_ || sim_->time() < *best_time_) best_time_ = sim_->time();
                LOG_INFO("game", "RUN_WON time=" << static_cast<int>(sim_->time()) << "s hp=" << static_cast<int>(sim_->player().hp));
                break;
            case core::EventType::PlayerDestroyed:
                LOG_INFO("game", "PLAYER_DESTROYED wave=" << sim_->wave() << " time=" << static_cast<int>(sim_->time()) << "s");
                break;
        }
    }
}

void Game::render(SDL_Renderer* r) {
    if (!assets_ && !assets_failed_) {   // on the first frame, so a missing file fails the boot, not the first fight
        assets_ = std::make_unique<Assets>();
        if (!assets_->load(r)) {
            assets_failed_ = true;
            quit_ = true;  // Assets logged what is missing
        }
    }
    if (shell_) shell_->render(r);   // the screens; the play screen calls play_draw
}

// The play screen: the fight in its own 1280x720 space, then the presentation goes back to the shell's 640x360
// for the pause hint, subtitles and the pause menu drawn over it. The shell's Draw records nothing here: the
// fight is game content, not a panel (the access sweep sees the shell's outlined hint).
void Game::play_draw(shell::Draw& draw) {
    (void)draw;
    SDL_Renderer* r = renderer_;
    SDL_SetRenderLogicalPresentation(r, kViewW, kViewH, SDL_LOGICAL_PRESENTATION_LETTERBOX);
    SDL_SetRenderDrawBlendMode(r, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(r, 47, 58, 44, 255);
    SDL_RenderClear(r);
    if (sim_ && assets_ && assets_->loaded()) {
        draw_world(r);
        if (debug_ai_) draw_debug(r);
        draw_hud(r);
    }
    SDL_SetRenderLogicalPresentation(r, kWidth, kHeight, SDL_LOGICAL_PRESENTATION_LETTERBOX);
}

void Game::draw_world(SDL_Renderer* r) {
    const core::Arena& arena = sim_->arena();
    // Ground: the tile seen from above, squashed into the camera's depth
    const Sheet& ground = assets_->sheet("ground");
    // Only the tile's inner area: its beveled rim would draw a dark grid when scaled down
    const SDL_FRect inner{static_cast<float>(kGroundInset), static_cast<float>(kGroundInset),
                          static_cast<float>(ground.cell - 2 * kGroundInset), static_cast<float>(ground.cell - 2 * kGroundInset)};
    SDL_SetTextureScaleMode(ground.texture.get(), SDL_SCALEMODE_LINEAR);
    // Integer edges taken from the next tile's position, so neighbours always meet (no 1 px seams)
    for (int y = 0; y < static_cast<int>(arena.bounds.max_y); ++y) {
        for (int x = 0; x < static_cast<int>(arena.bounds.max_x); ++x) {
            const view::Point a = view::to_screen({static_cast<double>(x), static_cast<double>(y)});
            const view::Point b = view::to_screen({x + 1.0, y + 1.0});
            const int x0 = static_cast<int>(std::floor(a.x));
            const int y0 = static_cast<int>(std::floor(a.y));
            const SDL_FRect dst{static_cast<float>(x0), static_cast<float>(y0),
                                static_cast<float>(static_cast<int>(std::floor(b.x)) - x0),
                                static_cast<float>(static_cast<int>(std::floor(b.y)) - y0)};
            SDL_RenderTexture(r, ground.texture.get(), &inner, &dst);
        }
    }

    // Everything that stands on the ground, back to front
    struct Item {
        double depth;
        int kind;  // 0 cover, 1 scrap, 2 tank
        size_t index;
    };
    std::vector<Item> items;
    for (size_t i = 0; i < arena.cover.size(); ++i) items.push_back({arena.cover[i].shape.c.y, 0, i});
    for (size_t i = 0; i < sim_->scrap().size(); ++i) {
        if (!sim_->scrap()[i].taken) items.push_back({sim_->scrap()[i].pos.y - 0.5, 1, i});
    }
    for (size_t i = 0; i < sim_->tanks().size(); ++i) items.push_back({sim_->tanks()[i].pos.y, 2, i});
    std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) { return a.depth < b.depth; });

    for (const Item& it : items) {
        if (it.kind == 0) {
            const core::Cover& c = arena.cover[it.index];
            blit_row(r, assets_->sheet(core::cover_name(c.kind)), 0, view::to_screen(c.shape.c));
        } else if (it.kind == 1) {
            const core::Scrap& s = sim_->scrap()[it.index];
            blit_row(r, assets_->sheet(it.index % 2 ? "scrap_tire" : "scrap_plate"), 0, view::to_screen(s.pos));
        } else {
            draw_tank(r, sim_->tanks()[it.index]);
        }
    }

    const Sheet& shell = assets_->sheet("shell");
    for (const core::Shell& s : sim_->shells()) blit_row(r, shell, 0, view::to_screen(s.pos, kShellHeight));

    // Intent labels and hp bars over the raiders (pillar 2: read the raiders)
    for (const core::Tank& t : sim_->tanks()) {
        if (t.team != core::Team::Raider || !t.alive) continue;
        const view::Point p = view::to_screen(t.pos, kLabelHeight);
        fill(r, {kInk.r, kInk.g, kInk.b, 190}, static_cast<float>(p.x) - 42, static_cast<float>(p.y) - 24, 84, 22);
        draw_text(r, t.intent, 16, is_attack(t.intent) ? kAttack : kDefend, p.x, p.y - 22, true);
        const float w = 44.0f;
        fill(r, kInk, static_cast<float>(p.x) - w / 2, static_cast<float>(p.y), w, 5);
        fill(r, is_attack(t.intent) ? kAttack : kDefend, static_cast<float>(p.x) - w / 2, static_cast<float>(p.y),
             w * static_cast<float>(t.hp / t.spec->max_hp), 5);
    }

    // Crosshair for mouse play
    if (!autoplay_ && !pad_used_ && sim_->outcome() == core::Outcome::Playing) {
        SDL_SetRenderDrawColor(r, kWhite.r, kWhite.g, kWhite.b, 200);
        const float mx = static_cast<float>(mouse_x_);
        const float my = static_cast<float>(mouse_y_);
        SDL_RenderLine(r, mx - 9, my, mx - 3, my);
        SDL_RenderLine(r, mx + 3, my, mx + 9, my);
        SDL_RenderLine(r, mx, my - 9, mx, my - 3);
        SDL_RenderLine(r, mx, my + 3, mx, my + 9);
    }
}

void Game::draw_tank(SDL_Renderer* r, const core::Tank& t) {
    const bool player = t.team == core::Team::Player;
    const Sheet& hull = assets_->sheet(player ? "hull_player" : (t.kind == core::TankKind::Heavy ? "hull_heavy" : "hull_enemy"));
    const Sheet& turret = assets_->sheet(player ? "turret_player" : "turret_enemy");
    if (!t.alive) {  // wreck: darkened hull, no turret, fading out so the yard stays readable
        const double age = sim_->time() - t.destroyed_at;
        const double fade = 1.0 - core::clamp((age - kWreckStay) / kWreckFade, 0.0, 1.0);
        if (fade <= 0.0) return;
        SDL_SetTextureColorMod(hull.texture.get(), 70, 70, 70);
        SDL_SetTextureAlphaMod(hull.texture.get(), static_cast<Uint8>(255 * fade));
        blit_row(r, hull, view::sheet_row(t.heading, hull.rows), view::to_screen(t.pos));
        SDL_SetTextureColorMod(hull.texture.get(), 255, 255, 255);
        SDL_SetTextureAlphaMod(hull.texture.get(), 255);
        return;
    }
    blit_row(r, hull, view::sheet_row(t.heading, hull.rows), view::to_screen(t.pos));
    const core::Vec2 mount = t.pos - core::from_angle(t.heading) * kTurretMountBack;
    // The turret models face the other way in their files (yaw offset pi, see core/View.hpp)
    blit_row(r, turret, view::sheet_row(t.turret, turret.rows, core::kPi), view::to_screen(mount, kTurretMountHeight));
}

void Game::draw_hud(SDL_Renderer* r) {
    // The bar's left end is the shell's: it draws "Esc  Pause" there (over the game, outlined)
    fill(r, {kInk.r, kInk.g, kInk.b, 215}, 0, 0, kViewW, 44);
    const core::Tank& me = sim_->player();
    const float x0 = kHudLeft;
    draw_text(r, "HP", 22, kWhite, x0, 9, false);
    fill(r, {60, 66, 80, 255}, x0 + 44, 15, 220, 14);
    const double f = me.hp / me.spec->max_hp;
    fill(r, f > 0.35 ? kGold : kAttack, x0 + 44, 15, static_cast<float>(220 * f), 14);
    std::ostringstream wave;
    wave << "WAVE " << std::max(1, sim_->wave()) << "/" << core::Sim::waves_total() << "    RAIDERS " << sim_->raiders_alive();
    draw_text(r, wave.str(), 22, kWhite, x0 + 290, 9, false);
    if (best_time_) {
        std::ostringstream best;
        best << "BEST " << static_cast<int>(*best_time_) << " S";
        draw_text(r, best.str(), 16, kGold, x0 + 680, 13, false);
    }
    draw_text(r, std::string("v") + GAME_VERSION, 16, kWhite, kViewW - 70, 13, false);

    std::string msg;
    std::string sub;
    if (sim_->outcome() == core::Outcome::Won) {
        std::ostringstream m;
        m << "SCRAPYARD CLEARED IN " << static_cast<int>(sim_->time()) << " S";
        msg = m.str();
        sub = "PRESS R TO GO AGAIN";
    } else if (sim_->outcome() == core::Outcome::Destroyed) {
        msg = "DESTROYED";
        sub = "PRESS R TO TRY AGAIN";
    } else if (sim_->time() < 4.0 && !autoplay_) {
        msg = "WASD DRIVE   MOUSE AIM   CLICK FIRE";
        sub = "STAY IN COVER. RED LABELS ARE COMING FOR YOU, BLUE ONES ARE HIDING.";
    } else if (sim_->raiders_alive() == 0 && sim_->wave() < core::Sim::waves_total()) {
        msg = "NEXT WAVE INCOMING";
    }
    if (!msg.empty()) {   // above the shell's subtitle strip at the bottom
        const float top = kViewH - kMessageBottom;
        fill(r, {kInk.r, kInk.g, kInk.b, 200}, kViewW / 2.0f - 380, top, 760, 84);
        draw_text(r, msg, 34, kWhite, kViewW / 2.0, top + 6, true);
        if (!sub.empty()) draw_text(r, sub, 16, kWhite, kViewW / 2.0, top + 52, true);
    }
}

void Game::draw_debug(SDL_Renderer* r) {
    const core::Tank& me = sim_->player();
    for (const core::Tank& t : sim_->tanks()) {
        if (t.team != core::Team::Raider || !t.alive) continue;
        // Path and chosen spot
        SDL_SetRenderDrawColor(r, 255, 59, 212, 255);
        view::Point a = view::to_screen(t.pos);
        for (const core::Vec2& p : t.path) {
            const view::Point b = view::to_screen(p);
            SDL_RenderLine(r, static_cast<float>(a.x), static_cast<float>(a.y), static_cast<float>(b.x), static_cast<float>(b.y));
            a = b;
        }
        if (t.has_spot) {
            const view::Point s = view::to_screen(t.spot);
            const SDL_FRect box{static_cast<float>(s.x) - 4, static_cast<float>(s.y) - 4, 8, 8};
            SDL_RenderRect(r, &box);
        }
        // Who can hit the player right now
        if (sim_->can_hit(t.pos, me.pos)) {
            SDL_SetRenderDrawColor(r, kAttack.r, kAttack.g, kAttack.b, 160);
            const view::Point p = view::to_screen(t.pos, 1.0);
            const view::Point q = view::to_screen(me.pos, 1.0);
            SDL_RenderLine(r, static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(q.x), static_cast<float>(q.y));
        }
    }
    if (bot_) {
        const view::Point p = view::to_screen(me.pos, kLabelHeight);
        draw_text(r, std::string("BOT ") + bot_->reason(), 16, kGold, p.x, p.y - 22, true);
    }
    std::istringstream tree(core::raider_tree_text());
    std::string line;
    double y = 60;
    while (std::getline(tree, line)) {
        draw_text(r, line, 16, kWhite, 12, y, false);
        y += 18;
    }
}

void Game::draw_text(SDL_Renderer* r, const std::string& s, int size, SDL_Color c, double x, double y, bool centered) {
    if (s.empty()) return;
    const Text& t = assets_->text(r, s, size, c);
    if (!t.texture) return;
    const float left = static_cast<float>(centered ? x - t.w / 2.0 : x);
    const SDL_FRect dst{left, static_cast<float>(y), static_cast<float>(t.w), static_cast<float>(t.h)};
    SDL_RenderTexture(r, t.texture.get(), nullptr, &dst);
}

}  // namespace game
