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
//           The audio modules are ports of tools/audio/wavesmith/ (audio_events.py, music.py, access.py): they
//           only decide (which file, pitch, gain, duck, when the music changes); a Bevy audio system plays it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): the kit's juice and shell modules
//           2026-11-10 with Claude (Fable 5.1, claude-fable-5-1): auto_repeat (hold to mash, #166)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): analog (stick and trigger shaping, #265)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): charmap (which characters a font can draw)
//           2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): display_staging (the Display tab's Apply, #308),
//           hud_scale (a game HUD's text size, #309)
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
pub mod analog;
pub mod atomic_file;
pub mod auto_repeat;
pub mod bindings;
pub mod charmap;
pub mod display_staging;
pub mod hud_scale;
pub mod i18n;
pub mod save_store;
pub mod settings;

// Audio: sound events, adaptive music, accessibility (kit modules)
pub mod audio_access;
pub mod audio_director;
pub mod music_director;
