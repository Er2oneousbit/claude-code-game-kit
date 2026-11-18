// ---------------------------------------------------------------------------
// logic/platform_steam.rs
// Purpose : The Steam backend for the platform layer (#84, docs/PLATFORM.md). The mapping (which Steam call each
//           platform call becomes) is plain Rust over the SteamApi trait, so it is unit tested with a fake; the real
//           SteamApi is the steamworks crate (MIT OR Apache-2.0), compiled only with `cargo build --features steam`.
// Usage   : let backend = platform_steam::make(&defs, &data_dir, automated);   // None: the null backend
//           tests: SteamBackend::new(defs, data_dir, Box::new(fake))
// Notes   : Off by default: without the feature nothing below `#[cfg(feature = "steam")]` is built and the game
//           runs the null backend exactly as before. The feature pulls the steamworks crate, whose -sys crate
//           carries Valve's redistributable SDK files; read the Steamworks SDK access agreement before you ship it
//           (verify). bevy_steamworks (0.17) is the Bevy plugin over the same crate, but it targets Bevy 0.19, not
//           this project's 0.20 (checked 2026-11-18), so the kit calls steamworks directly. The steamworks 0.13 calls
//           (Client::init, user_stats().achievement(id).set/get, set_stat_i32 / set_stat_f32, store_stats,
//           reset_all_stats, friends().set_rich_presence / clear_rich_presence, remote_storage().file(name).write,
//           register_callback(GameOverlayActivated), run_callbacks) are written from its docs and never compiled
//           here (verify with the feature on). Only store_stats failing counts as a failed store (verify).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use serde_json::{Value, json};

use crate::logic::platform::Backend;

/// The Steam calls the backend needs (ISteamUserStats, ISteamFriends, ISteamRemoteStorage).
pub trait SteamApi: Send + Sync {
    fn set_achievement(&mut self, id: &str) -> bool;
    fn achieved(&mut self, id: &str) -> Option<bool>;
    fn set_stat_int(&mut self, id: &str, v: i32) -> bool;
    fn set_stat_float(&mut self, id: &str, v: f32) -> bool;
    fn stat_int(&mut self, id: &str) -> Option<i32>;
    fn stat_float(&mut self, id: &str) -> Option<f32>;
    fn store_stats(&mut self) -> bool;
    fn indicate_progress(&mut self, id: &str, current: u32, max: u32) -> bool;
    fn reset_all_stats(&mut self, achievements: bool) -> bool;
    fn set_rich_presence(&mut self, key: &str, value: &str) -> bool;
    fn clear_rich_presence(&mut self);
    fn file_write(&mut self, name: &str, bytes: &[u8]) -> bool;
    fn run_callbacks(&mut self);
}

pub struct SteamBackend {
    defs: Value,
    data_dir: PathBuf,
    api: Box<dyn SteamApi>,
    /// The overlay's last change, set by the SDK's callback and taken by update().
    pub overlay: Arc<Mutex<Option<bool>>>,
}

impl SteamBackend {
    pub fn new(defs: Value, data_dir: PathBuf, api: Box<dyn SteamApi>) -> Self {
        SteamBackend {
            defs,
            data_dir,
            api,
            overlay: Arc::new(Mutex::new(None)),
        }
    }

    fn is_int(&self, id: &str) -> bool {
        self.defs["stats"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|s| s["id"] == id && s["type"] == "int")
    }
}

impl Backend for SteamBackend {
    fn name(&self) -> &str {
        "steam"
    }

    fn available(&mut self) -> bool {
        true
    }

    fn remote(&mut self) -> Value {
        let mut unlocked = Vec::new();
        for a in self.defs["achievements"].as_array().cloned().unwrap_or_default() {
            let id = a["id"].as_str().unwrap_or("");
            if self.api.achieved(id) == Some(true) {
                unlocked.push(id.to_string());
            }
        }
        let mut stats = serde_json::Map::new();
        for s in self.defs["stats"].as_array().cloned().unwrap_or_default() {
            let id = s["id"].as_str().unwrap_or("").to_string();
            let v = if s["type"] == "int" {
                self.api.stat_int(&id).map(|v| json!(v))
            } else {
                self.api.stat_float(&id).map(|v| json!(v))
            };
            if let Some(v) = v {
                stats.insert(id, v);
            }
        }
        json!({"unlocked": unlocked, "stats": stats})
    }

    fn send(&mut self, call: &Value) -> bool {
        let s = |n: usize| call.get(n).and_then(Value::as_str).unwrap_or("").to_string();
        let n = |i: usize| call.get(i).and_then(Value::as_f64).unwrap_or(0.0);
        match call[0].as_str().unwrap_or("") {
            "set_achievement" => {
                self.api.set_achievement(&s(1));
            }
            "set_stat" => {
                if self.is_int(&s(1)) {
                    self.api.set_stat_int(&s(1), n(2) as i32);
                } else {
                    self.api.set_stat_float(&s(1), n(2) as f32);
                }
            }
            "store_stats" => return self.api.store_stats(),
            "indicate_progress" => {
                self.api.indicate_progress(&s(1), n(2) as u32, n(3) as u32);
            }
            "reset_all_stats" => {
                self.api.reset_all_stats(call[1].as_bool().unwrap_or(true));
            }
            "set_presence" => {
                self.api.set_rich_presence(&s(1), &s(2));
            }
            "clear_presence" => self.api.clear_rich_presence(),
            "cloud_write" => {
                if let Ok(bytes) = std::fs::read(self.data_dir.join(s(1))) {
                    self.api.file_write(&s(1), &bytes);
                }
            }
            _ => {}
        }
        true
    }

    fn update(&mut self) -> Option<bool> {
        self.api.run_callbacks();
        self.overlay.lock().ok().and_then(|mut o| o.take())
    }
}

/// The store backend for this build: Steam's with the `steam` feature when Steam starts, else None (the null
/// backend). An automated run (dev.py smoke, tests) never asks a store.
pub fn make(defs: &Value, data_dir: &Path, automated: bool) -> Option<Box<dyn Backend>> {
    if automated {
        return None;
    }
    steam_sdk::make(defs, data_dir)
}

#[cfg(not(feature = "steam"))]
mod steam_sdk {
    use super::*;

    pub fn make(_defs: &Value, _data_dir: &Path) -> Option<Box<dyn Backend>> {
        None // built without the `steam` feature: the null backend
    }
}

#[cfg(feature = "steam")]
mod steam_sdk {
    use super::*;

    /// steamworks 0.13 behind SteamApi (verify every call against the crate's docs with the feature on).
    struct Steamworks(steamworks::Client);

    impl SteamApi for Steamworks {
        fn set_achievement(&mut self, id: &str) -> bool {
            self.0.user_stats().achievement(id).set().is_ok()
        }
        fn achieved(&mut self, id: &str) -> Option<bool> {
            self.0.user_stats().achievement(id).get().ok()
        }
        fn set_stat_int(&mut self, id: &str, v: i32) -> bool {
            self.0.user_stats().set_stat_i32(id, v).is_ok()
        }
        fn set_stat_float(&mut self, id: &str, v: f32) -> bool {
            self.0.user_stats().set_stat_f32(id, v).is_ok()
        }
        fn stat_int(&mut self, id: &str) -> Option<i32> {
            self.0.user_stats().get_stat_i32(id).ok()
        }
        fn stat_float(&mut self, id: &str) -> Option<f32> {
            self.0.user_stats().get_stat_f32(id).ok()
        }
        fn store_stats(&mut self) -> bool {
            self.0.user_stats().store_stats().is_ok()
        }
        fn indicate_progress(&mut self, id: &str, current: u32, max: u32) -> bool {
            self.0
                .user_stats()
                .indicate_achievement_progress(id, current, max)
                .is_ok()
        }
        fn reset_all_stats(&mut self, achievements: bool) -> bool {
            self.0.user_stats().reset_all_stats(achievements).is_ok()
        }
        fn set_rich_presence(&mut self, key: &str, value: &str) -> bool {
            self.0.friends().set_rich_presence(key, Some(value))
        }
        fn clear_rich_presence(&mut self) {
            self.0.friends().clear_rich_presence();
        }
        fn file_write(&mut self, name: &str, bytes: &[u8]) -> bool {
            use std::io::Write;
            self.0.remote_storage().file(name).write().write_all(bytes).is_ok()
        }
        fn run_callbacks(&mut self) {
            self.0.run_callbacks();
        }
    }

    pub fn make(defs: &Value, data_dir: &Path) -> Option<Box<dyn Backend>> {
        let client = match steamworks::Client::init() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[WARN] platform: built with Steam, but Steam did not start ({e}): the null backend runs");
                return None;
            }
        };
        let backend = SteamBackend::new(
            defs.clone(),
            data_dir.to_path_buf(),
            Box::new(Steamworks(client.clone())),
        );
        let overlay = backend.overlay.clone();
        // the handle must live as long as the game: leak it on purpose (one per run)
        std::mem::forget(client.register_callback(move |e: steamworks::GameOverlayActivated| {
            if let Ok(mut o) = overlay.lock() {
                *o = Some(e.active);
            }
        }));
        Some(Box::new(backend))
    }
}

// {{FOOTER}}
