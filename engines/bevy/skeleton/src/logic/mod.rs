// ---------------------------------------------------------------------------
// logic/mod.rs
// Purpose : Engine-free game logic: plain Rust that never touches the ECS, so it is unit tested in
//           milliseconds and reused by bots, tools and tests.
// Usage   : use crate::logic::{math, rng::Rng, shake::Shake, settings};
// Notes   : Keep Bevy types out of here except plain math (bevy::math is glam: vectors, no ECS). Rules,
//           tuning formulas, track or level generation and scoring belong here; systems in game/ call them.
//           Named `logic`, not `core`: a module called core shadows Rust's own core crate in macro paths.
//           The juice and shell modules are ports of tools/golden_vectors.py (f64, like the reference):
//           tests/golden.rs checks them against data/golden/*.json, the same vectors every engine passes.
//           The audio modules are ports of tools/audio/wavesmith/ (audio_events.py, music.py, access.py): they
//           only decide (which file, pitch, gain, duck, when the music changes); your Bevy audio system plays it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): juice and shell modules
//           2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): audio director, music director, audio access
// ---------------------------------------------------------------------------
pub mod math;
pub mod rng;

// Juice: game feel
pub mod coyote;
pub mod ease;
pub mod flash_limiter;
pub mod follow;
pub mod hitstop;
pub mod input_buffer;
pub mod shake;
pub mod spring;

// Shell: settings, input, saves, text
pub mod atomic_file;
pub mod bindings;
pub mod i18n;
pub mod save_store;
pub mod settings;

// Audio: sound events, adaptive music, accessibility
pub mod audio_access;
pub mod audio_director;
pub mod music_director;

// {{FOOTER}}
