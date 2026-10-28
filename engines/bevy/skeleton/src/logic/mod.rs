// ---------------------------------------------------------------------------
// logic/mod.rs
// Purpose : Engine-free game logic: plain Rust that never touches the ECS, so it is unit tested in
//           milliseconds and reused by bots, tools and tests.
// Usage   : use crate::logic::{math, rng::Rng};
// Notes   : Keep Bevy types out of here except plain math (bevy::math is glam: vectors, no ECS). Rules,
//           tuning formulas, track or level generation and scoring belong here; systems in game/ call them.
//           Named `logic`, not `core`: a module called core shadows Rust's own core crate in macro paths.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
pub mod math;
pub mod rng;

// {{FOOTER}}
