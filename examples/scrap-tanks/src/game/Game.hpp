// ---------------------------------------------------------------------------
// Game.hpp
// Purpose : Top-level game object: owns the kit's shell (title, menus, settings, pause; src/shell) and runs one
//           core::Sim as its play screen, feeding it keyboard, mouse and gamepad input (or an autoplay bot), and
//           drawing it with the rendered sprites, HUD and sounds.
// Usage   : Game game; game.set_automated(smoke); game.configure(args); game.init(window, renderer);
//           game.handle_event(e); game.update(dt); game.render(renderer);
// Notes   : Game options come after `--` (see options_help); the shell's own (--drive, --data-dir, --locale) are
//           taken first. All rules and AI live in src/core; this file only reads input, draws and plays sounds.
//           Assets load on the first render. The shell draws in its 640x360 design space (shell::style); the
//           fight keeps its own 1280x720 space (kViewW x kViewH): play_draw switches the logical presentation for
//           the game's frame and back, and mouse coordinates arrive in the shell's space (kViewScale).
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): Scrap Tanks (sim, bots, sprites, HUD)
// Updated : 2026-11-10 with Claude (Fable 5.1, claude-fable-5-1): the shell's screens (#168): the fight is the play
//           screen behind the title, menus and pause; the settings' game speed, attack binding and captions apply
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): kit 0.14.4: fire honours access.hold_to_toggle
//           (auto-fire) and buffers a tap made while reloading for kInputBufferWindow times access.timing_scale
//           (#269); the left stick drives through shell_->stick() (the player's deadzone and invert_y, #274); the
//           run's seed goes into crash files and bug reports (#275)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "core/Bot.hpp"
#include "core/InputBuffer.hpp"
#include "core/MotorAccess.hpp"
#include "core/Sim.hpp"
#include "game/Assets.hpp"
#include "shell/Shell.hpp"

namespace game {

class Game {
public:
    Game();
    ~Game();

    // Game options from the command line (everything after `--`). The shell's own (--drive, --data-dir, --locale)
    // are taken here; the rest are the game's (autoplay, seed, cheats). Logs and returns false on anything
    // unknown; main.cpp then exits 2. options_help() lists them for --help.
    bool configure(const std::vector<std::string>& args);
    static const char* options_help();

    // A headless smoke run: scripted input, no window changes, no speech. Call before init().
    void set_automated(bool on) { options_.automated = on; }

    // Creates the shell once the window and renderer exist. False on a problem that stops the game (logged).
    bool init(SDL_Window* window, SDL_Renderer* renderer);

    // Reacts to one SDL event (quit, restart, mouse, gamepad hot-plug); the shell gets every event first.
    void handle_event(const SDL_Event& event);

    // Advances the shell and, when the play screen is on top, the simulation by one fixed step (seconds).
    void update(double dt);

    // Draws the current state (loads the assets on the first call). main.cpp presents the frame.
    void render(SDL_Renderer* renderer);

    bool quit_requested() const { return quit_ || (shell_ && shell_->quit_requested()); }

    // Logical resolution main.cpp presents: the shell's design space, scaled to the window
    static constexpr int kWidth = shell::style::kBaseW;
    static constexpr int kHeight = shell::style::kBaseH;
    // The fight's own space (the sprites were rendered for it); the play screen draws in it
    static constexpr int kViewW = 1280;
    static constexpr int kViewH = 720;
    static constexpr double kViewScale = static_cast<double>(kViewW) / kWidth;   // shell px -> view px

private:
    void restart();
    bool playing() const;                 // the play screen is on top (no menu over it)
    core::Control read_controls() const;  // the devices as they are now (keyboard, mouse, pad)
    core::Control player_controls();      // read_controls plus motor access on fire (toggle, buffered tap)
    void on_events(const std::vector<core::Event>& events);
    void play_enter();
    void play_update(double dt);
    void play_draw(shell::Draw& draw);
    bool play_action(const std::string& action);
    void draw_world(SDL_Renderer* r);
    void draw_tank(SDL_Renderer* r, const core::Tank& t);
    void draw_hud(SDL_Renderer* r);
    void draw_debug(SDL_Renderer* r);
    void draw_text(SDL_Renderer* r, const std::string& s, int size, SDL_Color c, double x, double y, bool centered);

    // Options
    shell::RunOptions options_;
    std::optional<core::BotMode> autoplay_;
    std::uint64_t seed_ = 1;
    bool seed_given_ = false;
    bool god_ = false;
    bool debug_ai_ = false;

    std::unique_ptr<shell::Shell> shell_;
    SDL_Renderer* renderer_ = nullptr;    // the play screen draws through it (play_draw)
    bool quit_ = false;
    bool assets_failed_ = false;
    std::unique_ptr<Assets> assets_;
    std::unique_ptr<core::Sim> sim_;
    std::optional<core::Bot> bot_;
    double end_timer_ = 0.0;
    double speed_acc_ = 0.0;              // access.game_speed: whole sim steps owed (the sim's step is fixed)
    int runs_ = 0;
    std::optional<double> best_time_;

    // Input state
    double mouse_x_ = kViewW / 2.0;
    double mouse_y_ = kViewH / 2.0;
    bool mouse_fire_ = false;
    bool pad_used_ = false;
    SDL_Gamepad* pad_ = nullptr;

    // Motor access on fire (#166, #269): held, or toggled on and off with access.hold_to_toggle (auto-fire); a tap
    // made while the gun reloads is kept for kInputBufferWindow times access.timing_scale and fires when it can
    core::HeldAction fire_hold_;
    core::InputBuffer fire_buffer_;
    bool fire_was_held_ = false;          // the devices' fire last sim step, to find a new press
};

}  // namespace game
