// ---------------------------------------------------------------------------
// logic/mod.rs
// Purpose : Engine-free game logic: the whole race (track, karts, items, the changing sections, bots) as plain
//           Rust that never touches the ECS, so it is unit tested in milliseconds and bots race it in tests.
// Usage   : use crate::logic::{race::Race, bots, tuning};
// Notes   : Bevy types are allowed here only for plain math (bevy::math is glam: vectors, no ECS). The game/
//           plugins wrap Race in a resource, feed it inputs every fixed tick and draw what it holds.
//           Named `logic`, not `core`: a module called core shadows Rust's own core crate in macro paths.
//           The juice and shell modules are the kit's ports of tools/golden_vectors.py (f64, like the
//           reference): tests/golden.rs checks them against data/golden/*.json. The race does not use them yet.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): the kit's juice and shell modules
// ---------------------------------------------------------------------------
pub mod bots;
pub mod kart;
pub mod math;
pub mod race;
pub mod rng;
pub mod track;
pub mod tuning;

// Juice: game feel (kit modules)
pub mod coyote;
pub mod ease;
pub mod flash_limiter;
pub mod follow;
pub mod hitstop;
pub mod input_buffer;
pub mod shake;
pub mod spring;

// Shell: settings, input, saves, text (kit modules)
pub mod atomic_file;
pub mod bindings;
pub mod i18n;
pub mod save_store;
pub mod settings;
