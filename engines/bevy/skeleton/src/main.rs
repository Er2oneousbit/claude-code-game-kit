// ---------------------------------------------------------------------------
// main.rs
// Purpose : Program entry: parse the command line, read the game options, build the App, run it, and turn
//           Bevy's AppExit into the process exit code dev.py reads.
// Usage   : {{GAME_SLUG}} [--debug] [--smoke N] [--screenshot FILE.png] [--record DIR] [-- game options]
//           (normally through python tools/dev.py run | smoke; --help lists everything)
// Notes   : Exit 0 ok, 1 the game failed (AppExit::Error), 2 bad command line, 101 a Rust panic.
//           Release builds on Windows hide the console window (windows_subsystem); dev.py still reads the
//           output, because it passes its own pipes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::ExitCode;

use bevy::app::AppExit;

use {{GAME_SLUG}}::{app, cli, game};

fn main() -> ExitCode {
    let cli = match cli::parse(std::env::args().skip(1)) {
        Ok(cli) => cli,
        Err(msg) => {
            eprintln!("[error] {msg}\n{}{}", cli::HELP, game::OPTIONS_HELP);
            return ExitCode::from(2);
        }
    };
    if cli.help {
        print!("{}{}", cli::HELP, game::OPTIONS_HELP);
        return ExitCode::SUCCESS;
    }
    if cli.version {
        println!("{} {}", env!("CARGO_PKG_NAME"), env!("CARGO_PKG_VERSION"));
        return ExitCode::SUCCESS;
    }
    let cfg = match game::configure(&cli.game_args) {
        Ok(cfg) => cfg,
        Err(msg) => {
            eprintln!("[error] {msg}");
            return ExitCode::from(2);
        }
    };
    match app::build(&cli, cfg).run() {
        AppExit::Success => ExitCode::SUCCESS,
        AppExit::Error(code) => ExitCode::from(code.get()),
    }
}

// {{FOOTER}}
