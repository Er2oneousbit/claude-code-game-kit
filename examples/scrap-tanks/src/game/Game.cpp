// ---------------------------------------------------------------------------
// Game.cpp
// Purpose : Implementation of game::Game (see Game.hpp).
// Usage   : created once in main.cpp; main feeds it events, fixed-step update() calls and render().
// Notes   : Console markers for dev.py smoke: WAVE_START, RAIDER_DESTROYED, RUN_WON, PLAYER_DESTROYED.
//           With --autoplay the game quits a moment after the fight ends, so a smoke run stops by itself.
//
// Pseudocode (one frame):
//   update: control = bot or (keyboard + mouse + gamepad) -> sim.step -> sounds and log lines
//   render: ground tiles -> cover, scrap, wrecks and tanks sorted by depth (hull + turret rows from the
//           sprite sheets) -> shells -> intent labels and hp bars over raiders -> HUD -> debug overlay
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): Scrap Tanks (sim, bots, sprites, HUD)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): --seed rejects negative and out-of-range numbers
// ---------------------------------------------------------------------------
#include "game/Game.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <sstream>

#include "core/EnemyBrain.hpp"
#include "core/Log.hpp"
#include "core/View.hpp"

namespace game {

namespace {

// Tunables: presentation only (gameplay numbers live in src/core/Tuning.hpp)
constexpr double kEndPause = 1.5;           // s an autoplay run lingers on the result before quitting
constexpr double kTurretMountHeight = 1.4;  // m: the turret sits on the tractor's cab roof
constexpr double kTurretMountBack = 0.35;   // m behind the hull's origin
constexpr double kShellHeight = 1.0;        // m above ground where shells fly
constexpr double kLabelHeight = 2.6;        // m above a raider for its intent label
constexpr int kPadDeadZone = 8000;
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
    const SDL_Rect src{0, row * s.cell, s.cell, s.cell};
    const SDL_FRect dst = cell_rect(at, s.cell);
    SDL_RenderCopyF(r, s.texture.get(), &src, &dst);
}

void fill(SDL_Renderer* r, SDL_Color c, float x, float y, float w, float h) {
    SDL_SetRenderDrawColor(r, c.r, c.g, c.b, c.a);
    const SDL_FRect rect{x, y, w, h};
    SDL_RenderFillRectF(r, &rect);
}

bool is_attack(const std::string& intent) { return intent == "FIRE" || intent == "FLANK"; }

}  // namespace

Game::Game() {
    SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER);  // hot-plug events arrive as SDL_CONTROLLERDEVICEADDED
}

Game::~Game() {
    assets_.reset();  // free textures and close audio before the controller subsystem
    if (pad_) SDL_GameControllerClose(pad_);
    SDL_QuitSubSystem(SDL_INIT_GAMECONTROLLER);
}

const char* Game::options_help() {
    return "  --autoplay skilled|reckless  a bot plays (scenario checks: skilled fights from cover, reckless charges)\n"
           "  --seed N                     fight number N (raider spawns); same seed, same fight\n"
           "  --god                        the player takes no damage\n"
           "  --debug-ai                   draw raider paths, chosen spots, who can hit you, and the bot's reason\n";
}

bool Game::configure(const std::vector<std::string>& args) {
    for (size_t i = 0; i < args.size(); ++i) {
        const std::string& a = args[i];
        const bool has_value = i + 1 < args.size();
        if (a == "--autoplay" && has_value) {
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
    restart();
    return true;
}

void Game::restart() {
    // A new seed per human restart, the given seed for the first run (and every autoplay run)
    const std::uint64_t seed = (runs_ == 0 || seed_given_) ? seed_ : seed_ + static_cast<std::uint64_t>(runs_);
    sim_ = std::make_unique<core::Sim>(seed, god_);
    bot_.reset();
    if (autoplay_) bot_.emplace(*autoplay_);
    end_timer_ = 0.0;
    ++runs_;
    LOG_INFO("game", "RUN_START seed=" << seed << (autoplay_ ? (*autoplay_ == core::BotMode::Skilled ? " autoplay=skilled" : " autoplay=reckless") : "")
                                       << (god_ ? " god" : ""));
}

void Game::handle_event(const SDL_Event& event) {
    switch (event.type) {
        case SDL_QUIT:
            quit_ = true;
            break;
        case SDL_KEYDOWN:
            if (event.key.keysym.sym == SDLK_ESCAPE) quit_ = true;
            if (event.key.keysym.sym == SDLK_r && !event.key.repeat) restart();
            break;
        case SDL_MOUSEMOTION:  // logical coordinates: SDL scales mouse events with the logical size
            mouse_x_ = event.motion.x;
            mouse_y_ = event.motion.y;
            pad_used_ = false;
            break;
        case SDL_MOUSEBUTTONDOWN:
        case SDL_MOUSEBUTTONUP:
            if (event.button.button == SDL_BUTTON_LEFT) mouse_fire_ = event.type == SDL_MOUSEBUTTONDOWN;
            break;
        case SDL_CONTROLLERDEVICEADDED:
            if (!pad_) pad_ = SDL_GameControllerOpen(event.cdevice.which);
            break;
        case SDL_CONTROLLERDEVICEREMOVED:
            if (pad_ && SDL_GameControllerGetAttached(pad_) == SDL_FALSE) {
                SDL_GameControllerClose(pad_);
                pad_ = nullptr;
            }
            break;
        case SDL_CONTROLLERBUTTONDOWN:
            pad_used_ = true;
            if (event.cbutton.button == SDL_CONTROLLER_BUTTON_START) restart();
            break;
        default:
            break;
    }
}

core::Control Game::read_controls() const {
    const core::Tank& me = sim_->player();
    core::Control c;
    const Uint8* keys = SDL_GetKeyboardState(nullptr);
    c.throttle = (keys[SDL_SCANCODE_W] || keys[SDL_SCANCODE_UP] ? 1.0 : 0.0) -
                 (keys[SDL_SCANCODE_S] || keys[SDL_SCANCODE_DOWN] ? 1.0 : 0.0);
    c.turn = (keys[SDL_SCANCODE_D] || keys[SDL_SCANCODE_RIGHT] ? 1.0 : 0.0) -
             (keys[SDL_SCANCODE_A] || keys[SDL_SCANCODE_LEFT] ? 1.0 : 0.0);
    c.aim = view::to_world(mouse_x_, mouse_y_ + kTurretMountHeight * view::kHeight * view::kPixelsPerMeter);
    c.fire = mouse_fire_ || keys[SDL_SCANCODE_SPACE];
    if (pad_) {
        const auto axis = [this](SDL_GameControllerAxis a) {
            const int v = SDL_GameControllerGetAxis(pad_, a);
            return std::abs(v) < kPadDeadZone ? 0.0 : v / 32767.0;
        };
        const double lx = axis(SDL_CONTROLLER_AXIS_LEFTX);
        const double ly = axis(SDL_CONTROLLER_AXIS_LEFTY);
        if (lx != 0.0 || ly != 0.0) {
            c.turn = lx;
            c.throttle = -ly;
        }
        const double rx = axis(SDL_CONTROLLER_AXIS_RIGHTX);
        const double ry = axis(SDL_CONTROLLER_AXIS_RIGHTY);
        if (rx != 0.0 || ry != 0.0) c.aim = me.pos + core::normalized({rx, ry / view::kDepth}) * 8.0;
        else if (pad_used_) c.aim = me.pos + core::from_angle(me.turret) * 8.0;  // keep the gun where it is
        c.fire = c.fire || SDL_GameControllerGetAxis(pad_, SDL_CONTROLLER_AXIS_TRIGGERRIGHT) > 16000 ||
                 SDL_GameControllerGetButton(pad_, SDL_CONTROLLER_BUTTON_A);
    }
    return c;
}

void Game::update(double dt) {
    if (!sim_) restart();
    if (sim_->outcome() != core::Outcome::Playing) {
        end_timer_ += dt;
        if (autoplay_ && end_timer_ >= kEndPause) quit_ = true;  // smoke runs stop by themselves
        return;
    }
    const core::Control control = bot_ ? bot_->think(*sim_) : read_controls();
    on_events(sim_->step(control));
}

void Game::on_events(const std::vector<core::Event>& events) {
    for (const core::Event& e : events) {
        switch (e.type) {
            case core::EventType::WaveStart:
                LOG_INFO("game", "WAVE_START " << e.a << "/" << core::Sim::waves_total() << " raiders=" << sim_->raiders_alive());
                break;
            case core::EventType::Fire:
                if (assets_) assets_->play(e.team == core::Team::Player ? "fire_player" : "fire_raider", 40);
                break;
            case core::EventType::Hit:
                if (assets_) assets_->play("hit", 50);
                LOG_DEBUG("game", "hit tank " << e.a);
                break;
            case core::EventType::TankDestroyed:
                if (assets_) assets_->play("destroyed", 70);
                if (e.team == core::Team::Raider) LOG_INFO("game", "RAIDER_DESTROYED id=" << e.a << " left=" << sim_->raiders_alive());
                break;
            case core::EventType::Pickup:
                if (assets_) assets_->play("pickup", 60);
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
    if (!assets_ && !assets_failed_) {
        assets_ = std::make_unique<Assets>();
        if (!assets_->load(r)) {
            assets_failed_ = true;
            quit_ = true;  // Assets logged what is missing
        }
    }
    SDL_SetRenderDrawBlendMode(r, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(r, 47, 58, 44, 255);
    SDL_RenderClear(r);
    if (!sim_ || !assets_ || !assets_->loaded()) return;
    draw_world(r);
    if (debug_ai_) draw_debug(r);
    draw_hud(r);
}

void Game::draw_world(SDL_Renderer* r) {
    const core::Arena& arena = sim_->arena();
    // Ground: the tile seen from above, squashed into the camera's depth
    const Sheet& ground = assets_->sheet("ground");
    // Only the tile's inner area: its beveled rim would draw a dark grid when scaled down
    const SDL_Rect inner{kGroundInset, kGroundInset, ground.cell - 2 * kGroundInset, ground.cell - 2 * kGroundInset};
    SDL_SetTextureScaleMode(ground.texture.get(), SDL_ScaleModeLinear);
    // Integer edges taken from the next tile's position, so neighbours always meet (no 1 px seams)
    for (int y = 0; y < static_cast<int>(arena.bounds.max_y); ++y) {
        for (int x = 0; x < static_cast<int>(arena.bounds.max_x); ++x) {
            const view::Point a = view::to_screen({static_cast<double>(x), static_cast<double>(y)});
            const view::Point b = view::to_screen({x + 1.0, y + 1.0});
            const int x0 = static_cast<int>(std::floor(a.x));
            const int y0 = static_cast<int>(std::floor(a.y));
            const SDL_Rect dst{x0, y0, static_cast<int>(std::floor(b.x)) - x0, static_cast<int>(std::floor(b.y)) - y0};
            SDL_RenderCopy(r, ground.texture.get(), &inner, &dst);
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
        SDL_RenderDrawLineF(r, mx - 9, my, mx - 3, my);
        SDL_RenderDrawLineF(r, mx + 3, my, mx + 9, my);
        SDL_RenderDrawLineF(r, mx, my - 9, mx, my - 3);
        SDL_RenderDrawLineF(r, mx, my + 3, mx, my + 9);
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
    fill(r, {kInk.r, kInk.g, kInk.b, 215}, 0, 0, kWidth, 44);
    const core::Tank& me = sim_->player();
    draw_text(r, "HP", 22, kWhite, 20, 9, false);
    fill(r, {60, 66, 80, 255}, 64, 15, 220, 14);
    const double f = me.hp / me.spec->max_hp;
    fill(r, f > 0.35 ? kGold : kAttack, 64, 15, static_cast<float>(220 * f), 14);
    std::ostringstream wave;
    wave << "WAVE " << std::max(1, sim_->wave()) << "/" << core::Sim::waves_total() << "    RAIDERS " << sim_->raiders_alive();
    draw_text(r, wave.str(), 22, kWhite, 310, 9, false);
    if (best_time_) {
        std::ostringstream best;
        best << "BEST " << static_cast<int>(*best_time_) << " S";
        draw_text(r, best.str(), 16, kGold, 700, 13, false);
    }
    draw_text(r, std::string("v") + GAME_VERSION, 16, kWhite, kWidth - 70, 13, false);

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
    if (!msg.empty()) {
        fill(r, {kInk.r, kInk.g, kInk.b, 200}, kWidth / 2.0f - 380, kHeight - 104, 760, 84);
        draw_text(r, msg, 34, kWhite, kWidth / 2.0, kHeight - 98, true);
        if (!sub.empty()) draw_text(r, sub, 16, kWhite, kWidth / 2.0, kHeight - 52, true);
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
            SDL_RenderDrawLineF(r, static_cast<float>(a.x), static_cast<float>(a.y), static_cast<float>(b.x), static_cast<float>(b.y));
            a = b;
        }
        if (t.has_spot) {
            const view::Point s = view::to_screen(t.spot);
            const SDL_FRect box{static_cast<float>(s.x) - 4, static_cast<float>(s.y) - 4, 8, 8};
            SDL_RenderDrawRectF(r, &box);
        }
        // Who can hit the player right now
        if (sim_->can_hit(t.pos, me.pos)) {
            SDL_SetRenderDrawColor(r, kAttack.r, kAttack.g, kAttack.b, 160);
            const view::Point p = view::to_screen(t.pos, 1.0);
            const view::Point q = view::to_screen(me.pos, 1.0);
            SDL_RenderDrawLineF(r, static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(q.x), static_cast<float>(q.y));
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
    SDL_RenderCopyF(r, t.texture.get(), nullptr, &dst);
}

}  // namespace game
