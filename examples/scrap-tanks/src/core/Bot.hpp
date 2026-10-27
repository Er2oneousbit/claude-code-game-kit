// ---------------------------------------------------------------------------
// Bot.hpp
// Purpose : Autoplay drivers for the player tank, for scenario checks (SOP-14 step 6).
//           "skilled" fights from cover: holds a hidden spot with the gun pre-aimed, duels one raider
//           at a time, moves when two can see it, picks up scrap when it is safe. "reckless" charges the nearest
//           raider in the open and shoots whenever its gun points at one.
// Usage   : core::Bot bot(core::BotMode::Skilled);  each step: sim.step(bot.think(sim));
// Notes   : Engine-free, so tests/test_scenario.cpp plays both bots over several seeds. The pair
//           tests pillar 1: if the reckless bot also wins, cover does not matter.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <optional>

#include "core/Sim.hpp"

namespace core {

enum class BotMode { Skilled, Reckless };

class Bot {
public:
    explicit Bot(BotMode mode) : mode_(mode) {}
    Control think(Sim& sim);
    BotMode mode() const { return mode_; }
    // What the bot is doing (HIDE, HOLD, DUEL, HUNT, SCRAP, CHARGE): for the debug overlay and logs.
    const char* reason() const { return reason_; }

private:
    Control skilled(Sim& sim);
    Control reckless(Sim& sim);

    BotMode mode_;
    double replan_ = 0.0;
    std::optional<Vec2> goal_;
    std::optional<Vec2> goal_last_;
    const char* reason_ = "";
};

}  // namespace core
