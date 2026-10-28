// ---------------------------------------------------------------------------
// lib.rs
// Purpose : The game as a library: main.rs is a thin launcher, and the tests in tests/ build the same App
//           headless through app::test_app.
// Usage   : use project_crimson_nebula::{app, game, logic};
// Notes   : Layout (docs/ENGINE.md): logic/ engine-free rules, game/ simulation plugin, game/present.rs
//           visuals and input, app.rs plugin sets per run mode, cli.rs command line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
pub mod app;
pub mod cli;
pub mod game;
pub mod logic;
