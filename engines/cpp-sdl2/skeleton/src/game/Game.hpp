// ---------------------------------------------------------------------------
// Game.hpp
// Purpose : Top-level game object. Owns the shell (title, menus, settings, pause; src/shell) and the play screen's
//           state, updates it on a fixed step, and draws it. Talks to SDL only for events and rendering.
// Usage   : Game game; game.set_automated(smoke); game.configure(args); game.init(window, renderer);
//           game.handle_event(e); game.update(dt); game.render(renderer);
// Notes   : PROTOTYPE: the play screen is a rectangle bouncing between the walls (it proves the loop works) that
//           jumps (a buffered press plus coyote time, both stretched by access.timing_scale) and guards while
//           interact is held (or toggled, with access.hold_to_toggle). Replace
//           play_update / play_draw / play_action with real systems and keep SDL types out of update() so the
//           simulation stays testable. The shell owns settings.json, the strings (data/i18n) and the dialogue
//           lines (data/dialogue); the game reads them through shell_ (shell_->game_speed(), shell_->palette()).
//           When the game has Dotwork packs (assets/dotwork/*.assets.json), the play screen also shows their art
//           (DotworkShowcase: a map, a label in the font, a prop and a character walking).
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): the shell's screens (#168); the play screen uses the
//           settings (game speed, colour-blind palette, hold to mash, captions) and says the sample line
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): jump and guard use timing_scale and hold_to_toggle (#269)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the Dotwork art on the play screen (#60)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <memory>
#include <string>
#include <vector>

#include "core/CoyoteTimer.hpp"
#include "core/InputBuffer.hpp"
#include "core/MotorAccess.hpp"
#include "core/ShellLogic.hpp"
#include "game/DotworkShowcase.hpp"
#include "shell/Shell.hpp"

namespace game {

class Game {
public:
    Game();
    ~Game();

    // Game options from the command line (everything after `--`). The shell's own (--drive, --data-dir, --locale)
    // are taken here; anything else is the game's (an autoplay mode, cheats, seeds). Logs and returns false on
    // anything unknown; main.cpp then exits 2. options_help() lists them for --help.
    bool configure(const std::vector<std::string>& args);
    static const char* options_help();

    // A headless smoke run: scripted input, no window changes, no speech. Call before init().
    void set_automated(bool on) { options_.automated = on; }

    // Creates the shell once the window and renderer exist. False on a problem that stops the game (logged).
    bool init(SDL_Window* window, SDL_Renderer* renderer);

    // Reacts to one SDL event (quit, keys, gamepad). Sets quit_requested().
    void handle_event(const SDL_Event& event);

    // Advances the simulation by one fixed step (seconds).
    void update(double dt);

    // Draws the current state. main.cpp presents the frame.
    void render(SDL_Renderer* renderer);

    bool quit_requested() const { return shell_ ? shell_->quit_requested() : quit_; }

    // Logical resolution the game draws in; main.cpp scales it to the window
    static constexpr int kWidth = shell::style::kBaseW;
    static constexpr int kHeight = shell::style::kBaseH;

private:
    shell::RunOptions options_;
    std::unique_ptr<shell::Shell> shell_;
    bool quit_ = false;

    // PROTOTYPE: bouncing box state (pixels, pixels per second)
    double x_ = 40.0;
    double y_ = 40.0;
    double vx_ = 160.0;
    double vy_ = 0.0;
    bool on_floor_ = false;
    bool guarding_ = false;
    double hit_t_ = 0.0;                 // seconds left of the hit flash
    core::AutoRepeat repeat_;            // hold to mash (#166)
    core::InputBuffer jump_buffer_;      // a jump pressed just before landing still happens
    core::CoyoteTimer coyote_;           // ... and just after leaving the floor
    core::HeldAction guard_;             // held, or toggled with access.hold_to_toggle (#166)
    DotworkShowcase art_;                // the game's Dotwork art, when it has some (#60)
    static constexpr int kBoxSize = 32;
    static constexpr int kFloorH = 40;
    static constexpr double kHitS = 0.15;
    static constexpr double kGravity = 900.0;     // pixels per second squared
    static constexpr double kJumpSpeed = 340.0;   // pixels per second up (about 64 pixels high)
    static constexpr int kGuardGap = 4;           // the guard frame's distance from the box

    void play_enter();
    void play_update(double dt);
    void play_draw(shell::Draw& draw);
    bool play_action(const std::string& action);
    void hit();
};

}  // namespace game

// {{FOOTER}}
