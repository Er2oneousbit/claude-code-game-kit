// ---------------------------------------------------------------------------
// shell/bug_report.rs
// Purpose : The bug-report key (F8 in debug builds, SOP-19 section 7): bundles info.txt (name, version, time,
//           screen, locale, build, os), log_tail.txt, settings.json and a screenshot into bug_<time>/ in the
//           user-data folder, so a tester attaches one folder.
// Usage   : view.rs calls shell.bug_key() on F8; ShellPlugin runs bug_report::capture every frame, which writes the
//           files a frame later and asks the window for the screenshot. shell.last_bug_report is the folder once
//           everything is on disk (the `bug` drive waits for it).
// Notes   : Release builds ignore the key (a player's F8 belongs to the game). Headless runs (tests, `smoke` without
//           a window) get the text files without a screenshot. Nothing leaves the machine.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::{Path, PathBuf};

use bevy::prelude::*;
use bevy::render::view::screenshot::{Screenshot, ScreenshotCaptured, save_to_disk};
use bevy::window::PrimaryWindow;

use super::{Shell, crash};

// ---- Tunables ------------------------------------------------------------------
/// Log lines the report keeps.
pub const TAIL_LINES: usize = 200;
pub const FILES: [&str; 4] = ["info.txt", "log_tail.txt", "settings.json", "screenshot.png"];

/// Writes the text files of a report into a new bug_<stamp>/ under the data folder; returns the folder.
pub fn write_files(shell: &Shell, data_dir: &Path) -> std::io::Result<PathBuf> {
    std::fs::create_dir_all(data_dir)?;
    let dir = crash::unique_path(data_dir, "bug", "");
    std::fs::create_dir_all(&dir)?;
    let info = [
        format!("{} {}", crate::game::TITLE, env!("CARGO_PKG_VERSION")),
        format!("time: {}", crash::iso_now()),
        format!("screen: {}", shell.top_name().map_or("none", |s| s.as_str())),
        format!("locale: {}", shell.language()),
        format!("build: {}", crash::build_kind()),
        format!("os: {} {}", std::env::consts::OS, std::env::consts::ARCH),
    ]
    .join("\n");
    std::fs::write(dir.join("info.txt"), info + "\n")?;
    std::fs::write(dir.join("log_tail.txt"), crash::tail(TAIL_LINES) + "\n")?;
    let settings = serde_json::to_string_pretty(&shell.settings).unwrap_or_default();
    std::fs::write(dir.join("settings.json"), settings + "\n")?;
    Ok(dir)
}

/// The finished folder: logs it, toasts it, and records it for the drive.
fn finished(shell: &mut Shell, dir: PathBuf) {
    info!("bug: report saved to {}", dir.display());
    let text = shell.t("toast.bug_saved");
    shell.toast(text);
    shell.last_bug_report = Some(dir);
}

/// Answers a pending F8: the text files now, the screenshot from the window (when there is one).
pub fn capture(mut commands: Commands, mut shell: ResMut<Shell>, windows: Query<(), With<PrimaryWindow>>) {
    if !std::mem::take(&mut shell.bug_requested) {
        return;
    }
    let data_dir = shell.store.data_dir.clone();
    let dir = match write_files(&shell, &data_dir) {
        Ok(dir) => dir,
        Err(e) => {
            error!("bug: report not saved: {e}");
            return;
        }
    };
    if windows.is_empty() {
        finished(&mut shell, dir);
        return;
    }
    // the window's next frame: save_to_disk writes the PNG, then the second observer marks the report done
    let shot = dir.join("screenshot.png");
    commands
        .spawn(Screenshot::primary_window())
        .observe(save_to_disk(shot))
        .observe(move |_: On<ScreenshotCaptured>, mut shell: ResMut<Shell>| {
            finished(&mut shell, dir.clone());
        });
}

// {{FOOTER}}
