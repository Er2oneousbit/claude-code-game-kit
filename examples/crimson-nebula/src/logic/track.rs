// ---------------------------------------------------------------------------
// logic/track.rs
// Purpose : The track as data: a closed centerline with a width (the main loop), shortcuts (extra open strips
//           across the infield), lane closures (a blocked half of the main loop over a stretch), item boxes and
//           the starting grid. Answers "can a kart be here?" and "how far along the lap is this point?".
// Usage   : let track = Track::neon_loop();  track.main.project(p).s;  track.drivable(p, &open)
// Notes   : 2D, meters, x right and y "up" on the map (the 3D view maps y to world z). Driving direction is
//           counterclockwise, so `lateral` > 0 is the left of the kart and the inside of the loop.
//           Changes (the twist) are OpenShortcut or CloseLane; which ones are live is decided in race.rs.
//
// Pseudocode:
//   centerline = Catmull-Rom spline through control points, sampled every TRACK_STEP m -> Strip
//   project(p): nearest point on any segment -> arc length s, signed lateral offset, distance
//   drivable(p): inside main (and not in a live closure) OR inside a live shortcut
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::math::Vec2;

use super::tuning::*;

/// A centerline with a width: the main loop (closed) or a shortcut (open).
#[derive(Debug, Clone)]
pub struct Strip {
    pub points: Vec<Vec2>,
    /// Arc length at each point; for a closed strip one more entry (the full length) for the closing segment.
    pub cum: Vec<f32>,
    pub closed: bool,
    pub half_width: f32,
}

/// Where a point lies relative to a strip.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Projection {
    /// Arc length along the strip at the nearest centerline point.
    pub s: f32,
    /// Signed offset from the centerline: positive = left of the driving direction.
    pub lateral: f32,
    /// Distance from the centerline (= |lateral| except near the ends of an open strip).
    pub dist: f32,
    pub point: Vec2,
    pub tangent: Vec2,
}

impl Strip {
    pub fn new(points: Vec<Vec2>, closed: bool, half_width: f32) -> Self {
        let mut cum = vec![0.0];
        let segs = if closed { points.len() } else { points.len() - 1 };
        for i in 0..segs {
            let next = cum[i] + points[i].distance(points[(i + 1) % points.len()]);
            cum.push(next);
        }
        Self {
            points,
            cum,
            closed,
            half_width,
        }
    }

    pub fn length(&self) -> f32 {
        *self.cum.last().expect("a strip has points")
    }

    fn segments(&self) -> usize {
        self.cum.len() - 1
    }

    fn segment(&self, i: usize) -> (Vec2, Vec2) {
        (self.points[i], self.points[(i + 1) % self.points.len()])
    }

    /// Nearest point on the centerline. Brute force over all segments: about 550 on the toy track, cheap.
    pub fn project(&self, p: Vec2) -> Projection {
        let mut best = Projection {
            s: 0.0,
            lateral: 0.0,
            dist: f32::MAX,
            point: self.points[0],
            tangent: Vec2::X,
        };
        for i in 0..self.segments() {
            let (a, b) = self.segment(i);
            let ab = b - a;
            let len2 = ab.length_squared().max(1e-9);
            let t = ((p - a).dot(ab) / len2).clamp(0.0, 1.0);
            let q = a + ab * t;
            let dist = p.distance(q);
            if dist < best.dist {
                let tangent = ab.normalize_or(Vec2::X);
                best = Projection {
                    s: self.cum[i] + t * (self.cum[i + 1] - self.cum[i]),
                    lateral: tangent.perp().dot(p - q),
                    dist,
                    point: q,
                    tangent,
                };
            }
        }
        best
    }

    /// Point and direction at arc length s (wraps on a closed strip, clamps on an open one).
    pub fn point_at(&self, s: f32) -> (Vec2, Vec2) {
        let len = self.length();
        let s = if self.closed {
            s.rem_euclid(len)
        } else {
            s.clamp(0.0, len)
        };
        // Binary search for the segment holding s
        let i = match self.cum.binary_search_by(|c| c.total_cmp(&s)) {
            Ok(i) => i.min(self.segments() - 1),
            Err(i) => i.saturating_sub(1).min(self.segments() - 1),
        };
        let (a, b) = self.segment(i);
        let seg = (self.cum[i + 1] - self.cum[i]).max(1e-6);
        let t = ((s - self.cum[i]) / seg).clamp(0.0, 1.0);
        (a.lerp(b, t), (b - a).normalize_or(Vec2::X))
    }

    /// Inside the strip with a margin (the kart's radius).
    pub fn contains(&self, p: Vec2, margin: f32) -> bool {
        self.project(p).dist <= self.half_width - margin
    }
}

/// An infield cut: an open strip that joins the main loop at s_from and s_to.
#[derive(Debug, Clone)]
pub struct Shortcut {
    pub strip: Strip,
    pub s_from: f32,
    pub s_to: f32,
}

impl Shortcut {
    /// Lap distance for a point on the shortcut: its share of the shortcut maps onto s_from..s_to.
    pub fn lap_s(&self, along: f32) -> f32 {
        self.s_from + (self.s_to - self.s_from) * (along / self.strip.length()).clamp(0.0, 1.0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    Left,
    Right,
}

impl Side {
    /// +1 for left (the positive lateral side), -1 for right.
    pub fn sign(self) -> f32 {
        match self {
            Side::Left => 1.0,
            Side::Right => -1.0,
        }
    }
}

/// One half of the main loop blocked between s_from and s_to.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Closure {
    pub s_from: f32,
    pub s_to: f32,
    pub side: Side,
}

impl Closure {
    /// How far the barrier reaches across the track at lap distance s, as a lateral bound on the blocked side:
    /// the kart is blocked when lateral * side.sign() is above it. It tapers in over CLOSURE_TAPER meters (a
    /// funnel, like road cones), so a kart that drives into it is deflected sideways instead of stopped dead.
    pub fn bound(&self, s: f32) -> Option<f32> {
        if s < self.s_from || s > self.s_to {
            return None;
        }
        let f = ((s - self.s_from) / CLOSURE_TAPER).clamp(0.0, 1.0);
        Some(TRACK_HALF_WIDTH + (-CLOSURE_PAST_CENTER - TRACK_HALF_WIDTH) * f)
    }

    /// True when a kart at (s, lateral) would overlap the barrier.
    pub fn blocks(&self, s: f32, lateral: f32, margin: f32) -> bool {
        self.bound(s).is_some_and(|b| lateral * self.side.sign() > b - margin)
    }

    /// The lateral offset just clear of the barrier on the open side at s.
    pub fn clear_lateral(&self, s: f32, margin: f32) -> f32 {
        let b = self.bound(s).unwrap_or(TRACK_HALF_WIDTH);
        self.side.sign() * (b - margin - 0.01)
    }
}

/// A section that can change during a race.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChangeKind {
    OpenShortcut(usize),
    CloseLane(usize),
}

/// Which changes are live right now, as the race sees them.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Live {
    pub shortcut: Option<usize>,
    pub closure: Option<usize>,
}

#[derive(Debug, Clone)]
pub struct Track {
    pub main: Strip,
    pub shortcuts: Vec<Shortcut>,
    pub closures: Vec<Closure>,
    /// Every change this track offers; the race schedule picks from these by index.
    pub changes: Vec<ChangeKind>,
    pub item_boxes: Vec<Vec2>,
    /// Grid slots, front first: position and heading.
    pub grid: Vec<(Vec2, f32)>,
}

impl Track {
    pub fn length(&self) -> f32 {
        self.main.length()
    }

    /// Where a change's section starts along the lap (for warnings and bots).
    pub fn change_start(&self, change: usize) -> f32 {
        match self.changes[change] {
            ChangeKind::OpenShortcut(i) => self.shortcuts[i].s_from,
            ChangeKind::CloseLane(i) => self.closures[i].s_from,
        }
    }

    /// Can a kart (circle of `margin`) sit at p? `inside` is the shortcut the kart is already driving on, which
    /// stays drivable for it even after the shortcut closes behind the leader (no kart is ever stranded).
    pub fn drivable(&self, p: Vec2, live: &Live, inside: Option<usize>, margin: f32) -> bool {
        let pr = self.main.project(p);
        if pr.dist <= self.main.half_width - margin {
            let blocked = live
                .closure
                .is_some_and(|c| self.closures[c].blocks(pr.s, pr.lateral, margin));
            if !blocked {
                return true;
            }
        }
        self.shortcuts
            .iter()
            .enumerate()
            .any(|(i, sc)| (live.shortcut == Some(i) || inside == Some(i)) && sc.strip.contains(p, margin))
    }

    /// The toy track: a ~1.1 km neon loop with two infield shortcuts, two closable sections, two item rows.
    pub fn neon_loop() -> Track {
        const CTRL: [(f32, f32); 12] = [
            (0.0, 0.0),
            (70.0, 0.0),
            (120.0, 15.0),
            (145.0, 55.0),
            (135.0, 100.0),
            (95.0, 120.0),
            (55.0, 105.0),
            (20.0, 120.0),
            (-25.0, 110.0),
            (-50.0, 70.0),
            (-45.0, 25.0),
            (-25.0, 5.0),
        ];
        const SCALE: f32 = 2.0;
        let ctrl: Vec<Vec2> = CTRL.iter().map(|&(x, y)| Vec2::new(x, y) * SCALE).collect();
        let main = Strip::new(catmull_rom_loop(&ctrl, TRACK_STEP), true, TRACK_HALF_WIDTH);
        let len = main.length();

        // Shortcuts: a gentle S across the infield between two points of the loop (fractions of a lap)
        let shortcuts = [(0.22, 0.46), (0.60, 0.86)]
            .iter()
            .map(|&(f0, f1)| shortcut_between(&main, f0 * len, f1 * len, 4.0))
            .collect::<Vec<_>>();
        let closures = vec![
            Closure {
                s_from: 0.52 * len,
                s_to: 0.60 * len,
                side: Side::Left,
            },
            Closure {
                s_from: 0.80 * len,
                s_to: 0.88 * len,
                side: Side::Right,
            },
        ];
        let changes = vec![
            ChangeKind::CloseLane(0),
            ChangeKind::CloseLane(1),
            ChangeKind::OpenShortcut(0),
            ChangeKind::OpenShortcut(1),
        ];
        // Item rows: three boxes across the track
        let mut item_boxes = Vec::new();
        for f in [0.12, 0.62] {
            let (p, t) = main.point_at(f * len);
            for lat in [-4.0, 0.0, 4.0] {
                item_boxes.push(p + t.perp() * lat);
            }
        }
        // Grid: two columns behind the start line, 6 m between rows
        let (start, dir) = main.point_at(0.0);
        let heading = dir.y.atan2(dir.x);
        let grid = (0..4)
            .map(|i| {
                let back = 6.0 + 6.0 * (i / 2) as f32 + if i % 2 == 1 { 3.0 } else { 0.0 };
                let lat = if i % 2 == 0 { 3.0 } else { -3.0 };
                (start - dir * back + dir.perp() * lat, heading)
            })
            .collect();
        Track {
            main,
            shortcuts,
            closures,
            changes,
            item_boxes,
            grid,
        }
    }
}

/// An open strip that peels off the main loop at s_from and rejoins at s_to through two S-kink control points.
/// It starts and ends SHORTCUT_BRANCH meters further out along the loop itself, so karts curve into it instead of
/// meeting a corner; its recorded s_from/s_to are those outer points, so lap distance maps end to end.
fn shortcut_between(main: &Strip, s_from: f32, s_to: f32, kink: f32) -> Shortcut {
    let (a, _) = main.point_at(s_from);
    let (b, _) = main.point_at(s_to);
    let (a0, _) = main.point_at(s_from - SHORTCUT_BRANCH);
    let (b0, _) = main.point_at(s_to + SHORTCUT_BRANCH);
    let chord = b - a;
    let n = chord.normalize_or(Vec2::X).perp();
    let m1 = a + chord * 0.38 + n * kink;
    let m2 = a + chord * 0.62 - n * kink;
    Shortcut {
        strip: Strip::new(
            catmull_rom_open(&[a0, a, m1, m2, b, b0], TRACK_STEP),
            false,
            SHORTCUT_HALF_WIDTH,
        ),
        s_from: s_from - SHORTCUT_BRANCH,
        s_to: s_to + SHORTCUT_BRANCH,
    }
}

fn catmull_rom(p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2, t: f32) -> Vec2 {
    let (t2, t3) = (t * t, t * t * t);
    0.5 * (2.0 * p1 + (p2 - p0) * t + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 + (3.0 * p1 - p0 - 3.0 * p2 + p3) * t3)
}

/// Samples a closed Catmull-Rom spline through `ctrl` about every `step` meters.
pub fn catmull_rom_loop(ctrl: &[Vec2], step: f32) -> Vec<Vec2> {
    let n = ctrl.len();
    let mut out = Vec::new();
    for i in 0..n {
        let (p0, p1, p2, p3) = (ctrl[(i + n - 1) % n], ctrl[i], ctrl[(i + 1) % n], ctrl[(i + 2) % n]);
        let k = ((p1.distance(p2) / step).ceil() as usize).max(2);
        out.extend((0..k).map(|j| catmull_rom(p0, p1, p2, p3, j as f32 / k as f32)));
    }
    out
}

/// Samples an open Catmull-Rom spline through every point of `pts`, ends included.
pub fn catmull_rom_open(pts: &[Vec2], step: f32) -> Vec<Vec2> {
    let mut ext = vec![pts[0]];
    ext.extend_from_slice(pts);
    ext.push(*pts.last().expect("at least two points"));
    let mut out = Vec::new();
    for i in 1..ext.len() - 2 {
        let k = ((ext[i].distance(ext[i + 1]) / step).ceil() as usize).max(2);
        out.extend((0..k).map(|j| catmull_rom(ext[i - 1], ext[i], ext[i + 1], ext[i + 2], j as f32 / k as f32)));
    }
    out.push(*pts.last().expect("at least two points"));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_loop_is_about_a_kilometer_and_closed() {
        let track = Track::neon_loop();
        let len = track.length();
        assert!((1000.0..1200.0).contains(&len), "lap length {len}");
        // The closing segment joins the last point back to the first
        assert!(track.main.points[0].distance(*track.main.points.last().unwrap()) < TRACK_STEP * 2.0);
    }

    #[test]
    fn projection_reports_arc_length_and_left_is_positive() {
        let track = Track::neon_loop();
        let (p, t) = track.main.point_at(100.0);
        let left = track.main.project(p + t.perp() * 3.0);
        assert!((left.s - 100.0).abs() < 0.5, "s {}", left.s);
        assert!((left.lateral - 3.0).abs() < 0.05);
        assert!(track.main.project(p - t.perp() * 3.0).lateral < 0.0);
    }

    #[test]
    fn every_shortcut_is_shorter_than_the_track_it_skips() {
        let track = Track::neon_loop();
        for sc in &track.shortcuts {
            let skipped = sc.s_to - sc.s_from;
            assert!(
                sc.strip.length() < skipped - 20.0,
                "{} vs {}",
                sc.strip.length(),
                skipped
            );
        }
    }

    #[test]
    fn a_shortcut_is_drivable_only_while_live_or_for_karts_already_on_it() {
        let track = Track::neon_loop();
        let sc = &track.shortcuts[0];
        let (mid, _) = sc.strip.point_at(sc.strip.length() / 2.0);
        assert!(!track.drivable(mid, &Live::default(), None, KART_RADIUS));
        let open = Live {
            shortcut: Some(0),
            closure: None,
        };
        assert!(track.drivable(mid, &open, None, KART_RADIUS));
        assert!(track.drivable(mid, &Live::default(), Some(0), KART_RADIUS));
    }

    #[test]
    fn a_closed_lane_blocks_its_side_and_leaves_the_other_open() {
        let track = Track::neon_loop();
        let c = track.closures[0];
        let (p, t) = track.main.point_at((c.s_from + c.s_to) / 2.0);
        let live = Live {
            shortcut: None,
            closure: Some(0),
        };
        let blocked_side = p + t.perp() * (c.side.sign() * 4.0);
        let open_side = p + t.perp() * (-c.side.sign() * 4.5);
        assert!(!track.drivable(blocked_side, &live, None, KART_RADIUS));
        assert!(
            !track.drivable(p, &live, None, KART_RADIUS),
            "the center line is blocked too"
        );
        assert!(track.drivable(open_side, &live, None, KART_RADIUS));
        assert!(track.drivable(blocked_side, &Live::default(), None, KART_RADIUS));
    }

    #[test]
    fn the_grid_starts_behind_the_line_on_the_track() {
        let track = Track::neon_loop();
        for &(p, _) in &track.grid {
            let pr = track.main.project(p);
            assert!(pr.dist < TRACK_HALF_WIDTH - KART_RADIUS);
            assert!(pr.s > track.length() - 30.0, "grid slot at s {}", pr.s);
        }
    }
}
