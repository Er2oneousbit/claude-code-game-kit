// ---------------------------------------------------------------------------
// Game.hpp
// Purpose : Top-level game object: runs one core::Sim, feeds it keyboard, mouse and gamepad input
//           (or an autoplay bot), and draws it with the rendered sprites, HUD and sounds.
// Usage   : Game game; game.configure(args); game.handle_event(e); game.update(dt); game.render(renderer);
// Notes   : Game options come after `--` (see options_help). All rules and AI live in src/core; this
//           file only reads input, draws and plays sounds. Assets load on the first render.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): Scrap Tanks (sim, bots, sprites, HUD)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "core/Bot.hpp"
#include "core/Sim.hpp"
#include "game/Assets.hpp"

namespace game {

class Game {
public:
    Game();
    ~Game();

    // Game options from the command line (everything after `--`). Logs and returns false on anything
    // unknown; main.cpp then exits 2. options_help() lists them for --help.
    bool configure(const std::vector<std::string>& args);
    static const char* options_help();

    // Reacts to one SDL event (quit, restart, mouse, gamepad hot-plug).
    void handle_event(const SDL_Event& event);

    // Advances the simulation by one fixed step (seconds).
    void update(double dt);

    // Draws the current state (loads the assets on the first call). main.cpp presents the frame.
    void render(SDL_Renderer* renderer);

    bool quit_requested() const { return quit_; }

    // Logical resolution the game draws in; main.cpp scales it to the window
    static constexpr int kWidth = 1280;
    static constexpr int kHeight = 720;

private:
    void restart();
    core::Control read_controls() const;
    void on_events(const std::vector<core::Event>& events);
    void draw_world(SDL_Renderer* r);
    void draw_tank(SDL_Renderer* r, const core::Tank& t);
    void draw_hud(SDL_Renderer* r);
    void draw_debug(SDL_Renderer* r);
    void draw_text(SDL_Renderer* r, const std::string& s, int size, SDL_Color c, double x, double y, bool centered);

    // Options
    std::optional<core::BotMode> autoplay_;
    std::uint64_t seed_ = 1;
    bool seed_given_ = false;
    bool god_ = false;
    bool debug_ai_ = false;

    bool quit_ = false;
    bool assets_failed_ = false;
    std::unique_ptr<Assets> assets_;
    std::unique_ptr<core::Sim> sim_;
    std::optional<core::Bot> bot_;
    double end_timer_ = 0.0;
    int runs_ = 0;
    std::optional<double> best_time_;

    // Input state
    double mouse_x_ = kWidth / 2.0;
    double mouse_y_ = kHeight / 2.0;
    bool mouse_fire_ = false;
    bool pad_used_ = false;
    SDL_GameController* pad_ = nullptr;
};

}  // namespace game
