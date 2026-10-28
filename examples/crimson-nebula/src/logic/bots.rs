// ---------------------------------------------------------------------------
// logic/bots.rs
// Purpose : Bot drivers for rival karts, smoke scenarios and the bot-pair tests (SOP-14): follow a path a few
//           meters ahead, lift off in tight turns, use the boost on straights, and react to the track changes
//           according to their style.
// Usage   : let input = bots::drive(&race, kart, Style::Reader);
// Notes   : Styles differ ONLY in how they read the changes, so a bot-pair result measures reading, nothing else:
//           Reader acts on the warning glow, Late acts once a change is live, Ignorer drives the base line and
//           never takes a shortcut (it still gets pushed around by closed lanes). Same speed, same grip as the
//           player: no rubber-banding (GDD assumption 3).
//
// Pseudocode:
//   pick path: shortcut (if this style sees it open and its entry is ahead) or the main loop at a lane offset
//   (dodge to the open side of a closed lane this style sees) -> aim point = path point LOOKAHEAD ahead
//   -> steer toward it, lift when the angle is large -> boost on a straight
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::math::Vec2;

use super::kart::KartInput;
use super::math::wrap_angle;
use super::race::{ChangeState, Race};
use super::track::ChangeKind;
use super::tuning::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Style {
    /// Reacts to the warning glow (what a sharp player does).
    Reader,
    /// Reacts once the change is live (a beat late).
    Late,
    /// Never reacts: base line, no shortcuts.
    Ignorer,
}

impl Style {
    fn sees(self, state: ChangeState) -> bool {
        match self {
            Style::Reader => matches!(state, ChangeState::Warning(_) | ChangeState::Live),
            Style::Late => state == ChangeState::Live,
            Style::Ignorer => false,
        }
    }
}

pub fn drive(race: &Race, k: usize, style: Style) -> KartInput {
    let racer = &race.racers[k];
    let kart = &racer.kart;
    let track = &race.track;
    let len = track.length();
    let speed = kart.speed().max(0.0);
    let look = AI_LOOKAHEAD + AI_LOOKAHEAD_PER_SPEED * speed;

    // What this bot believes about the changes ahead
    let mut take_shortcut = None;
    let mut dodge = 0.0;
    for sc in &race.schedule {
        let reads = style.sees(sc.state);
        match track.changes[sc.change] {
            ChangeKind::OpenShortcut(i) => {
                // Only while the shortcut can still be entered: shut ones stay open only for karts already on them
                // Still worth it from AI_SIGHT before its start until it has peeled away from the loop
                let ahead = signed_ahead(track.shortcuts[i].s_from, racer.s, len);
                let beside = ahead <= 0.0 && track.shortcuts[i].strip.contains(kart.pos, 0.0);
                if reads && ahead < AI_SIGHT && (ahead > -SHORTCUT_BRANCH || beside) {
                    take_shortcut = Some(i);
                }
            }
            ChangeKind::CloseLane(i) => {
                let c = track.closures[i];
                let ahead = (c.s_from - racer.s).rem_euclid(len);
                let inside = racer.s >= c.s_from && racer.s <= c.s_to;
                // Readers swerve early; a non-reader swerves only once it has been zapped by the barrier
                let panic = sc.state == ChangeState::Live && inside && racer.bonks > 0;
                if (reads && (ahead < AI_SIGHT || inside)) || panic {
                    dodge = -c.side.sign() * AI_DODGE_OFFSET;
                }
            }
        }
    }
    // A shortcut that is no longer live cannot be entered (only finished)
    let live = race.live();
    if let Some(i) = take_shortcut
        && live.shortcut != Some(i)
        && racer.on_shortcut != Some(i)
    {
        let warning = race.schedule.iter().any(|c| {
            track.changes[c.change] == ChangeKind::OpenShortcut(i) && matches!(c.state, ChangeState::Warning(_))
        });
        if !warning {
            take_shortcut = None;
        }
    }

    // Traffic: a kart close ahead on our line gets passed on the side with more room (no train of bumps);
    // never while dodging a closed lane, where the open side is the only side
    if racer.on_shortcut.is_none() && dodge == 0.0 {
        dodge = pass_offset(race, k, dodge);
    }

    let plan = match (racer.on_shortcut, take_shortcut) {
        (Some(i), _) => Plan::Shortcut(i),
        (None, Some(i)) if live.shortcut == Some(i) => Plan::Shortcut(i),
        _ => Plan::Main(dodge),
    };

    // Steer at the point `look` ahead on the plan; shorter on a narrow shortcut, so the bot does not cut its
    // inside edge (aiming far ahead makes a follower cut corners by about the aim distance's bend)
    let look = match plan {
        Plan::Shortcut(_) => look * AI_SHORTCUT_LOOK_SHARE,
        Plan::Main(_) => look,
    };
    let target = plan_point(race, k, plan, look);
    let to_target = target - kart.pos;
    let error = wrap_angle(to_target.y.atan2(to_target.x) - kart.heading);
    let steer = (error * AI_STEER_GAIN).clamp(-1.0, 1.0);

    // Speed: the slowest corner ahead (within braking distance) sets the target
    let target_speed = corner_speed(race, k, plan, speed);
    let throttle = if speed > target_speed + 1.0 {
        -1.0
    } else if speed > target_speed - 1.0 || error.abs() > AI_LIFT_ANGLE {
        0.3
    } else {
        1.0
    };
    let straight = target_speed >= TOP_SPEED * BOOST_SPEED_MULT;
    let use_item = kart.item.is_some() && straight && error.abs() < 0.08 && speed > TOP_SPEED * 0.8;
    KartInput {
        throttle,
        steer,
        drift: false,
        use_item,
    }
}

/// Where a bot means to drive: the main loop at a lane offset, or through a shortcut.
#[derive(Debug, Clone, Copy, PartialEq)]
enum Plan {
    Main(f32),
    Shortcut(usize),
}

/// The point `d` meters ahead of kart k along its plan.
fn plan_point(race: &Race, k: usize, plan: Plan, d: f32) -> Vec2 {
    let racer = &race.racers[k];
    match plan {
        Plan::Main(offset) => on_main(race, racer.s + d, offset),
        Plan::Shortcut(i) => {
            let sc = &race.track.shortcuts[i];
            let len = race.track.length();
            // Distance along the shortcut; negative = still on the main loop before its start
            let along = if racer.on_shortcut == Some(i) {
                sc.strip.project(racer.kart.pos).s
            } else {
                // Signed, so a kart just past the start (still overlapping the loop) is on the shortcut's first meters
                -signed_ahead(sc.s_from, racer.s, len)
            } + d;
            if along < 0.0 {
                on_main(race, sc.s_from + along, 0.0)
            } else if along <= sc.strip.length() {
                sc.strip.point_at(along).0
            } else {
                on_main(race, sc.s_to + (along - sc.strip.length()), 0.0)
            }
        }
    }
}

/// The fastest speed that still makes every bend ahead within braking distance.
/// Bend radius from three points AI_CURVE_STEP apart; a kart turns at TURN_RATE, so it holds radius R up to
/// R * TURN_RATE m/s (less a safety margin), and it can brake BRAKE m/s^2 on the way there.
fn corner_speed(race: &Race, k: usize, plan: Plan, speed: f32) -> f32 {
    let reach = speed * speed / (2.0 * BRAKE * AI_BRAKE_SHARE) + AI_LOOKAHEAD + 10.0;
    let mut best = TOP_SPEED * BOOST_SPEED_MULT;
    let mut d = 0.0;
    while d < reach {
        let (a, b, c) = (
            plan_point(race, k, plan, d),
            plan_point(race, k, plan, d + AI_CURVE_STEP),
            plan_point(race, k, plan, d + 2.0 * AI_CURVE_STEP),
        );
        let turn = (c - b).angle_to(b - a).abs();
        if turn > 1e-3 {
            let radius = AI_CURVE_STEP / turn;
            let corner = radius * TURN_RATE * AI_CORNER_MARGIN;
            let allowed = (corner * corner + 2.0 * BRAKE * AI_BRAKE_SHARE * d).sqrt();
            best = best.min(allowed);
        }
        d += AI_CURVE_STEP;
    }
    best.max(AI_MIN_CORNER_SPEED)
}

/// The lane offset to drive at, given the planned one and the karts just ahead.
fn pass_offset(race: &Race, k: usize, planned: f32) -> f32 {
    let me = &race.racers[k];
    let len = race.track.length();
    let my_lat = race.track.main.project(me.kart.pos).lateral;
    let max = TRACK_HALF_WIDTH - KART_RADIUS - 1.0;
    for (j, other) in race.racers.iter().enumerate() {
        if j == k || other.on_shortcut.is_some() {
            continue;
        }
        let gap = (other.s - me.s).rem_euclid(len);
        let their_lat = race.track.main.project(other.kart.pos).lateral;
        if gap > 0.5 && gap < AI_PASS_LOOK && (their_lat - planned).abs() < AI_PASS_WIDTH {
            // Pass on the side of them that is further from the wall and closer to where we already are
            let left = their_lat + AI_PASS_WIDTH;
            let right = their_lat - AI_PASS_WIDTH;
            let pick = if left > max {
                right
            } else if right < -max || (left - my_lat).abs() <= (right - my_lat).abs() {
                left
            } else {
                right
            };
            return pick.clamp(-max, max);
        }
    }
    planned
}

/// Lap distance from s to `target`, in -len/2..len/2: negative once the target is behind.
fn signed_ahead(target: f32, s: f32, len: f32) -> f32 {
    (target - s + len / 2.0).rem_euclid(len) - len / 2.0
}

fn on_main(race: &Race, s: f32, offset: f32) -> Vec2 {
    let (p, t) = race.track.main.point_at(s);
    p + t.perp() * offset
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic::race::{Phase, RaceEvent};

    const DT: f32 = 1.0 / 60.0;

    /// Races one bot alone on a seed; returns (finish time, bonks, used a shortcut).
    fn solo(seed: u64, style: Style) -> (f32, u32, bool) {
        let mut race = Race::new(seed, 1);
        let mut shortcut = false;
        while race.phase != Phase::Over {
            let input = drive(&race, 0, style);
            race.step(&[input], DT);
            shortcut |= race.racers[0].on_shortcut.is_some();
        }
        let time = race.racers[0].finished.expect("the bot finishes");
        (time, race.racers[0].bonks, shortcut)
    }

    #[test]
    fn a_bot_finishes_three_laps_without_hitting_walls() {
        let (time, bonks, _) = solo(1, Style::Ignorer);
        let laps_at_top_speed = LAPS as f32 * Track::neon_loop().length() / TOP_SPEED;
        assert!(
            time < laps_at_top_speed * 1.35,
            "time {time} vs ideal {laps_at_top_speed}"
        );
        // Ignorer may bonk a closed lane, but never the plain walls more than a couple of times
        assert!(bonks <= 6, "bonks {bonks}");
    }

    #[test]
    fn reading_the_changes_wins_over_twenty_seeds() {
        // GDD assumption 1: following the warning glow must pay off
        let mut wins = 0;
        let mut margin = 0.0;
        for seed in 0..20 {
            let (reader, reader_bonks, _) = solo(seed, Style::Reader);
            let (ignorer, _, _) = solo(seed, Style::Ignorer);
            assert!(
                reader_bonks <= 2,
                "seed {seed}: the reader dodged badly ({reader_bonks} bonks)"
            );
            if reader < ignorer {
                wins += 1;
            }
            margin += ignorer - reader;
        }
        assert_eq!(
            wins,
            20,
            "the reader won {wins} of 20 (average margin {:.2} s)",
            margin / 20.0
        );
    }

    #[test]
    fn reacting_at_all_beats_ignoring() {
        // Late reacts a beat after the Reader; dodging early costs the Reader a little racing line, so the two are
        // close. Both must clearly beat the Ignorer.
        let total = |style| (0..10).map(|seed| solo(seed, style).0).sum::<f32>();
        let (reader, late, ignorer) = (total(Style::Reader), total(Style::Late), total(Style::Ignorer));
        assert!(
            reader < ignorer - 5.0 && late < ignorer - 5.0,
            "{reader} / {late} / {ignorer}"
        );
    }

    #[test]
    fn the_reader_takes_an_open_shortcut() {
        let track = Track::neon_loop();
        let seed = (0..50)
            .find(|&s| {
                let sched = crate::logic::race::make_schedule(&track, s);
                matches!(track.changes[sched[1].change], ChangeKind::OpenShortcut(_))
            })
            .expect("some seed opens a shortcut on lap 3");
        let (_, _, used) = solo(seed, Style::Reader);
        assert!(used, "seed {seed}");
        let (_, _, ignorer_used) = solo(seed, Style::Ignorer);
        assert!(!ignorer_used);
    }

    #[test]
    fn four_bots_race_to_a_full_finish_order() {
        let mut race = Race::new(7, 4);
        let styles = [Style::Reader, Style::Reader, Style::Late, Style::Ignorer];
        let mut over = false;
        while !over {
            let inputs: Vec<_> = (0..4).map(|k| drive(&race, k, styles[k])).collect();
            race.step(&inputs, DT);
            over = race.events.contains(&RaceEvent::RaceOver);
        }
        let state: Vec<_> = race
            .racers
            .iter()
            .map(|r| (r.finished, r.progress as i32, r.bonks))
            .collect();
        assert_eq!(
            race.finish_order.len(),
            4,
            "everyone finished: {:?} {state:?}",
            race.finish_order
        );
    }

    use crate::logic::track::Track;
}

/// Balance report for tuning (SOP-14): `cargo test --lib balance_report -- --ignored --nocapture` prints, per seed,
/// the schedule and how much reading the changes gained.
#[cfg(test)]
mod measure {
    use super::*;
    use crate::logic::race::{Phase, make_schedule};
    use crate::logic::track::Track;
    #[test]
    #[ignore]
    fn balance_report() {
        let track = Track::neon_loop();
        for seed in 0..12 {
            let sched = make_schedule(&track, seed);
            let run = |style| {
                let mut race = Race::new(seed, 1);
                while race.phase != Phase::Over {
                    let i = drive(&race, 0, style);
                    race.step(&[i], 1.0 / 60.0);
                }
                (race.racers[0].finished.unwrap(), race.racers[0].bonks)
            };
            let (r, rb) = run(Style::Reader);
            let (g, gb) = run(Style::Ignorer);
            println!(
                "seed {seed:2} lap2 {:?} lap3 {:?}: reader {r:.2} ({rb}) ignorer {g:.2} ({gb}) margin {:+.2}",
                track.changes[sched[0].change],
                track.changes[sched[1].change],
                g - r
            );
        }
    }
}
