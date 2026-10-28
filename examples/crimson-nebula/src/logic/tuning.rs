// ---------------------------------------------------------------------------
// logic/tuning.rs
// Purpose : Every number that decides how the race feels, in one place (docs/GDD.md "Tunables that define feel").
// Usage   : use crate::logic::tuning::*;   change a value, `python tools/dev.py test`, then play
// Notes   : Units are meters, seconds and radians. One kart is about 2 m long, the track 14 m wide, a lap about
//           1.1 km. Tests read these constants, so they keep passing when a value is retuned within reason.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Kart --------------------------------------------------------------------
/// Collision circle radius (m).
pub const KART_RADIUS: f32 = 1.0;
/// Top speed on throttle (m/s): 26 m/s is about 94 km/h, quick for a 14 m wide track.
pub const TOP_SPEED: f32 = 26.0;
/// Acceleration toward top speed (m/s^2).
pub const ACCEL: f32 = 13.0;
/// Braking (m/s^2).
pub const BRAKE: f32 = 32.0;
/// Reverse top speed (m/s).
pub const REVERSE_SPEED: f32 = 7.0;
/// Rolling slowdown with no throttle (m/s^2).
pub const COAST_DRAG: f32 = 5.0;
/// Turn rate at full steer (rad/s). Turning circle radius at top speed = TOP_SPEED / TURN_RATE.
pub const TURN_RATE: f32 = 2.0;
/// Speed (m/s) at which steering reaches its full rate; slower karts turn less (no spinning on the spot).
pub const TURN_FULL_AT: f32 = 7.0;
/// How quickly the kart's motion follows its nose (1/s): high = on rails, low = slides.
pub const GRIP: f32 = 14.0;
/// Grip while drifting: the kart slides wide.
pub const DRIFT_GRIP: f32 = 4.5;
/// Extra turn rate while drifting.
pub const DRIFT_TURN_BONUS: f32 = 1.3;
/// Minimum speed to start or hold a drift (m/s).
pub const DRIFT_MIN_SPEED: f32 = 10.0;
/// Seconds of steering-while-drifting needed for a mini boost on release.
pub const DRIFT_CHARGE_MIN: f32 = 0.9;
/// Mini boost length after a charged drift (s).
pub const MINI_BOOST_TIME: f32 = 0.5;

// ---- Boost item --------------------------------------------------------------
pub const BOOST_TIME: f32 = 1.5;
/// Top speed multiplier while boosting.
pub const BOOST_SPEED_MULT: f32 = 1.45;
/// Acceleration while boosting (m/s^2).
pub const BOOST_ACCEL: f32 = 40.0;

// ---- Contact -----------------------------------------------------------------
/// Speed kept after hitting a wall or barrier head-on (scraping along keeps more).
pub const WALL_SPEED_KEEP: f32 = 0.55;
/// Speed kept after touching a closed lane's barrier: an energy wall that zaps you (pillar 1: not reading the
/// change has to cost something).
pub const CLOSURE_ZAP_KEEP: f32 = 0.45;
/// Seconds between zaps while a kart scrapes along a barrier.
pub const ZAP_COOLDOWN: f32 = 1.0;
/// Impact speed (m/s into the wall) that counts as a bonk (a log line, a sound later).
pub const BONK_MIN_IMPACT: f32 = 3.0;
/// Bounciness of kart-to-kart bumps: 0 = they stick on contact, 1 = they bounce apart at full speed.
pub const BUMP_BOUNCE: f32 = 0.3;

// ---- Track -------------------------------------------------------------------
pub const TRACK_HALF_WIDTH: f32 = 7.0;
pub const SHORTCUT_HALF_WIDTH: f32 = 4.0;
/// Shortcuts leave and rejoin the loop along it for this many meters (a curve in, not a corner).
pub const SHORTCUT_BRANCH: f32 = 35.0;
/// A closed lane blocks its half of the track plus this much past the center line (m).
pub const CLOSURE_PAST_CENTER: f32 = 1.0;
/// A closed lane's barrier reaches full width over this many meters (a funnel, not a wall face).
pub const CLOSURE_TAPER: f32 = 15.0;
/// Spline sampling step for track centerlines (m).
pub const TRACK_STEP: f32 = 2.0;

// ---- Changes (the twist) -----------------------------------------------------
/// The warning glow starts when the leader is WARN_TIME at its current speed plus this many meters from the
/// changing section, so even a boosting leader has this much road left to turn in when the change goes live.
pub const WARN_LEAD: f32 = 30.0;
/// Seconds between the warning glow and the change going live.
pub const WARN_TIME: f32 = 2.0;

// ---- Items -------------------------------------------------------------------
pub const ITEM_BOX_RADIUS: f32 = 1.2;
/// Seconds before a taken box reappears.
pub const ITEM_RESPAWN: f32 = 3.0;

// ---- Race --------------------------------------------------------------------
pub const LAPS: u32 = 3;
pub const COUNTDOWN: f32 = 3.0;
/// The race ends this long after the player finishes, even if rivals are still driving (s).
pub const FINISH_GRACE: f32 = 12.0;
/// Hard stop for a race nobody finishes (s): a stuck bot cannot hang a smoke run.
pub const RACE_TIME_LIMIT: f32 = 400.0;

// ---- Rival AI ----------------------------------------------------------------
/// How far ahead along its path a bot aims (m), plus a share of its speed.
pub const AI_LOOKAHEAD: f32 = 8.0;
pub const AI_LOOKAHEAD_PER_SPEED: f32 = 0.35;
/// Share of the lookahead used on a (narrow) shortcut.
pub const AI_SHORTCUT_LOOK_SHARE: f32 = 0.55;
/// Steering response to the heading error.
pub const AI_STEER_GAIN: f32 = 2.8;
/// Heading error (rad) above which a bot lifts off the throttle.
pub const AI_LIFT_ANGLE: f32 = 0.55;
/// Spacing (m) of the points a bot uses to measure bends ahead.
pub const AI_CURVE_STEP: f32 = 4.0;
/// Share of the kart's possible cornering speed a bot dares to use.
pub const AI_CORNER_MARGIN: f32 = 0.9;
/// Share of full braking a bot plans with.
pub const AI_BRAKE_SHARE: f32 = 0.7;
/// A bot never plans slower than this (m/s), so it cannot stall on a hairpin.
pub const AI_MIN_CORNER_SPEED: f32 = 6.0;
/// How far ahead (m) a bot looks for warnings to react to.
pub const AI_SIGHT: f32 = 120.0;
/// A kart this far ahead (m) and within AI_PASS_WIDTH of a bot's line gets overtaken.
pub const AI_PASS_LOOK: f32 = 14.0;
/// Sideways room (m) a bot leaves when it passes.
pub const AI_PASS_WIDTH: f32 = 3.0;
/// Lateral offset (m) a bot drives at when it dodges a closed lane.
pub const AI_DODGE_OFFSET: f32 = 3.8;
