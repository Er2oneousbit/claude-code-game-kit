// ---------------------------------------------------------------------------
// shell/crash.rs
// Purpose : Crash files (SOP-19 section 7): a panic writes crashes/crash_<time>.txt into the user-data folder with
//           the version, the build, the screen, the error and where it happened, the backtrace, the settings and the
//           log tail, then prints CRASH_WRITTEN <path> (dev.py smoke echoes it). Also keeps the log tail itself (the
//           last lines this run logged), which the F8 bug report reads too.
// Usage   : main.rs: crash::install_panic_hook()   (after the App is built, so it wraps any hook Bevy set)
//           app.rs:  LogPlugin { custom_layer: crash::log_layer, .. }   (feeds the tail)
//           crash::tail(50) -> the last 50 log lines;  crash::stamp() -> "20261110_142233" (UTC)
//           the shell keeps the context current (crash::track runs every frame in ShellPlugin)
// Notes   : A panic hook runs on the thread that panicked, possibly while another thread holds a lock, so it only
//           ever try_locks (a busy lock means that part of the report says "(busy)") and never panics itself: a
//           crash report must not hide the crash. Only the first panic writes a file (a panic while unwinding from
//           another one would only repeat it). Before the shell starts (a panic during startup) the file goes to
//           the platform's user-data folder. The tests never install the hook; they check report() and write().
//
// Pseudocode:
//   panic -> once: report(context, message, location, backtrace, tail) -> crashes/crash_<stamp>[_n].txt
//   -> print CRASH_WRITTEN <path> -> the previous hook prints the panic as before (dev.py fails on "panicked at")
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::VecDeque;
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use bevy::log::BoxedLayer;
use bevy::log::tracing::field::{Field, Visit};
use bevy::log::tracing::{Event, Subscriber};
use bevy::log::tracing_subscriber::Layer;
use bevy::log::tracing_subscriber::layer::Context;
use bevy::prelude::*;

use super::Shell;

// ---- Tunables ------------------------------------------------------------------
/// The crash files' folder under the user-data folder.
pub const CRASH_DIR: &str = "crashes";
/// Log lines kept in memory for crash files and bug reports.
pub const TAIL_KEEP: usize = 200;
/// Log lines a crash file quotes.
pub const CRASH_TAIL: usize = 60;
/// crash_<stamp>_2.txt ... when several crashes share a second.
const MAX_SAME_SECOND: u32 = 50;

/// What the shell knows that a crash file should say (the shell refreshes it; the hook reads it).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct CrashContext {
    pub data_dir: Option<PathBuf>,
    pub screen: String,
    pub locale: String,
    /// settings.json as it is in memory (pretty JSON).
    pub settings: String,
}

static CONTEXT: Mutex<Option<CrashContext>> = Mutex::new(None);
static TAIL: Mutex<VecDeque<String>> = Mutex::new(VecDeque::new());
static WROTE: AtomicBool = AtomicBool::new(false);

// ---- The log tail ----------------------------------------------------------------------------------------------
/// Adds one line to the tail (the log layer does this for every log event that passes the filter).
pub fn remember(line: String) {
    if let Ok(mut tail) = TAIL.lock() {
        if tail.len() >= TAIL_KEEP {
            tail.pop_front();
        }
        tail.push_back(line);
    }
}

/// The last `n` log lines, oldest first, one per line ("" when nothing was logged; "(busy)" if the log is locked).
pub fn tail(n: usize) -> String {
    match TAIL.try_lock() {
        Ok(tail) => {
            let skip = tail.len().saturating_sub(n);
            tail.iter().skip(skip).cloned().collect::<Vec<_>>().join("\n")
        }
        Err(_) => "(busy)".into(),
    }
}

/// Collects an event's message and fields as one line of text.
struct LineVisitor(String);

impl Visit for LineVisitor {
    fn record_debug(&mut self, field: &Field, value: &dyn std::fmt::Debug) {
        if field.name() == "message" {
            let _ = write!(self.0, "{value:?}");
        } else if !field.name().starts_with("log.") {
            // (log.target, log.file ...: the log crate's bookkeeping on lines from dependencies, noise here)
            let _ = write!(self.0, " {}={value:?}", field.name());
        }
    }
}

/// A tracing layer that copies every log event into the tail: "WARN game::shell: settings: fixed audio.master".
pub struct TailLayer;

impl<S: Subscriber> Layer<S> for TailLayer {
    fn on_event(&self, event: &Event<'_>, _ctx: Context<'_, S>) {
        let mut visitor = LineVisitor(String::new());
        event.record(&mut visitor);
        let meta = event.metadata();
        remember(format!("{} {}: {}", meta.level(), meta.target(), visitor.0));
    }
}

/// LogPlugin's custom_layer (app.rs): the tail layer.
pub fn log_layer(_app: &mut App) -> Option<BoxedLayer> {
    Some(Box::new(TailLayer))
}

// ---- Time without a date crate ----------------------------------------------------------------------------------
/// (year, month, day, hour, minute, second) in UTC for seconds since 1970 (Howard Hinnant's civil_from_days).
pub fn utc(secs: u64) -> (i64, u32, u32, u32, u32, u32) {
    let days = (secs / 86_400) as i64;
    let rest = secs % 86_400;
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let year = yoe + era * 400 + i64::from(month <= 2);
    (
        year,
        month,
        day,
        (rest / 3600) as u32,
        (rest / 60 % 60) as u32,
        (rest % 60) as u32,
    )
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

/// "20261110_142233" (UTC): file and folder names.
pub fn stamp_at(secs: u64) -> String {
    let (y, mo, d, h, mi, s) = utc(secs);
    format!("{y:04}{mo:02}{d:02}_{h:02}{mi:02}{s:02}")
}

pub fn stamp() -> String {
    stamp_at(now_secs())
}

/// "2026-11-10T14:22:33Z": inside the files.
pub fn iso_at(secs: u64) -> String {
    let (y, mo, d, h, mi, s) = utc(secs);
    format!("{y:04}-{mo:02}-{d:02}T{h:02}:{mi:02}:{s:02}Z")
}

pub fn iso_now() -> String {
    iso_at(now_secs())
}

/// `dir/<prefix>_<stamp><ext>`, with _2, _3 ... when that name is taken (several in one second).
pub fn unique_path(dir: &Path, prefix: &str, ext: &str) -> PathBuf {
    let base = format!("{prefix}_{}", stamp());
    let mut path = dir.join(format!("{base}{ext}"));
    let mut n = 1;
    while path.exists() && n < MAX_SAME_SECOND {
        n += 1;
        path = dir.join(format!("{base}_{n}{ext}"));
    }
    path
}

// ---- The context ------------------------------------------------------------------------------------------------
/// Replaces what the next crash file says about the run.
pub fn set_context(ctx: CrashContext) {
    if let Ok(mut slot) = CONTEXT.lock() {
        *slot = Some(ctx);
    }
}

fn context() -> CrashContext {
    match CONTEXT.try_lock() {
        Ok(slot) => slot.clone().unwrap_or_default(),
        Err(_) => CrashContext {
            screen: "(busy)".into(),
            ..CrashContext::default()
        },
    }
}

/// ShellPlugin runs this every frame: the context follows the shell (only when something on screen changed).
pub fn track(mut last: Local<Option<u64>>, shell: Res<Shell>) {
    if *last == Some(shell.version) {
        return;
    }
    *last = Some(shell.version);
    set_context(CrashContext {
        data_dir: Some(shell.store.data_dir.clone()),
        screen: shell.top_name().map_or("none", |s| s.as_str()).to_string(),
        locale: shell.language(),
        settings: serde_json::to_string_pretty(&shell.settings).unwrap_or_default(),
    });
}

/// "debug" or "release".
pub fn build_kind() -> &'static str {
    if cfg!(debug_assertions) { "debug" } else { "release" }
}

// ---- The report ---------------------------------------------------------------------------------------------------
/// The crash file's text (separate from writing it, so tests check it without a panic).
pub fn report(ctx: &CrashContext, message: &str, location: &str, backtrace: &str, log_tail: &str) -> String {
    let mut out = String::new();
    let lines = [
        format!("{} crash report", crate::game::TITLE),
        format!("version: {}", env!("CARGO_PKG_VERSION")),
        format!("time: {}", iso_now()),
        format!("build: {}", build_kind()),
        format!("os: {} {}", std::env::consts::OS, std::env::consts::ARCH),
        format!("screen: {}", if ctx.screen.is_empty() { "none" } else { &ctx.screen }),
        format!("locale: {}", if ctx.locale.is_empty() { "none" } else { &ctx.locale }),
        String::new(),
        format!("error: {message}"),
        format!("at: {}", if location.is_empty() { "unknown" } else { location }),
        String::new(),
        "backtrace:".into(),
        backtrace.trim_end().to_string(),
        String::new(),
        "settings:".into(),
        if ctx.settings.is_empty() {
            "(not loaded yet)".into()
        } else {
            ctx.settings.clone()
        },
        String::new(),
        "log tail:".into(),
        if log_tail.is_empty() {
            "(no log lines)".into()
        } else {
            log_tail.to_string()
        },
    ];
    for line in lines {
        out.push_str(&line);
        out.push('\n');
    }
    out
}

/// Writes `text` as crashes/crash_<stamp>.txt under `data_dir`; returns the file's path.
pub fn write(data_dir: &Path, text: &str) -> std::io::Result<PathBuf> {
    let dir = data_dir.join(CRASH_DIR);
    std::fs::create_dir_all(&dir)?;
    let path = unique_path(&dir, "crash", ".txt");
    std::fs::write(&path, text)?;
    Ok(path)
}

/// The panic's message: the &str or String it carried.
fn panic_message(info: &std::panic::PanicHookInfo<'_>) -> String {
    let payload = info.payload();
    if let Some(s) = payload.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else {
        "a panic without a message".into()
    }
}

/// Installs the hook: the first panic writes a crash file, then the previous hook runs as it always did.
pub fn install_panic_hook() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if !WROTE.swap(true, Ordering::SeqCst) {
            let ctx = context();
            let location = info
                .location()
                .map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()))
                .unwrap_or_default();
            let backtrace = std::backtrace::Backtrace::force_capture().to_string();
            let text = report(&ctx, &panic_message(info), &location, &backtrace, &tail(CRASH_TAIL));
            let dir = ctx
                .data_dir
                .clone()
                .unwrap_or_else(|| super::store::user_data_dir(env!("CARGO_PKG_NAME")));
            match write(&dir, &text) {
                Ok(path) => println!("CRASH_WRITTEN {}", path.display()),
                Err(e) => eprintln!("[error] crash report not written to {}: {e}", dir.display()),
            }
        }
        previous(info);
    }));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utc_dates_match_known_instants() {
        assert_eq!(utc(0), (1970, 1, 1, 0, 0, 0));
        assert_eq!(utc(1_700_000_000), (2023, 11, 14, 22, 13, 20));
        assert_eq!(utc(951_782_400), (2000, 2, 29, 0, 0, 0), "a leap day");
        assert_eq!(stamp_at(1_700_000_000), "20231114_221320");
        assert_eq!(iso_at(1_700_000_000), "2023-11-14T22:13:20Z");
    }

    #[test]
    fn the_report_names_the_version_error_settings_and_tail() {
        let ctx = CrashContext {
            data_dir: None,
            screen: "play".into(),
            locale: "fr".into(),
            settings: "{\"audio\": {}}".into(),
        };
        let text = report(
            &ctx,
            "boom",
            "src/game/mod.rs:9:5",
            "0: main",
            "INFO x: one\nWARN x: two",
        );
        for want in [
            "crash report",
            &format!("version: {}", env!("CARGO_PKG_VERSION")),
            "screen: play",
            "locale: fr",
            "error: boom",
            "at: src/game/mod.rs:9:5",
            "backtrace:\n0: main",
            "settings:\n{\"audio\": {}}",
            "log tail:\nINFO x: one\nWARN x: two",
        ] {
            assert!(text.contains(want), "{want:?} missing from:\n{text}");
        }
        let bare = report(&CrashContext::default(), "x", "", "", "");
        assert!(bare.contains("(not loaded yet)") && bare.contains("(no log lines)") && bare.contains("at: unknown"));
    }

    #[test]
    fn write_puts_each_crash_in_a_file_of_its_own() {
        let dir = std::env::temp_dir().join(format!("{}-crash-{}", env!("CARGO_PKG_NAME"), std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let a = write(&dir, "one").unwrap();
        let b = write(&dir, "two").unwrap();
        assert_ne!(a, b, "two crashes in one second keep both files");
        assert_eq!(std::fs::read_to_string(&a).unwrap(), "one");
        assert!(a.starts_with(dir.join(CRASH_DIR)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_tail_keeps_the_newest_lines() {
        for i in 0..(TAIL_KEEP + 5) {
            remember(format!("tail-test {i}"));
        }
        let last = tail(2);
        assert!(last.ends_with(&format!("tail-test {}", TAIL_KEEP + 4)), "{last}");
        assert_eq!(last.lines().count(), 2);
    }
}
