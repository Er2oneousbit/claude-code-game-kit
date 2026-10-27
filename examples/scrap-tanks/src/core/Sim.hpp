// ---------------------------------------------------------------------------
// Sim.hpp
// Purpose : One fight in the scrapyard, engine-free: tanks (player and raiders), shells, scrap,
//           waves and the outcome. The game draws it; tests play it.
// Usage   : core::Sim sim(seed);  each fixed step: auto events = sim.step(control);
//           control comes from the keyboard, a bot (core/Bot.hpp) or nothing.
// Notes   : Fixed step (tuning::kStep) and one seeded RNG: the same seed and inputs give the same fight
//           on every machine, so `--autoplay` runs and tests/test_scenario.cpp agree exactly.
//           Raiders are driven by the behavior tree in core/EnemyBrain.cpp, ticked every kThinkEvery.
//
// Pseudocode (step):
//   raiders: think on their timer (behavior tree -> Control)
//   every tank: drive (throttle/turn, or follow an A* path to Control.goal), turn turret to Control.aim,
//               fire if asked (raiders: only when aimed and the shot is clear)
//   shells: move; stop at cover or the edge; damage tanks of the other team
//   destroyed raiders drop scrap; the player picks it up to repair
//   waves: when no raider is left, pause, then spawn the next; after the last: won
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "core/Arena.hpp"
#include "core/Nav.hpp"
#include "core/Rng.hpp"
#include "core/Tuning.hpp"

namespace core {

enum class Team { Player, Raider };
enum class TankKind { Player, Scout, Heavy };

// What a driver wants this step: tank controls (throttle, turn) or a goal to drive to, plus aim and fire.
struct Control {
    double throttle = 0.0;  // -1..1
    double turn = 0.0;      // -1..1, positive = clockwise on screen
    bool use_goal = false;  // drive along an A* path to `goal` instead of throttle/turn
    Vec2 goal;
    Vec2 aim;               // world point the turret turns toward
    bool fire = false;
    double aim_tolerance = -1.0;  // >= 0: fire only when the turret is within this many radians of `aim`
};

struct Tank {
    int id = 0;
    TankKind kind = TankKind::Player;
    Team team = Team::Player;
    const tuning::TankSpec* spec = &tuning::kPlayer;
    Vec2 pos;
    Vec2 vel;               // m/s, measured (for aim leading)
    double heading = 0.0;   // hull, radians
    double speed = 0.0;     // signed, along the heading
    double turret = 0.0;    // radians, world space
    double hp = 0.0;
    double reload = 0.0;    // s until the next shot
    bool alive = true;
    double destroyed_at = 0.0;  // sim time of death (wrecks fade in the game)
    Control control;
    // Navigation state
    std::vector<Vec2> path;
    Vec2 path_goal;
    double repath = 0.0;
    // Raider brain state (core/EnemyBrain.cpp)
    std::string intent;     // active behavior-tree action: shown over the tank
    double think = 0.0;
    bool retreating = false;
    bool retreat_used = false;  // one retreat per life, so fights end
    bool has_spot = false;
    Vec2 spot;
    double spot_age = 0.0;
};

struct Shell {
    Vec2 pos;
    Vec2 vel;
    Team team = Team::Player;
    double damage = 0.0;
    double life = 0.0;
};

struct Scrap {
    Vec2 pos;
    bool taken = false;
};

enum class Outcome { Playing, Won, Destroyed };
enum class EventType { WaveStart, Fire, Hit, TankDestroyed, Pickup, RunWon, PlayerDestroyed };

struct Event {
    EventType type;
    int a = 0;              // wave number, tank id, ...
    Team team = Team::Player;
};

class Sim {
public:
    explicit Sim(std::uint64_t seed, bool god = false);

    std::vector<Event> step(const Control& player_control);

    const Arena& arena() const { return arena_; }
    const std::vector<Circle>& blockers() const { return blockers_; }
    const NavGrid& nav() const { return nav_; }
    Tank& player() { return tanks_.front(); }
    const Tank& player() const { return tanks_.front(); }
    std::vector<Tank>& tanks() { return tanks_; }
    const std::vector<Tank>& tanks() const { return tanks_; }
    const std::vector<Shell>& shells() const { return shells_; }
    const std::vector<Scrap>& scrap() const { return scrap_; }
    Outcome outcome() const { return outcome_; }
    int wave() const { return wave_; }  // 1-based wave in progress (0 before the first)
    static int waves_total() { return static_cast<int>(tuning::kWaves.size()); }
    double time() const { return time_; }
    int raiders_alive() const;
    bool god() const { return god_; }

    // Can a tank at `from` see `to`? Within sight range and no cover in between.
    bool sees(Vec2 from, Vec2 to) const;
    // Would a shell from `from` reach `to` without hitting cover?
    bool clear_shot(Vec2 from, Vec2 to) const;
    // A real threat: in sight range with a clear shot (seeing past a crate edge is not enough to hit).
    bool can_hit(Vec2 from, Vec2 to) const { return distance(from, to) <= tuning::kSightRange && clear_shot(from, to); }

private:
    void spawn_wave(std::vector<Event>& events);
    void drive(Tank& t, double dt);
    void follow_path(Tank& t, double dt);
    void try_fire(Tank& t, std::vector<Event>& events);
    void update_shells(double dt, std::vector<Event>& events);
    void separate_tanks();

    const Arena& arena_;
    std::vector<Circle> blockers_;
    NavGrid nav_;
    Rng rng_;
    bool god_;
    std::vector<Tank> tanks_;
    std::vector<Shell> shells_;
    std::vector<Scrap> scrap_;
    Outcome outcome_ = Outcome::Playing;
    int wave_ = 0;
    double wave_timer_ = tuning::kWavePause;
    double time_ = 0.0;
    int next_id_ = 1;
};

}  // namespace core
