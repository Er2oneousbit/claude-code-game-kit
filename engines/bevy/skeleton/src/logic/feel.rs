// ---------------------------------------------------------------------------
// logic/feel.rs
// Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): impact (a hit confirm scaled by damage),
//           float_text (a damage number's rise, pop and fade) and the tracer's point history by distance
//           (trail_push, trail_shrink, trail_length).
// Usage   : let hit = feel::impact(damage, max_hp, &feel::IMPACT);
//           hitstop.hit(hit.hitstop); shake.add_trauma(hit.trauma);
//           if hit.flash && limiter.request(real_now) { flash() }
//           let f = feel::float_text(age, &feel::FLOAT_TEXT);        // f.dy, f.scale, f.alpha, f.done
//           points = feel::trail_push(&points, x, y, spacing, length);  // every frame; after the hit:
//           points = feel::trail_shrink(&points, speed * dt);          // until fewer than two points
// Notes   : Pure functions: no settings, no clock, no random numbers, no Bevy types. Points are [x, y] (f64, like
//           the reference), tail first, head last; each trail function returns a new Vec. The constants are
//           SOP-18's starting points. Tested in tests/golden.rs against data/golden/juice.json ("impact",
//           "float_text", "trail").
//
// Pseudocode:
//   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); nothing for damage <= 0; lerp hitstop, trauma; flash f >= at
//   float_text: u = t / life; dy = -rise * out_cubic(u); scale = out_back(t / pop); alpha = 1 - in_cubic(u)
//   trail_push: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
//   trail_shrink: cut the trail to (length - amount) from the tail
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): impact is the same with blood on or off; what a
//           hit leaves is the game's: blood, or (blood_enabled off) a neutral spark or dust (SOP-18 step 4, #171)
// ---------------------------------------------------------------------------
use super::ease::Ease;

// ---- Tunables (SOP-18 step 4 starting points) ---------------------------------------
/// A hit confirm: hitstop and trauma from their min (the smallest hit) to their max (a full one), and a flash from
/// flash_at of `full`. The largest hitstop stays under the Hitstop cap (0.25 s).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ImpactTuning {
    pub hitstop_min: f64,
    pub hitstop_max: f64,
    pub trauma_min: f64,
    pub trauma_max: f64,
    pub flash_at: f64,
}
pub const IMPACT: ImpactTuning = ImpactTuning {
    hitstop_min: 0.03,
    hitstop_max: 0.1,
    trauma_min: 0.15,
    trauma_max: 0.6,
    flash_at: 0.5,
};

/// A damage number: life (s), rise (px), pop (s). With reduce motion pass rise 0 and pop_s 0.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FloatTuning {
    pub life: f64,
    pub rise: f64,
    pub pop_s: f64,
}
pub const FLOAT_TEXT: FloatTuning = FloatTuning {
    life: 0.8,
    rise: 24.0,
    pop_s: 0.12,
};

pub const TRAIL_SPACING: f64 = 6.0; // px between kept points
pub const TRAIL_LENGTH: f64 = 48.0; // px, the longest trail
const EPS: f64 = 1e-12; // a cut this close to a point removes the point

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Impact {
    pub hitstop: f64,
    pub trauma: f64,
    pub flash: bool,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FloatText {
    pub dy: f64,
    pub scale: f64,
    pub alpha: f64,
    pub done: bool,
}

pub fn impact(damage: f64, full: f64, t: &ImpactTuning) -> Impact {
    if damage <= 0.0 {
        return Impact {
            hitstop: 0.0,
            trauma: 0.0,
            flash: false,
        };
    }
    let f = if full <= 0.0 {
        1.0
    } else {
        (damage / full).clamp(0.0, 1.0)
    };
    Impact {
        hitstop: t.hitstop_min + (t.hitstop_max - t.hitstop_min) * f,
        trauma: t.trauma_min + (t.trauma_max - t.trauma_min) * f,
        flash: f >= t.flash_at,
    }
}

pub fn float_text(t: f64, k: &FloatTuning) -> FloatText {
    let u = if k.life > 0.0 {
        (t / k.life).clamp(0.0, 1.0)
    } else {
        1.0
    };
    FloatText {
        dy: -k.rise * Ease::OutCubic.apply(u),
        scale: if k.pop_s > 0.0 {
            Ease::OutBack.apply(t / k.pop_s)
        } else {
            1.0
        },
        alpha: 1.0 - Ease::InCubic.apply(u),
        done: t >= k.life,
    }
}

fn seg(a: [f64; 2], b: [f64; 2]) -> f64 {
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    (dx * dx + dy * dy).sqrt()
}

/// Total length, tail to head (summed in order, as the reference does).
pub fn trail_length(points: &[[f64; 2]]) -> f64 {
    points.windows(2).map(|w| seg(w[0], w[1])).fold(0.0, |a, s| a + s)
}

fn trim_to(mut pts: Vec<[f64; 2]>, keep: f64) -> Vec<[f64; 2]> {
    let mut excess = trail_length(&pts) - keep.max(0.0);
    while excess > EPS && pts.len() > 1 {
        let s = seg(pts[0], pts[1]);
        if s <= excess + EPS {
            pts.remove(0);
            excess -= s;
        } else {
            let k = excess / s;
            pts[0] = [
                pts[0][0] + (pts[1][0] - pts[0][0]) * k,
                pts[0][1] + (pts[1][1] - pts[0][1]) * k,
            ];
            excess = 0.0;
        }
    }
    pts
}

/// A tracer's path: the head follows (x, y); a new point is kept once the head is `spacing` past the point before
/// it (by distance, not frame); longer than max_len, the tail is cut.
pub fn trail_push(points: &[[f64; 2]], x: f64, y: f64, spacing: f64, max_len: f64) -> Vec<[f64; 2]> {
    let mut pts = points.to_vec();
    let n = pts.len();
    if n < 2 || seg(pts[n - 2], pts[n - 1]) >= spacing {
        pts.push([x, y]);
    } else {
        pts[n - 1] = [x, y];
    }
    trim_to(pts, max_len)
}

/// The tail catching up after the shot dies: remove `amount` px from the tail (fewer than two points: draw nothing).
pub fn trail_shrink(points: &[[f64; 2]], amount: f64) -> Vec<[f64; 2]> {
    trim_to(points.to_vec(), trail_length(points) - amount)
}

// {{FOOTER}}
