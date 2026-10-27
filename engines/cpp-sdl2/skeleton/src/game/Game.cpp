// ---------------------------------------------------------------------------
// Game.cpp
// Purpose : Implementation of game::Game (see Game.hpp).
// Usage   : created once in main.cpp; main feeds it events, fixed-step update() calls and render().
// Notes   : PROTOTYPE bouncing box. Escape or window close quits.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
#include "game/Game.hpp"

#include "core/Log.hpp"

namespace game {

bool Game::configure(const std::vector<std::string>& args) {
    if (!args.empty()) {
        LOG_ERROR("game", "unknown game option: " << args.front() << " (see --help)");
        return false;
    }
    return true;
}

const char* Game::options_help() {
    return "  (none yet: add them in Game::configure)\n";
}

void Game::handle_event(const SDL_Event& event) {
    switch (event.type) {
        case SDL_QUIT:
            quit_ = true;
            break;
        case SDL_KEYDOWN:
            if (event.key.keysym.sym == SDLK_ESCAPE) {
                quit_ = true;
            }
            break;
        default:
            break;
    }
}

void Game::update(double dt) {
    // Move, then bounce off the walls by flipping velocity and clamping position.
    x_ += vx_ * dt;
    y_ += vy_ * dt;
    if (x_ < 0.0) { x_ = 0.0; vx_ = -vx_; }
    if (y_ < 0.0) { y_ = 0.0; vy_ = -vy_; }
    if (x_ > kWidth - kBoxSize)  { x_ = kWidth - kBoxSize;  vx_ = -vx_; }
    if (y_ > kHeight - kBoxSize) { y_ = kHeight - kBoxSize; vy_ = -vy_; }
}

void Game::render(SDL_Renderer* renderer) const {
    SDL_SetRenderDrawColor(renderer, 18, 18, 24, 255);
    SDL_RenderClear(renderer);

    SDL_SetRenderDrawColor(renderer, 240, 200, 80, 255);
    const SDL_Rect box{static_cast<int>(x_), static_cast<int>(y_), kBoxSize, kBoxSize};
    SDL_RenderFillRect(renderer, &box);
}

}  // namespace game

// {{FOOTER}}
