// ---------------------------------------------------------------------------
// logic/atomic_file.rs
// Purpose : Crash-safe file writes for settings and saves: after a crash the file on disk is either the old version
//           or the new one, never half of each (after a power cut this also depends on the file system keeping the
//           rename; saves keep a .bak for that case).
// Usage   : atomic_file::write(&path, text.as_bytes())?;      // <file>.tmp, flush to disk, rename over <file>
//           atomic_file::backup(&path)?;                       // copy <file> to <file>.bak (also atomically)
//           let text: Option<String> = atomic_file::read_text(&path)?;   // None when the file does not exist
// Notes   : std::fs::rename replaces an existing target in one call on Windows, Linux and macOS (the .tmp sits
//           in the same folder, so on the same drive). A crash before the rename leaves the old file and a stray
//           <file>.tmp, which the next write overwrites. The file data is synced before the rename; the folder
//           entry is not (std has no portable way on Windows).
//
// Pseudocode:
//   write(path, bytes): make the folder -> create <path>.tmp -> write all -> sync to disk -> rename over path
//   backup(path): if path exists, write(<path>.bak, its bytes)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

// ---- Constants -----------------------------------------------------------------
pub const TMP_SUFFIX: &str = ".tmp";
pub const BAK_SUFFIX: &str = ".bak";

/// `<path><suffix>` in the same folder (the rename must stay on one drive).
pub fn with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(suffix);
    PathBuf::from(name)
}

pub fn tmp_path(path: &Path) -> PathBuf {
    with_suffix(path, TMP_SUFFIX)
}

pub fn bak_path(path: &Path) -> PathBuf {
    with_suffix(path, BAK_SUFFIX)
}

/// The file's text, or None when it does not exist. Other errors (no permission, not UTF-8) are errors.
pub fn read_text(path: &Path) -> io::Result<Option<String>> {
    match fs::read_to_string(path) {
        Ok(text) => Ok(Some(text)),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e),
    }
}

/// Step 1 of write: the new bytes in `<path>.tmp`, synced to disk. Public so tests can simulate a crash here.
pub fn write_tmp(path: &Path, bytes: &[u8]) -> io::Result<PathBuf> {
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        fs::create_dir_all(dir)?;
    }
    let tmp = tmp_path(path);
    let mut file = fs::File::create(&tmp)?;
    file.write_all(bytes)?;
    file.sync_all()?; // the data is on disk before the rename makes it the real file
    Ok(tmp)
}

/// Step 2 of write: `<path>.tmp` replaces `<path>` in one rename.
pub fn commit(path: &Path) -> io::Result<()> {
    fs::rename(tmp_path(path), path)
}

/// Replaces the file's contents atomically.
pub fn write(path: &Path, bytes: &[u8]) -> io::Result<()> {
    write_tmp(path, bytes)?;
    commit(path)
}

/// Copies `<path>` to `<path>.bak` (atomically). Returns false when there is no file to back up.
pub fn backup(path: &Path) -> io::Result<bool> {
    match fs::read(path) {
        Ok(bytes) => write(&bak_path(path), &bytes).map(|_| true),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e),
    }
}

/// A fresh folder under the system temp dir for tests that touch the real filesystem; deleted on drop.
#[cfg(test)]
pub(crate) struct TempDir(pub PathBuf);

#[cfg(test)]
impl TempDir {
    pub fn new(tag: &str) -> Self {
        use std::sync::atomic::{AtomicU32, Ordering};
        static COUNT: AtomicU32 = AtomicU32::new(0);
        let n = COUNT.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!("{}-{tag}-{}-{n}", env!("CARGO_CRATE_NAME"), std::process::id()));
        let _ = fs::remove_dir_all(&dir); // a leftover from a killed run
        fs::create_dir_all(&dir).expect("create a temp folder");
        TempDir(dir)
    }
}

#[cfg(test)]
impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_replaces_the_file_and_leaves_no_tmp() {
        let dir = TempDir::new("atomic-write");
        let path = dir.0.join("sub").join("settings.json");
        write(&path, b"one").unwrap();
        write(&path, b"two").unwrap();
        assert_eq!(read_text(&path).unwrap().as_deref(), Some("two"));
        assert!(!tmp_path(&path).exists());
    }

    #[test]
    fn a_crash_between_write_and_rename_leaves_the_old_file_intact() {
        let dir = TempDir::new("atomic-crash");
        let path = dir.0.join("save.json");
        write(&path, b"old and good").unwrap();
        write_tmp(&path, b"new, never renamed").unwrap(); // the game dies here: no commit
        assert_eq!(read_text(&path).unwrap().as_deref(), Some("old and good"));
        write(&path, b"next save").unwrap(); // the stray .tmp does not block the next write
        assert_eq!(read_text(&path).unwrap().as_deref(), Some("next save"));
        assert!(!tmp_path(&path).exists());
    }

    #[test]
    fn backup_copies_the_current_file_and_skips_a_missing_one() {
        let dir = TempDir::new("atomic-backup");
        let path = dir.0.join("save.json");
        assert!(!backup(&path).unwrap());
        write(&path, b"first").unwrap();
        assert!(backup(&path).unwrap());
        write(&path, b"second").unwrap();
        assert_eq!(read_text(&bak_path(&path)).unwrap().as_deref(), Some("first"));
        assert_eq!(read_text(&path).unwrap().as_deref(), Some("second"));
    }

    #[test]
    fn a_missing_file_reads_as_none() {
        let dir = TempDir::new("atomic-missing");
        assert_eq!(read_text(&dir.0.join("nope.json")).unwrap(), None);
    }
}
