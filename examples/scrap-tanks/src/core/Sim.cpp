// ---------------------------------------------------------------------------
// Sim.cpp
// Purpose : Implementation of core::Sim (see Sim.hpp for the step order).
// Usage   : owned by game::Game and by the tests; one Sim per fight.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): no-path fallback in follow_path, cover that a
//           shell reaches first now stops it before the tank behind (Fable review)
// ---------------------------------------------------------------------------
#include "core/Sim.hpp"

#include <algorithm>
#include <cmath>

#include "core/EnemyBrain.hpp"

namespace core {

namespace {
constexpr double kArrive = 0.6;       // m: a path point counts as reached
constexpr double kGoalSlack = 1.0;    // m: a goal that moved less than this keeps the old path
constexpr double kFirstWaveDelay = 1.5;

// Where (0..1) the segment from -> to first leaves `r`; `from` is inside.
double bounds_exit_t(const Rect& r, Vec2 from, Vec2 to) {
    double t = 1.0;
    const auto axis = [&t](double a, double b, double lo, double hi) {
        if (b > hi && b != a) t = std::min(t, (hi - a) / (b - a));
        if (b < lo && b != a) t = std::min(t, (lo - a) / (b - a));
    };
    axis(from.x, to.x, r.min_x, r.max_x);
    axis(from.y, to.y, r.min_y, r.max_y);
    return std::max(0.0, t);
}
}  // namespace

Sim::Sim(std::uint64_t seed, bool god)
    : arena_(scrapyard()),
      blockers_(arena_.blockers()),
      nav_(arena_.bounds, blockers_, 0.5, tuning::kTankRadius + 0.05, arena_.player_start),
      rng_(seed),
      god_(god),
      wave_timer_(kFirstWaveDelay) {
    Tank p;
    p.id = 0;
    p.kind = TankKind::Player;
    p.team = Team::Player;
    p.spec = &tuning::kPlayer;
    p.pos = arena_.player_start;
    p.heading = arena_.player_heading;
    p.turret = p.heading;
    p.hp = p.spec->max_hp;
    p.control.aim = p.pos + from_angle(p.heading) * 5.0;
    tanks_.push_back(p);
}

int Sim::raiders_alive() const {
    return static_cast<int>(std::count_if(tanks_.begin(), tanks_.end(),
                                          [](const Tank& t) { return t.team == Team::Raider && t.alive; }));
}

bool Sim::sees(Vec2 from, Vec2 to) const {
    return distance(from, to) <= tuning::kSightRange && line_of_sight(from, to, blockers_);
}

bool Sim::clear_shot(Vec2 from, Vec2 to) const {
    return line_of_sight(from, to, blockers_, tuning::kShellRadius);
}

std::vector<Event> Sim::step(const Control& player_control) {
    std::vector<Event> events;
    if (outcome_ != Outcome::Playing) return events;
    const double dt = tuning::kStep;
    time_ += dt;
    player().control = player_control;

    // Raiders think on their own timers (behavior tree -> Control)
    for (Tank& t : tanks_) {
        if (t.team != Team::Raider || !t.alive) continue;
        t.think -= dt;
        if (t.think <= 0.0) {
            t.think = tuning::kThinkEvery;
            think_raider(*this, t);
        }
    }

    for (Tank& t : tanks_) {
        if (!t.alive) continue;
        const Vec2 before = t.pos;
        drive(t, dt);
        t.vel = (t.pos - before) * (1.0 / dt);
        t.turret = turn_toward(t.turret, angle_of(t.control.aim - t.pos), t.spec->turret_rate * dt);
        t.reload = std::max(0.0, t.reload - dt);
        const bool aimed = t.control.aim_tolerance < 0.0 ||
                           std::abs(wrap_angle(angle_of(t.control.aim - t.pos) - t.turret)) <= t.control.aim_tolerance;
        if (t.control.fire && aimed) try_fire(t, events);
        // Raiders heal while retreating out of the player's sight
        if (t.team == Team::Raider && t.retreating && !sees(player().pos, t.pos)) {
            t.hp = std::min(t.spec->max_hp, t.hp + tuning::kRegenPerSecond * dt);
        }
    }
    separate_tanks();
    update_shells(dt, events);

    // Scrap repairs the player
    Tank& p = player();
    for (Scrap& s : scrap_) {
        if (!s.taken && p.alive && distance(s.pos, p.pos) < tuning::kScrapRadius && p.hp < p.spec->max_hp) {
            s.taken = true;
            p.hp = std::min(p.spec->max_hp, p.hp + tuning::kScrapHeal);
            events.push_back({EventType::Pickup, 0});
        }
    }

    if (!p.alive) {
        outcome_ = Outcome::Destroyed;
        events.push_back({EventType::PlayerDestroyed, 0});
        return events;
    }
    if (raiders_alive() == 0) {
        if (wave_ >= waves_total()) {
            outcome_ = Outcome::Won;
            events.push_back({EventType::RunWon, wave_});
        } else {
            wave_timer_ -= dt;
            if (wave_timer_ <= 0.0) {
                spawn_wave(events);
                wave_timer_ = tuning::kWavePause;
            }
        }
    }
    return events;
}

void Sim::spawn_wave(std::vector<Event>& events) {
    const tuning::Wave& w = tuning::kWaves[static_cast<size_t>(wave_)];
    ++wave_;
    // Shuffle the spawn points (Fisher-Yates on the project RNG), then fill them in order
    std::vector<Vec2> spawns = arena_.spawns;
    for (int i = static_cast<int>(spawns.size()) - 1; i > 0; --i) {
        std::swap(spawns[static_cast<size_t>(i)], spawns[static_cast<size_t>(rng_.below(i + 1))]);
    }
    int slot = 0;
    const auto add = [&](TankKind kind, const tuning::TankSpec* spec) {
        Tank t;
        t.id = next_id_++;
        t.kind = kind;
        t.team = Team::Raider;
        t.spec = spec;
        t.pos = spawns[static_cast<size_t>(slot++ % static_cast<int>(spawns.size()))];
        t.heading = angle_of(player().pos - t.pos);
        t.turret = t.heading;
        t.hp = spec->max_hp;
        t.think = rng_.range(0.0, tuning::kThinkEvery);  // spread brain ticks over frames
        t.control.aim = player().pos;
        tanks_.push_back(t);
    };
    for (int i = 0; i < w.heavies; ++i) add(TankKind::Heavy, &tuning::kHeavy);
    for (int i = 0; i < w.scouts; ++i) add(TankKind::Scout, &tuning::kScout);
    events.push_back({EventType::WaveStart, wave_});
}

void Sim::drive(Tank& t, double dt) {
    const Control& c = t.control;
    double want_speed = 0.0;
    if (c.use_goal) {
        follow_path(t, dt);
        return;
    }
    t.heading = wrap_angle(t.heading + clamp(c.turn, -1.0, 1.0) * t.spec->turn_rate * dt);
    const double throttle = clamp(c.throttle, -1.0, 1.0);
    want_speed = throttle >= 0.0 ? throttle * t.spec->speed : throttle * t.spec->reverse_speed;
    const double dv = clamp(want_speed - t.speed, -t.spec->accel * dt, t.spec->accel * dt);
    t.speed += dv;
    const Vec2 next = move_circle(t.pos, from_angle(t.heading) * (t.speed * dt), tuning::kTankRadius, blockers_,
                                  arena_.bounds);
    // Pushing into cover eats speed, so a tank does not keep "stored" momentum against a wall
    if (distance(next, t.pos) < std::abs(t.speed * dt) * 0.5) t.speed *= 0.5;
    t.pos = next;
}

void Sim::follow_path(Tank& t, double dt) {
    const Vec2 goal = t.control.goal;
    t.repath -= dt;
    if (t.path.empty() || t.repath <= 0.0 || distance(goal, t.path_goal) > kGoalSlack) {
        t.path = nav_.find_path(t.pos, goal);
        // No grid path (the tank or the goal sits on a nav island): drive straight at the goal and let
        // move_circle slide along cover, instead of standing still until the goal changes
        if (t.path.empty()) t.path = {goal};
        t.path_goal = goal;
        t.repath = tuning::kRepathEvery;
    }
    while (t.path.size() > 1 && distance(t.pos, t.path.front()) < kArrive) t.path.erase(t.path.begin());
    double want_speed = 0.0;
    if (!t.path.empty() && distance(t.pos, t.path.front()) >= kArrive * 0.5) {
        const double want_heading = angle_of(t.path.front() - t.pos);
        t.heading = turn_toward(t.heading, want_heading, t.spec->turn_rate * dt);
        // Tank drive: full speed when facing the way, slow while turning, stop to turn around
        const double facing = std::cos(wrap_angle(want_heading - t.heading));
        want_speed = facing > 0.0 ? t.spec->speed * facing : 0.0;
        // Ease in on the final point
        if (t.path.size() == 1) want_speed = std::min(want_speed, distance(t.pos, t.path.front()) * 2.0);
    }
    const double dv = clamp(want_speed - t.speed, -t.spec->accel * dt, t.spec->accel * dt);
    t.speed += dv;
    t.pos = move_circle(t.pos, from_angle(t.heading) * (t.speed * dt), tuning::kTankRadius, blockers_, arena_.bounds);
}

void Sim::try_fire(Tank& t, std::vector<Event>& events) {
    if (t.reload > 0.0) return;
    const Vec2 dir = from_angle(t.turret);
    const Vec2 muzzle = t.pos + dir * tuning::kMuzzle;
    if (!line_of_sight(t.pos, muzzle, blockers_, tuning::kShellRadius)) return;  // barrel inside cover
    Shell s;
    s.pos = muzzle;
    s.vel = dir * t.spec->shell_speed;
    s.team = t.team;
    s.damage = t.spec->damage;
    s.life = tuning::kShellLife;
    shells_.push_back(s);
    t.reload = t.spec->reload;
    events.push_back({EventType::Fire, t.id, t.team});
}

void Sim::update_shells(double dt, std::vector<Event>& events) {
    for (Shell& s : shells_) {
        const Vec2 from = s.pos;
        const Vec2 to = s.pos + s.vel * dt;
        s.life -= dt;
        // Cover and the arena edge stop shells (pillar 1): stop_t is where along this step's segment
        // the first of them is reached (2 = not this step)
        double stop_t = 2.0;
        if (!inside(arena_.bounds, to)) stop_t = bounds_exit_t(arena_.bounds, from, to);
        for (const Circle& b : blockers_) {
            const double bt = segment_circle_t(from, to, b, tuning::kShellRadius);
            if (bt >= 0.0) stop_t = std::min(stop_t, bt);
        }
        // The first tank of the other team on the shell's path takes the hit, unless cover came first
        // (a tank hugging a crate is shielded even when both fall inside one step)
        Tank* hit = nullptr;
        double hit_t = stop_t;
        for (Tank& t : tanks_) {
            if (!t.alive || t.team == s.team) continue;
            const double ht = segment_circle_t(from, to, {t.pos, tuning::kTankRadius}, tuning::kShellRadius);
            if (ht >= 0.0 && ht < hit_t) {
                hit_t = ht;
                hit = &t;
            }
        }
        if (hit) {
            if (!(hit->team == Team::Player && god_)) hit->hp -= s.damage;
            events.push_back({EventType::Hit, hit->id, hit->team});
            if (hit->hp <= 0.0) {
                hit->alive = false;
                hit->hp = 0.0;
                hit->destroyed_at = time_;
                events.push_back({EventType::TankDestroyed, hit->id, hit->team});
                if (hit->team == Team::Raider) scrap_.push_back({hit->pos});
            }
            s.life = 0.0;
        } else if (stop_t <= 1.0) {
            s.life = 0.0;
        }
        s.pos = to;
    }
    shells_.erase(std::remove_if(shells_.begin(), shells_.end(), [](const Shell& s) { return s.life <= 0.0; }),
                  shells_.end());
}

void Sim::separate_tanks() {
    for (size_t i = 0; i < tanks_.size(); ++i) {
        for (size_t j = i + 1; j < tanks_.size(); ++j) {
            Tank& a = tanks_[i];
            Tank& b = tanks_[j];
            if (!a.alive || !b.alive) continue;
            const Vec2 d = b.pos - a.pos;
            const double dist = length(d);
            const double need = 2.0 * tuning::kTankRadius;
            if (dist >= need) continue;
            const Vec2 n = dist > 1e-9 ? d * (1.0 / dist) : Vec2{1.0, 0.0};
            const Vec2 push = n * ((need - dist) * 0.5);
            a.pos = move_circle(a.pos, push * -1.0, tuning::kTankRadius, blockers_, arena_.bounds);
            b.pos = move_circle(b.pos, push, tuning::kTankRadius, blockers_, arena_.bounds);
        }
    }
}

}  // namespace core
