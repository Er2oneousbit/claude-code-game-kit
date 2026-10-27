// ---------------------------------------------------------------------------
// Tuning.hpp
// Purpose : Every number that defines how Scrap Tanks plays, in one place (GDD "Tunables").
// Usage   : #include "core/Tuning.hpp"  then  tuning::kPlayer.speed, tuning::kWaves, ...
// Notes   : Units: meters, seconds, radians, hit points. After a change run `python tools/dev.py test`:
//           the scenario tests say whether the cover-using bot still wins and the charging bot still
//           loses (pillar 1: cover is life).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <array>

#include "core/Math.hpp"

namespace tuning {

constexpr double kStep = 1.0 / 60.0;  // simulation step, seconds
constexpr double kDeg = core::kPi / 180.0;

struct TankSpec {
    double max_hp;
    double speed;          // m/s forward
    double reverse_speed;  // m/s backward
    double accel;          // m/s^2
    double turn_rate;      // hull, rad/s
    double turret_rate;    // rad/s
    double reload;         // s between shots
    double shell_speed;    // m/s
    double damage;         // hp per hit
    double range;          // m, how far it chooses to shoot from (raiders)
};

constexpr double kTankRadius = 0.95;       // collision circle of every tank
constexpr double kMuzzle = 1.1;            // shells start this far from the tank center
constexpr double kShellRadius = 0.15;
constexpr double kShellLife = 2.5;         // s

constexpr TankSpec kPlayer{100.0, 5.0, 3.0, 14.0, 2.6, 4.5, 0.75, 20.0, 25.0, 0.0};
constexpr TankSpec kScout{40.0, 4.0, 2.5, 10.0, 2.2, 3.0, 1.6, 14.0, 14.0, 13.0};
constexpr TankSpec kHeavy{100.0, 2.6, 1.8, 6.0, 1.4, 2.0, 2.2, 13.0, 22.0, 12.0};

// Raider behavior tree thresholds (ADR 0002)
constexpr double kSightRange = 22.0;         // m; tanks see all around, cover blocks the view
constexpr double kRetreatBelow = 0.35;       // fraction of max hp that starts a retreat
constexpr double kRecoverTo = 0.7;           // ... and the fraction that ends it
constexpr double kRegenPerSecond = 9.0;      // hp/s while retreating out of sight
constexpr double kAimTolerance = 5.0 * kDeg; // fire when the turret is this close to the target
constexpr double kThinkEvery = 0.2;          // s between behavior-tree ticks per raider
constexpr double kRepathEvery = 0.5;         // s between path searches
constexpr double kSpotSpread = 4.0;          // m two raiders keep between their chosen spots (flanking)

// Scrap: dropped by destroyed raiders, repairs the player
constexpr double kScrapHeal = 20.0;
constexpr double kScrapRadius = 1.1;         // pickup distance

// Waves: scouts and heavies per wave, a pause between them
struct Wave {
    int scouts;
    int heavies;
};
constexpr std::array<Wave, 3> kWaves{{{3, 0}, {4, 0}, {3, 1}}};
constexpr double kWavePause = 2.5;           // s

}  // namespace tuning
