// ---------------------------------------------------------------------------
// logic/save_store.rs
// Purpose : Save games: a versioned envelope {"format": "save", "version": N, "data": {...}}, migrations that
//           bring an old save up to SAVE_VERSION one step at a time, a backup of the previous good save, and a
//           load that falls back to the backup when the main file is damaged.
// Usage   : let loaded = save_store::load_from(&path);          // loaded.envelope: Option<Value>, .source, .problems
//           if let Some(env) = &loaded.envelope { let data = &env["data"]; ... }
//           save_store::write_to(&path, &json!({"health": 5, "level": 2}))?;
// Notes   : Bump SAVE_VERSION when the data shape changes and add a migration from the old version (never edit
//           an old one: players have saves made with it). A save from a NEWER version is never loaded and never
//           overwritten (the player went back to an older build; their progress stays safe): while the slot or
//           its .bak holds one, write_to refuses. The two example
//           migrations (v2 renamed hp to health, v3 added difficulty) are the shape the golden vectors test:
//           replace them with your game's own once it has saves. Tested in tests/golden.rs against
//           data/golden/shell.json (tools/golden_vectors.py is the reference).
//
// Pseudocode:
//   load(primary, backup): for each of primary, backup: parse (missing | unreadable | not a save | bad version |
//   newer -> a problem, try the next) -> the first good one, migrated step by step to SAVE_VERSION
//   write_to(path, data): refuse when path or its .bak holds a newer save -> path is a good save? copy it to <path>.bak
//   -> atomic write of the new envelope
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::Path;

use serde_json::{Map, Value, json};

use super::atomic_file;

// ---- Constants -----------------------------------------------------------------
/// The save format this build writes. Bump it with a new migration.
pub const SAVE_VERSION: i64 = 3;
pub const FORMAT: &str = "save";

/// One migration step: the data of version N in, version N + 1 out.
type Migration = fn(&mut Map<String, Value>);

/// MIGRATIONS[i] takes a save from version i + 1 to i + 2.
const MIGRATIONS: [Migration; (SAVE_VERSION - 1) as usize] = [migrate_1_to_2, migrate_2_to_3];

fn migrate_1_to_2(data: &mut Map<String, Value>) {
    // v2 renamed hp to health
    if let Some(hp) = data.remove("hp") {
        data.insert("health".into(), hp);
    }
}

fn migrate_2_to_3(data: &mut Map<String, Value>) {
    // v3 added the difficulty the game was started on
    data.entry("difficulty").or_insert(json!("normal"));
}

/// Where a loaded save came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    Primary,
    Backup,
    /// Neither file held a usable save: start a new game.
    NoSave,
}

impl Source {
    pub fn as_str(self) -> &'static str {
        match self {
            Source::Primary => "primary",
            Source::Backup => "backup",
            Source::NoSave => "none",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Loaded {
    /// The envelope at SAVE_VERSION, or None.
    pub envelope: Option<Value>,
    pub source: Source,
    /// "primary: unreadable", "backup: missing", ... one per file that was tried and failed.
    pub problems: Vec<String>,
}

/// The envelope with a whole version, or why the text is not a loadable save.
pub fn parse(text: Option<&str>) -> Result<Map<String, Value>, &'static str> {
    let text = text.ok_or("missing")?;
    let value: Value = serde_json::from_str(text).map_err(|_| "unreadable")?;
    let Value::Object(mut env) = value else {
        return Err("not a save");
    };
    if env.get("format").and_then(Value::as_str) != Some(FORMAT) || !env.get("data").is_some_and(Value::is_object) {
        return Err("not a save");
    }
    let version = match env.get("version").and_then(Value::as_f64) {
        Some(v) if v.fract() == 0.0 && v >= 1.0 => v,
        _ => return Err("bad version"),
    };
    if version > SAVE_VERSION as f64 {
        return Err("newer");
    }
    env.insert("version".into(), json!(version as i64));
    Ok(env)
}

/// Runs the migrations from the envelope's version up to SAVE_VERSION.
pub fn migrate(mut env: Map<String, Value>) -> Map<String, Value> {
    let mut version = env.get("version").and_then(Value::as_i64).unwrap_or(SAVE_VERSION);
    while (1..SAVE_VERSION).contains(&version) {
        if let Some(Value::Object(data)) = env.get_mut("data") {
            MIGRATIONS[(version - 1) as usize](data);
        }
        version += 1;
        env.insert("version".into(), json!(version));
    }
    env
}

/// The first good save of primary and backup (file texts, None = no file), migrated to SAVE_VERSION.
pub fn load(primary: Option<&str>, backup: Option<&str>) -> Loaded {
    let mut problems = Vec::new();
    for (source, text) in [(Source::Primary, primary), (Source::Backup, backup)] {
        match parse(text) {
            Ok(env) => {
                return Loaded {
                    envelope: Some(Value::Object(migrate(env))),
                    source,
                    problems,
                };
            }
            Err(problem) => problems.push(format!("{}: {problem}", source.as_str())),
        }
    }
    Loaded {
        envelope: None,
        source: Source::NoSave,
        problems,
    }
}

/// The file's text, None when it does not exist. A file that cannot be read (no permission, not UTF-8: torn
/// inside a multibyte character) gives empty text, which parses as unreadable, so load and save agree on it.
fn read_save_text(path: &Path) -> Option<String> {
    atomic_file::read_text(path).unwrap_or_else(|_| Some(String::new()))
}

/// Loads `path`, falling back to `<path>.bak`. A file that cannot be read counts as unreadable.
pub fn load_from(path: &Path) -> Loaded {
    let (primary, backup) = (read_save_text(path), read_save_text(&atomic_file::bak_path(path)));
    load(primary.as_deref(), backup.as_deref())
}

/// Saves `data` (a JSON object) at SAVE_VERSION. The previous good save becomes `<path>.bak`; while `path` or
/// `<path>.bak` holds a newer game's save, nothing is written (Err).
pub fn write_to(path: &Path, data: &Value) -> Result<(), String> {
    if !data.is_object() {
        return Err("save data must be a JSON object".into());
    }
    let current = read_save_text(path); // unreadable here too, so a damaged primary never blocks saving
    let backup = atomic_file::bak_path(path);
    if parse(read_save_text(&backup).as_deref()) == Err("newer") {
        // the next save would copy this build's file over it
        return Err(format!(
            "{} holds a save made by a newer version of the game: not saving over this slot",
            backup.display()
        ));
    }
    match parse(current.as_deref()) {
        Err("newer") => {
            return Err(format!(
                "{} was made by a newer version of the game: not overwriting it",
                path.display()
            ));
        }
        Ok(_) => {
            atomic_file::backup(path).map_err(|e| format!("cannot back up {}: {e}", path.display()))?;
        }
        Err(_) => {} // nothing there, or damaged: keep the existing .bak, which is the last good save
    }
    let env = json!({"format": FORMAT, "version": SAVE_VERSION, "data": data});
    let text = serde_json::to_string_pretty(&env).map_err(|e| e.to_string())?;
    atomic_file::write(path, text.as_bytes()).map_err(|e| format!("cannot write {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic::atomic_file::{TempDir, bak_path, write_tmp};

    #[test]
    fn writing_keeps_the_previous_good_save_as_backup() {
        let dir = TempDir::new("save-backup");
        let path = dir.0.join("slot1.json");
        write_to(&path, &json!({"health": 3})).unwrap();
        write_to(&path, &json!({"health": 4})).unwrap();
        let loaded = load_from(&path);
        assert_eq!(loaded.source, Source::Primary);
        assert_eq!(loaded.envelope.unwrap()["data"]["health"], 4);
        let backup = load(atomic_file::read_text(&bak_path(&path)).unwrap().as_deref(), None);
        assert_eq!(backup.envelope.unwrap()["data"]["health"], 3);
    }

    #[test]
    fn a_damaged_save_loads_the_backup_and_is_not_backed_up() {
        let dir = TempDir::new("save-damaged");
        let path = dir.0.join("slot1.json");
        write_to(&path, &json!({"health": 3})).unwrap();
        write_to(&path, &json!({"health": 4})).unwrap();
        std::fs::write(&path, "{\"format\": \"save\", \"vers").unwrap(); // a torn file from outside the game
        let loaded = load_from(&path);
        assert_eq!((loaded.source, loaded.problems.len()), (Source::Backup, 1));
        write_to(&path, &json!({"health": 5})).unwrap(); // the good backup is kept, not replaced by the torn file
        let backup = load(atomic_file::read_text(&bak_path(&path)).unwrap().as_deref(), None);
        assert_eq!(backup.envelope.unwrap()["data"]["health"], 3);
    }

    #[test]
    fn a_primary_that_is_not_utf8_counts_as_unreadable_when_saving() {
        let dir = TempDir::new("save-not-utf8");
        let path = dir.0.join("slot1.json");
        write_to(&path, &json!({"health": 3})).unwrap();
        write_to(&path, &json!({"health": 4})).unwrap();
        // torn inside a multibyte character: read_to_string gives InvalidData, not text
        std::fs::write(
            &path,
            b"{\"format\": \"save\", \"version\": 3, \"data\": {\"name\": \"\xC3",
        )
        .unwrap();
        assert_eq!(load_from(&path).source, Source::Backup);
        write_to(&path, &json!({"health": 5})).unwrap(); // saving must not be blocked for good
        assert_eq!(load_from(&path).envelope.unwrap()["data"]["health"], 5);
        let backup = load(atomic_file::read_text(&bak_path(&path)).unwrap().as_deref(), None);
        assert_eq!(backup.envelope.unwrap()["data"]["health"], 3);
    }

    #[test]
    fn a_crash_between_write_and_rename_keeps_the_old_save() {
        let dir = TempDir::new("save-crash");
        let path = dir.0.join("slot1.json");
        write_to(&path, &json!({"health": 3})).unwrap();
        write_tmp(
            &path,
            b"{\"format\": \"save\", \"version\": 3, \"data\": {\"health\": 9}}",
        )
        .unwrap(); // no rename
        let loaded = load_from(&path);
        assert_eq!(loaded.source, Source::Primary);
        assert_eq!(loaded.envelope.unwrap()["data"]["health"], 3);
    }

    #[test]
    fn a_newer_save_is_never_overwritten() {
        let dir = TempDir::new("save-newer");
        let path = dir.0.join("slot1.json");
        let newer = format!(
            "{{\"format\": \"save\", \"version\": {}, \"data\": {{}}}}",
            SAVE_VERSION + 1
        );
        std::fs::write(&path, &newer).unwrap();
        assert!(write_to(&path, &json!({"health": 1})).is_err());
        assert_eq!(atomic_file::read_text(&path).unwrap(), Some(newer));
    }

    #[test]
    fn a_newer_backup_blocks_saving_too() {
        // a newer build saved twice, then the primary was deleted: the save after this one would copy this
        // build's file over the newer .bak, so every port refuses the slot
        let dir = TempDir::new("save-newer-bak");
        let path = dir.0.join("slot1.json");
        let newer = format!(
            "{{\"format\": \"save\", \"version\": {}, \"data\": {{}}}}",
            SAVE_VERSION + 1
        );
        std::fs::write(bak_path(&path), &newer).unwrap();
        assert!(write_to(&path, &json!({"health": 1})).is_err());
        assert!(!path.exists());
        assert_eq!(atomic_file::read_text(&bak_path(&path)).unwrap(), Some(newer));
    }
}
