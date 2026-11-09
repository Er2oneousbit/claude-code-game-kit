// ---------------------------------------------------------------------------
// shell/store.rs
// Purpose : Where the player's files live (settings.json, saves) and the data files the shell reads (string tables,
//           the one-handed layouts, the colour-blind palettes): the built-in copies compiled into the exe, with the
//           project's data/ folder on top when it is there.
// Usage   : let store = Store::new(cfg.data_dir.clone());   store.settings_path()
//           store.read_data("i18n/en.json")   // the file under data/, or None
//           store::builtin_tables()            // the string tables compiled in (data/i18n/*.json at build time)
// Notes   : The user-data folder follows the platform: %APPDATA%/<game> on Windows, ~/Library/Application Support/
//           <game> on macOS, $XDG_DATA_HOME or ~/.local/share/<game> elsewhere. An automated run (dev.py smoke) always
//           passes --data-dir, so a test never touches the player's files. data/ is found next to the exe, then in
//           the working folder, then in the project (CARGO_MANIFEST_DIR, for cargo run and the tests).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
use std::path::{Path, PathBuf};

// ---- Built-in data (ships inside the exe, so a missing data/ folder never breaks the shell) --------------------
pub const BUILTIN_I18N: &[(&str, &str)] = &[
    ("en", include_str!("../../data/i18n/en.json")),
    ("fr", include_str!("../../data/i18n/fr.json")),
];
pub const BUILTIN_PRESETS: &str = include_str!("../../data/input/presets.json");
pub const BUILTIN_COLOURS: &str = include_str!("../../data/access/colours.json");

pub const SETTINGS_FILE: &str = "settings.json";
pub const I18N_DIR: &str = "i18n";

#[derive(Debug, Clone)]
pub struct Store {
    /// The player's files (settings, saves).
    pub data_dir: PathBuf,
    /// The project's data/ folder, when one was found.
    pub project_data: Option<PathBuf>,
}

impl Store {
    pub fn new(data_dir: Option<PathBuf>) -> Store {
        Store {
            data_dir: data_dir.unwrap_or_else(|| user_data_dir(env!("CARGO_PKG_NAME"))),
            project_data: find_project_data(),
        }
    }

    pub fn settings_path(&self) -> PathBuf {
        self.data_dir.join(SETTINGS_FILE)
    }

    /// A file under data/ as text, or None (no data folder, no such file, not UTF-8).
    pub fn read_data(&self, relative: &str) -> Option<String> {
        let dir = self.project_data.as_ref()?;
        std::fs::read_to_string(dir.join(relative)).ok()
    }

    /// The locale files under data/i18n/: (locale, text), sorted by name.
    pub fn data_locales(&self) -> Vec<(String, String)> {
        let mut out = Vec::new();
        let Some(dir) = self.project_data.as_ref() else {
            return out;
        };
        if let Ok(entries) = std::fs::read_dir(dir.join(I18N_DIR)) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().and_then(|e| e.to_str()) != Some("json") {
                    continue;
                }
                if let (Some(stem), Ok(text)) = (
                    path.file_stem().and_then(|s| s.to_str()),
                    std::fs::read_to_string(&path),
                ) {
                    out.push((stem.to_string(), text));
                }
            }
        }
        out.sort();
        out
    }
}

/// The platform's folder for this game's files.
pub fn user_data_dir(game: &str) -> PathBuf {
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let base = if cfg!(target_os = "windows") {
        std::env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(|| home.join("AppData").join("Roaming"))
    } else if cfg!(target_os = "macos") {
        home.join("Library").join("Application Support")
    } else {
        std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local").join("share"))
    };
    base.join(game)
}

/// data/ next to the exe, in the working folder, or in the project.
fn find_project_data() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe()
        && let Some(dir) = exe.parent()
    {
        candidates.push(dir.join("data"));
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("data"));
    }
    candidates.push(Path::new(env!("CARGO_MANIFEST_DIR")).join("data"));
    candidates.into_iter().find(|p| p.is_dir())
}

// {{FOOTER}}
