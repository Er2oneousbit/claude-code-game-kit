// ---------------------------------------------------------------------------
// logic/race.rs
// Purpose : One race, engine-free: countdown, karts driving, walls and closed lanes pushing back, kart bumps,
//           item boxes, laps and positions, the seeded change schedule (the twist), finish order. The Bevy side
//           (game/) feeds inputs and draws the result; tests and bots drive it directly.
// Usage   : let mut race = Race::new(seed, 4);  loop { race.step(&inputs, DT); for e in &race.events {..} }
// Notes   : Progress is continuous race distance (laps * lap length + s), so a shortcut that maps 200 m of road
//           onto 250 m of lap gains distance honestly and nobody can skip a lap: walls keep karts on the road.
//           Schedule: lap 1 has no change (learn the track), lap 2 always closes a lane (the gentlest change,
//           GDD FTUE lesson 2), lap 3 picks any other change. A change warns (glows) when the leader is WARN_TIME (at
//           its speed) plus WARN_LEAD away from it on its lap, goes live WARN_TIME later and replaces the previous change.
//
// Pseudocode:
//   step: countdown -> for each kart: drive, resolve walls/closures, update lap progress, take item boxes
//         -> kart bumps -> update the change schedule from the leader -> finishes -> race over?
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::math::Vec2;

use super::kart::{Item, Kart, KartInput};
use super::rng::Rng;
use super::track::{ChangeKind, Live, Track};
use super::tuning::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    Countdown,
    Racing,
    Over,
}

/// A change on the schedule and where it stands.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ScheduledChange {
    /// Index into track.changes.
    pub change: usize,
    /// The lap (1-based) on which it happens.
    pub lap: u32,
    pub state: ChangeState,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ChangeState {
    Pending,
    /// Glowing; seconds left before it goes live.
    Warning(f32),
    Live,
    Over,
}

/// Something worth a log line, a sound or a test assertion. Cleared at the start of every step.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum RaceEvent {
    Go,
    Lap { kart: usize, lap: u32 },
    ChangeWarn { change: usize, lap: u32 },
    ChangeLive { change: usize },
    Bonk { kart: usize },
    ItemPicked { kart: usize },
    Boost { kart: usize },
    Finish { kart: usize, place: usize, time: f32 },
    RaceOver,
}

/// A kart plus its place in the race.
#[derive(Debug, Clone)]
pub struct Racer {
    pub kart: Kart,
    /// Race distance: negative on the grid, LAPS * lap length at the finish.
    pub progress: f32,
    /// Lap distance (s on the main loop) last tick.
    pub s: f32,
    /// The shortcut this kart is on, if any.
    pub on_shortcut: Option<usize>,
    pub finished: Option<f32>,
    pub bonks: u32,
    /// Seconds before the next barrier zap can happen.
    pub zap_cooldown: f32,
}

#[derive(Debug, Clone)]
pub struct ItemBox {
    pub pos: Vec2,
    /// Seconds until it is back; 0 = available.
    pub respawn: f32,
}

#[derive(Debug, Clone)]
pub struct Race {
    pub track: Track,
    pub racers: Vec<Racer>,
    pub boxes: Vec<ItemBox>,
    pub schedule: Vec<ScheduledChange>,
    pub phase: Phase,
    /// Seconds since the countdown started.
    pub time: f32,
    pub finish_order: Vec<usize>,
    pub events: Vec<RaceEvent>,
    pub seed: u64,
}

impl Race {
    /// A race on the toy track with `karts` karts (1 to 4); kart 0 is the player's.
    pub fn new(seed: u64, karts: usize) -> Self {
        let track = Track::neon_loop();
        let len = track.length();
        let racers = track
            .grid
            .iter()
            .take(karts.clamp(1, track.grid.len()))
            .map(|&(pos, heading)| {
                let s = track.main.project(pos).s;
                Racer {
                    kart: Kart::new(pos, heading),
                    progress: s - len,
                    s,
                    on_shortcut: None,
                    finished: None,
                    bonks: 0,
                    zap_cooldown: 0.0,
                }
            })
            .collect();
        let boxes = track
            .item_boxes
            .iter()
            .map(|&pos| ItemBox { pos, respawn: 0.0 })
            .collect();
        let schedule = make_schedule(&track, seed);
        Self {
            track,
            racers,
            boxes,
            schedule,
            phase: Phase::Countdown,
            time: 0.0,
            finish_order: Vec::new(),
            events: Vec::new(),
            seed,
        }
    }

    pub fn lap_length(&self) -> f32 {
        self.track.length()
    }

    /// The lap a racer is on (1..=LAPS), for the HUD and the schedule.
    pub fn lap_of(&self, i: usize) -> u32 {
        ((self.racers[i].progress / self.lap_length()).floor() as i64 + 1).clamp(1, LAPS as i64) as u32
    }

    /// Changes that are live now (what the track looks like).
    pub fn live(&self) -> Live {
        let mut live = Live::default();
        for sc in self.schedule.iter().filter(|c| c.state == ChangeState::Live) {
            match self.track.changes[sc.change] {
                ChangeKind::OpenShortcut(i) => live.shortcut = Some(i),
                ChangeKind::CloseLane(i) => live.closure = Some(i),
            }
        }
        live
    }

    /// Race order: finishers by finishing order, then everyone else by distance covered.
    pub fn standings(&self) -> Vec<usize> {
        let mut order = self.finish_order.clone();
        let mut rest: Vec<usize> = (0..self.racers.len())
            .filter(|i| self.racers[*i].finished.is_none())
            .collect();
        rest.sort_by(|a, b| self.racers[*b].progress.total_cmp(&self.racers[*a].progress));
        order.extend(rest);
        order
    }

    pub fn place_of(&self, i: usize) -> usize {
        self.standings().iter().position(|&k| k == i).map_or(0, |p| p + 1)
    }

    pub fn step(&mut self, inputs: &[KartInput], dt: f32) {
        self.events.clear();
        if self.phase == Phase::Over {
            return;
        }
        self.time += dt;
        if self.phase == Phase::Countdown {
            if self.time >= COUNTDOWN {
                self.phase = Phase::Racing;
                self.events.push(RaceEvent::Go);
            }
            return;
        }
        let live = self.live();
        for i in 0..self.racers.len() {
            let input = inputs.get(i).copied().unwrap_or_default();
            self.racers[i].zap_cooldown = (self.racers[i].zap_cooldown - dt).max(0.0);
            if self.racers[i].kart.drive(&input, dt) {
                self.events.push(RaceEvent::Boost { kart: i });
            }
            self.keep_on_track(i, &live);
            self.update_progress(i);
            self.take_items(i);
        }
        self.bump_karts();
        for b in &mut self.boxes {
            b.respawn = (b.respawn - dt).max(0.0);
        }
        self.update_schedule(dt);
        self.check_finish();
    }

    /// Walls and closed lanes: a kart that ends a tick off the road is put back just inside the edge and loses
    /// the speed it had into the wall.
    fn keep_on_track(&mut self, i: usize, live: &Live) {
        let track = &self.track;
        let r = &mut self.racers[i];
        let p = r.kart.pos;
        if track.drivable(p, live, r.on_shortcut, KART_RADIUS) {
            return;
        }
        // Candidate fixes: back inside the main loop (clear of a closure), or back inside an allowed shortcut;
        // take the one that moves the kart least.
        let mut best: Option<Vec2> = None;
        let mut consider = |q: Vec2| {
            if best.is_none_or(|b| q.distance(p) < b.distance(p)) {
                best = Some(q);
            }
        };
        let pr = track.main.project(p);
        let max_lat = track.main.half_width - KART_RADIUS - 0.01;
        let mut lat = pr.lateral.clamp(-max_lat, max_lat);
        let mut zapped = false;
        if let Some(c) = live.closure.map(|c| track.closures[c])
            && c.blocks(pr.s, lat, KART_RADIUS)
        {
            // Pushed over to the open side (the barrier's taper turns a straight hit into a deflection)
            lat = c.clear_lateral(pr.s, KART_RADIUS);
            zapped = true;
        }
        consider(pr.point + pr.tangent.perp() * lat);
        for (k, sc) in track.shortcuts.iter().enumerate() {
            if live.shortcut == Some(k) || r.on_shortcut == Some(k) {
                let sp = sc.strip.project(p);
                let max = sc.strip.half_width - KART_RADIUS - 0.01;
                consider(sp.point + sp.tangent.perp() * sp.lateral.clamp(-max, max));
            }
        }
        let Some(fixed) = best else { return };
        let normal = (fixed - p).normalize_or(Vec2::ZERO);
        let into_wall = -r.kart.vel.dot(normal);
        r.kart.pos = fixed;
        if into_wall > 0.0 {
            // Remove the motion into the wall, keep a share of the rest
            r.kart.vel += normal * into_wall;
            r.kart.vel *= WALL_SPEED_KEEP + (1.0 - WALL_SPEED_KEEP) * (1.0 - into_wall / TOP_SPEED).clamp(0.0, 1.0);
            if into_wall >= BONK_MIN_IMPACT && !zapped {
                r.bonks += 1;
                self.events.push(RaceEvent::Bonk { kart: i });
            }
        }
        // A closed lane is an energy wall: touching it zaps, whatever the angle (once per ZAP_COOLDOWN)
        if zapped && r.zap_cooldown == 0.0 {
            r.kart.vel *= CLOSURE_ZAP_KEEP;
            r.zap_cooldown = ZAP_COOLDOWN;
            r.bonks += 1;
            self.events.push(RaceEvent::Bonk { kart: i });
        }
    }

    /// Lap distance from the main loop or, on a shortcut, the shortcut's share of the lap it skips.
    fn update_progress(&mut self, i: usize) {
        let len = self.track.length();
        let r = &mut self.racers[i];
        let p = r.kart.pos;
        let main = self.track.main.project(p);
        let on_main = main.dist <= self.track.main.half_width;
        // On a shortcut: from where it leaves the loop's road until the kart leaves the strip (its ends overlap the
        // loop, so "inside the loop" alone cannot say which road a kart is on)
        r.on_shortcut = match r.on_shortcut {
            Some(k) if self.track.shortcuts[k].strip.contains(p, 0.0) => Some(k),
            _ if on_main => None,
            _ => self.track.shortcuts.iter().position(|sc| sc.strip.contains(p, 0.0)),
        };
        let s = match r.on_shortcut {
            Some(k) => {
                let sc = &self.track.shortcuts[k];
                sc.lap_s(sc.strip.project(p).s)
            }
            None => main.s,
        };
        // Signed change in lap distance, unwrapped across the start line
        let mut ds = s - r.s;
        if ds > len / 2.0 {
            ds -= len;
        } else if ds < -len / 2.0 {
            ds += len;
        }
        let lap_before = (r.progress / len).floor();
        r.progress += ds;
        r.s = s;
        let lap_after = (r.progress / len).floor();
        if lap_after > lap_before && lap_after >= 1.0 && r.finished.is_none() && lap_after < LAPS as f32 {
            self.events.push(RaceEvent::Lap {
                kart: i,
                lap: lap_after as u32 + 1,
            });
        }
    }

    fn take_items(&mut self, i: usize) {
        let pos = self.racers[i].kart.pos;
        for b in &mut self.boxes {
            if b.respawn == 0.0 && b.pos.distance(pos) <= ITEM_BOX_RADIUS + KART_RADIUS {
                b.respawn = ITEM_RESPAWN;
                if self.racers[i].kart.item.is_none() {
                    self.racers[i].kart.item = Some(Item::Boost);
                    self.events.push(RaceEvent::ItemPicked { kart: i });
                }
            }
        }
    }

    /// Karts are circles: overlapping pairs are pushed apart, and only the speed with which they close on each
    /// other is exchanged (a touch while side by side costs nothing; ramming the kart ahead slows you, speeds it).
    fn bump_karts(&mut self) {
        let n = self.racers.len();
        for a in 0..n {
            for b in a + 1..n {
                let d = self.racers[b].kart.pos - self.racers[a].kart.pos;
                let dist = d.length();
                let min = 2.0 * KART_RADIUS;
                if dist >= min || dist < 1e-6 {
                    continue;
                }
                let normal = d / dist;
                let push = normal * (min - dist) / 2.0;
                self.racers[a].kart.pos -= push;
                self.racers[b].kart.pos += push;
                let closing = (self.racers[b].kart.vel - self.racers[a].kart.vel).dot(normal);
                if closing < 0.0 {
                    let j = -(1.0 + BUMP_BOUNCE) * closing / 2.0;
                    self.racers[a].kart.vel -= normal * j;
                    self.racers[b].kart.vel += normal * j;
                }
            }
        }
    }

    /// The leader drives the schedule: the change for the leader's lap starts glowing when the leader is
    /// WARN_TIME (at its speed) plus WARN_LEAD from it, and goes live WARN_TIME later, ending the change before it.
    fn update_schedule(&mut self, dt: f32) {
        let Some(&leader) = self.standings().first() else {
            return;
        };
        let len = self.track.length();
        let lead = &self.racers[leader];
        let lead_lap = self.lap_of(leader);
        let lead_s = lead.progress.rem_euclid(len);
        for k in 0..self.schedule.len() {
            let sc = self.schedule[k];
            match sc.state {
                ChangeState::Pending if sc.lap <= lead_lap && lead.progress >= 0.0 => {
                    let start = self.track.change_start(sc.change);
                    let ahead = (start - lead_s).rem_euclid(len);
                    let warn_at = lead.kart.speed().max(TOP_SPEED) * WARN_TIME + WARN_LEAD;
                    if ahead <= warn_at || sc.lap < lead_lap {
                        self.schedule[k].state = ChangeState::Warning(WARN_TIME);
                        self.events.push(RaceEvent::ChangeWarn {
                            change: sc.change,
                            lap: sc.lap,
                        });
                    }
                }
                ChangeState::Warning(left) => {
                    let left = left - dt;
                    if left > 0.0 {
                        self.schedule[k].state = ChangeState::Warning(left);
                    } else {
                        for other in self.schedule.iter_mut() {
                            if other.state == ChangeState::Live {
                                other.state = ChangeState::Over;
                            }
                        }
                        self.schedule[k].state = ChangeState::Live;
                        self.events.push(RaceEvent::ChangeLive { change: sc.change });
                    }
                }
                _ => {}
            }
        }
    }

    fn check_finish(&mut self) {
        let goal = LAPS as f32 * self.lap_length();
        for i in 0..self.racers.len() {
            if self.racers[i].finished.is_none() && self.racers[i].progress >= goal {
                self.racers[i].finished = Some(self.time - COUNTDOWN);
                self.finish_order.push(i);
                self.events.push(RaceEvent::Finish {
                    kart: i,
                    place: self.finish_order.len(),
                    time: self.time - COUNTDOWN,
                });
            }
        }
        let all_done = self.racers.iter().all(|r| r.finished.is_some());
        let player_grace = self.racers[0]
            .finished
            .is_some_and(|t| self.time - COUNTDOWN - t >= FINISH_GRACE);
        if all_done || player_grace || self.time >= RACE_TIME_LIMIT {
            self.phase = Phase::Over;
            self.events.push(RaceEvent::RaceOver);
        }
    }
}

/// Lap 2 closes a lane (either one), lap 3 picks any change except that one. Same seed, same schedule.
pub fn make_schedule(track: &Track, seed: u64) -> Vec<ScheduledChange> {
    let mut rng = Rng::new(seed);
    let lanes: Vec<usize> = (0..track.changes.len())
        .filter(|&c| matches!(track.changes[c], ChangeKind::CloseLane(_)))
        .collect();
    let first = lanes[rng.below(lanes.len() as u32) as usize];
    let others: Vec<usize> = (0..track.changes.len()).filter(|&c| c != first).collect();
    let second = others[rng.below(others.len() as u32) as usize];
    [(first, 2), (second, 3)]
        .into_iter()
        .filter(|&(_, lap)| lap <= LAPS)
        .map(|(change, lap)| ScheduledChange {
            change,
            lap,
            state: ChangeState::Pending,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f32 = 1.0 / 60.0;

    #[test]
    fn nothing_moves_during_the_countdown() {
        let mut race = Race::new(1, 4);
        let start = race.racers[0].kart.pos;
        let go = vec![
            KartInput {
                throttle: 1.0,
                ..Default::default()
            };
            4
        ];
        for _ in 0..(COUNTDOWN / DT) as usize - 2 {
            race.step(&go, DT);
        }
        assert_eq!(race.phase, Phase::Countdown);
        assert_eq!(race.racers[0].kart.pos, start);
    }

    #[test]
    fn the_schedule_repeats_per_seed_and_lap_two_always_closes_a_lane() {
        let track = Track::neon_loop();
        for seed in 0..50 {
            let a = make_schedule(&track, seed);
            assert_eq!(a, make_schedule(&track, seed));
            assert_eq!(a.len(), 2);
            assert!(matches!(track.changes[a[0].change], ChangeKind::CloseLane(_)));
            assert_ne!(a[0].change, a[1].change);
        }
        let thirds: std::collections::HashSet<usize> = (0..50).map(|s| make_schedule(&track, s)[1].change).collect();
        assert!(thirds.len() >= 3, "lap 3 varies across seeds: {thirds:?}");
    }

    #[test]
    fn a_kart_driving_into_the_wall_stays_on_the_road_and_slows() {
        let mut race = Race::new(1, 1);
        race.phase = Phase::Racing;
        // Aim the kart straight at the outside wall
        let r = &mut race.racers[0];
        r.kart.heading -= std::f32::consts::FRAC_PI_2;
        r.kart.vel = Vec2::from_angle(r.kart.heading) * TOP_SPEED;
        let go = [KartInput {
            throttle: 1.0,
            ..Default::default()
        }];
        let mut bonked = false;
        for _ in 0..120 {
            race.step(&go, DT);
            bonked |= race.events.iter().any(|e| matches!(e, RaceEvent::Bonk { .. }));
            let pr = race.track.main.project(race.racers[0].kart.pos);
            assert!(pr.dist <= TRACK_HALF_WIDTH - KART_RADIUS + 0.05);
        }
        assert!(bonked);
        assert_eq!(race.racers[0].bonks, 1, "one hit, then it rests against the wall");
    }

    #[test]
    fn progress_counts_laps_across_the_start_line() {
        let mut race = Race::new(3, 1);
        race.phase = Phase::Racing;
        let len = race.lap_length();
        // Teleport-free check: walk the kart along the centerline in small steps
        let mut laps = vec![];
        let mut s = race.racers[0].s;
        for _ in 0..((len * 1.2) as usize) {
            s += 1.0;
            let (p, t) = race.track.main.point_at(s);
            race.racers[0].kart.pos = p;
            race.racers[0].kart.vel = t * 0.01;
            race.step(&[KartInput::default()], DT);
            laps.extend(race.events.iter().filter_map(|e| match e {
                RaceEvent::Lap { lap, .. } => Some(*lap),
                _ => None,
            }));
        }
        assert_eq!(
            laps,
            vec![2],
            "crossed the line twice: lap 1 starts, lap 2 is announced"
        );
        assert_eq!(race.lap_of(0), 2);
    }

    #[test]
    fn a_shortcut_maps_onto_the_lap_it_skips() {
        let mut race = Race::new(3, 1);
        race.phase = Phase::Racing;
        let sc = race.track.shortcuts[0].clone();
        // Put the kart on the main loop just before the entry, then walk it through the shortcut
        let (p, t) = race.track.main.point_at(sc.s_from - 1.0);
        race.racers[0].kart.pos = p;
        race.racers[0].kart.vel = t * 0.01;
        race.racers[0].s = sc.s_from - 1.0;
        race.racers[0].progress = sc.s_from - 1.0;
        race.schedule.clear();
        race.schedule.push(ScheduledChange {
            change: 2,
            lap: 1,
            state: ChangeState::Live,
        });
        let mut along = 0.0;
        while along < sc.strip.length() {
            along += 1.0;
            let (q, d) = sc.strip.point_at(along);
            race.racers[0].kart.pos = q;
            race.racers[0].kart.vel = d * 0.01;
            race.step(&[KartInput::default()], DT);
        }
        let gained = race.racers[0].progress - (sc.s_from - 1.0);
        assert!((gained - (sc.s_to - sc.s_from) - 1.0).abs() < 3.0, "gained {gained}");
    }

    #[test]
    fn the_lap_two_change_warns_then_goes_live_near_the_leader() {
        let mut race = Race::new(5, 1);
        race.phase = Phase::Racing;
        let len = race.lap_length();
        let change = race.schedule[0].change;
        let start = race.track.change_start(change);
        // Leader on lap 2, well before the section: nothing yet
        let warn_at = TOP_SPEED * WARN_TIME + WARN_LEAD;
        race.racers[0].progress = len + start - warn_at - 50.0;
        race.update_schedule(DT);
        assert_eq!(race.schedule[0].state, ChangeState::Pending);
        // Within the warning distance: glow, then live after WARN_TIME
        race.racers[0].progress = len + start - warn_at + 5.0;
        race.update_schedule(DT);
        assert!(matches!(race.schedule[0].state, ChangeState::Warning(_)));
        for _ in 0..(WARN_TIME / DT) as usize + 2 {
            race.update_schedule(DT);
        }
        assert_eq!(race.schedule[0].state, ChangeState::Live);
    }

    #[test]
    fn karts_never_overlap_after_a_bump() {
        let mut race = Race::new(1, 2);
        race.phase = Phase::Racing;
        race.racers[1].kart.pos = race.racers[0].kart.pos + Vec2::new(0.5, 0.0);
        race.bump_karts();
        let d = race.racers[0].kart.pos.distance(race.racers[1].kart.pos);
        assert!(d >= 2.0 * KART_RADIUS - 1e-4, "distance {d}");
    }
}
