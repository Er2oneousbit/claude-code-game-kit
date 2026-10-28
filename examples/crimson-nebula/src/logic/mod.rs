// ---------------------------------------------------------------------------
// logic/mod.rs
// Purpose : Engine-free game logic: the whole race (track, karts, items, the changing sections, bots) as plain
//           Rust that never touches the ECS, so it is unit tested in milliseconds and bots race it in tests.
// Usage   : use crate::logic::{race::Race, bots, tuning};
// Notes   : Bevy types are allowed here only for plain math (bevy::math is glam: vectors, no ECS). The game/
//           plugins wrap Race in a resource, feed it inputs every fixed tick and draw what it holds.
//           Named `logic`, not `core`: a module called core shadows Rust's own core crate in macro paths.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
pub mod bots;
pub mod kart;
pub mod math;
pub mod race;
pub mod rng;
pub mod track;
pub mod tuning;
