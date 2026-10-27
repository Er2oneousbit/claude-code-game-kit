// ---------------------------------------------------------------------------
// Game.hpp
// Purpose : Top-level game object. Owns game state, updates it on a fixed step,
//           and draws it. Talks to SDL only for events and rendering.
// Usage   : Game game; game.handle_event(e); game.update(dt); game.render(renderer);
// Notes   : PROTOTYPE: a rectangle bouncing around proves the loop works.
//           Replace with real systems. Keep SDL types out of update() so the
//           simulation stays testable.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL.h>

#include <string>
#include <vector>

namespace game {

class Game {
public:
    // Game options from the command line (everything after `--`, e.g. an autoplay mode). Logs and returns
    // false on anything unknown; main.cpp then exits 2. options_help() lists them for --help.
    bool configure(const std::vector<std::string>& args);
    static const char* options_help();

    // Reacts to one SDL event (quit, key presses). Sets quit_requested().
    void handle_event(const SDL_Event& event);

    // Advances the simulation by one fixed step (seconds).
    void update(double dt);

    // Draws the current state. Never mutates game state. main.cpp presents the frame.
    void render(SDL_Renderer* renderer) const;

    bool quit_requested() const { return quit_; }

    // Logical resolution the game draws in; main.cpp scales it to the window
    static constexpr int kWidth = 640;
    static constexpr int kHeight = 360;

private:
    bool quit_ = false;

    // PROTOTYPE: bouncing box state (pixels, pixels per second)
    double x_ = 40.0;
    double y_ = 40.0;
    double vx_ = 160.0;
    double vy_ = 110.0;
    static constexpr int kBoxSize = 32;
};

}  // namespace game

// {{FOOTER}}
