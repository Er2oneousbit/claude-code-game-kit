// ---------------------------------------------------------------------------
// SaveStore.hpp
// Purpose : Save games: a versioned envelope, migration of old saves to the current version, a fallback
//           to the backup when the main file is broken, and crash-safe writes that keep the previous good
//           save as <file>.bak. Plain C++, no SDL.
// Usage   : core::SaveStore store(core::path_from_utf8(user_dir + "/save.json"));
//           const core::SaveLoad loaded = store.load();
//           if (loaded.envelope.is_null()) start_new_game();   // loaded.problems says why (log it)
//           else         restore(loaded.envelope["data"]);     // already migrated to kSaveVersion
//           std::string err;  if (!store.save(snapshot(), &err)) LOG_ERROR("save", err);
// Notes   : The file is {"format": "save", "version": N, "data": {...game state...}}. Bump kSaveVersion
//           when the data's shape changes and add one migration step (SaveStore.cpp kMigrations; a
//           static_assert there fails the build until you do), and a test that loads a save of the old
//           version. A save from a NEWER game version is never loaded, and save() refuses to overwrite it
//           (the player may go back to the newer build). Matches tools/golden_vectors.py (save_load,
//           migrations), checked against data/golden/shell.json; the files are tested in a temp folder.
//
// Pseudocode:
//   parse(text): missing | unreadable | not a save | bad version | newer -> problem ; else the envelope
//   save_load(primary, backup): the first of the two that parses, migrated step by step to kSaveVersion
//   save(data):
//     either file holds a newer save -> refuse
//     write <file>.tmp ; if the current <file> is a good save, copy it to <file>.bak (atomically)
//     rename <file>.tmp over <file>
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

// ---- Constants ----
constexpr int kSaveVersion = 3;            // the version this build writes; older saves are migrated up to it
constexpr const char* kSaveFormat = "save";

struct SaveLoad {
    nlohmann::json envelope;            // at kSaveVersion, or null when nothing could be loaded
    std::string source;                 // "primary", "backup" or "none"
    std::vector<std::string> problems;  // "primary: unreadable", "backup: missing", ...
    bool newer = false;                 // a file came from a newer game version (tell the player; never overwrite)
};

// Loads from the two files' texts (std::nullopt = that file does not exist).
SaveLoad save_load(const std::optional<std::string>& primary, const std::optional<std::string>& backup);

// The envelope migrated to kSaveVersion (its version must be 1..kSaveVersion).
nlohmann::json save_migrate(nlohmann::json envelope);

// A current-version envelope around the game's data.
nlohmann::json save_envelope(const nlohmann::json& data);

class SaveStore {
public:
    explicit SaveStore(std::filesystem::path file) : file_(std::move(file)) {}

    SaveLoad load() const;

    // Writes data as the new save (see Pseudocode). False and *error on failure; the old save is then untouched.
    bool save(const nlohmann::json& data, std::string* error = nullptr) const;

    const std::filesystem::path& file() const { return file_; }
    std::filesystem::path backup_file() const;

private:
    std::filesystem::path file_;
};

}  // namespace core
