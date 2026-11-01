// ---------------------------------------------------------------------------
// AtomicFile.hpp
// Purpose : Crash-safe file writes for settings and saves, plus a whole-file reader. Plain C++17
//           (std::filesystem), no SDL.
// Usage   : std::string err;
//           if (!core::write_file_atomic(path, text, &err)) LOG_ERROR("save", "could not save: " << err);
//           if (auto text = core::read_file(path)) { ... *text ... }
// Notes   : A crash at any moment leaves either the old file or the new one, never half a file: the bytes go to
//           <file>.tmp first, are flushed to the disk, and only then renamed over <file> (a replacing rename). After
//           a power cut this also depends on the file system keeping the rename (the folder itself is not flushed),
//           which is why saves also keep a .bak (SaveStore).
//           A stale <file>.tmp from a crash is harmless (nobody reads it) and is replaced by the next write.
//           write_temp() and commit_temp() are the two halves, public so tests can stop in between.
//           Paths are std::filesystem::path: build them with path_from_utf8() from UTF-8 text, so names
//           like "Í" work on Windows. SaveStore.hpp adds the <file>.bak of the previous good save.
//
// Pseudocode:
//   write_temp(f, bytes): open f.tmp, write, fflush, fsync (_commit on Windows), close; any failure -> remove f.tmp
//   commit_temp(f)      : rename f.tmp over f (replaces it in one step on NTFS, ext4, APFS)
//   write_file_atomic   : write_temp, then commit_temp
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <filesystem>
#include <optional>
#include <string>

namespace core {

// ---- Constants ----
constexpr const char* kTempSuffix = ".tmp";    // <file>.tmp while a write is in flight
constexpr const char* kBackupSuffix = ".bak";  // <file>.bak: the previous good save (SaveStore)

// UTF-8 text <-> path, the same in C++17 and C++20 (u8path is deprecated in 20, u8string changes type).
std::filesystem::path path_from_utf8(const std::string& text);
std::string path_to_utf8(const std::filesystem::path& path);

// <file>.tmp and <file>.bak next to target (the suffix is appended: save.json -> save.json.tmp).
std::filesystem::path temp_path_for(const std::filesystem::path& target);
std::filesystem::path backup_path_for(const std::filesystem::path& target);

// The whole file as bytes, or nullopt. A missing file leaves *error empty; a file that exists but cannot be
// read sets it, so callers can tell "never saved" from "the disk said no".
std::optional<std::string> read_file(const std::filesystem::path& path, std::string* error = nullptr);

// Step 1: bytes into <target>.tmp, flushed to the disk. Creates missing parent folders. False on failure
// (the .tmp is removed again and *error says why).
bool write_temp(const std::filesystem::path& target, const std::string& bytes, std::string* error = nullptr);

// Step 2: <target>.tmp replaces target. False on failure (target is unchanged).
bool commit_temp(const std::filesystem::path& target, std::string* error = nullptr);

// Both steps: the crash-safe replacement for "open, write, close".
bool write_file_atomic(const std::filesystem::path& target, const std::string& bytes, std::string* error = nullptr);

}  // namespace core
