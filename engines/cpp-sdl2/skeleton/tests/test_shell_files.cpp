// ---------------------------------------------------------------------------
// test_shell_files.cpp
// Purpose : Tests the crash-safe file layer on the real filesystem: AtomicFile, the SaveStore backup and
//           newer-save rules, and the settings file round trip.
// Usage   : python tools/dev.py test
// Notes   : Each test works in its own temp folder whose name contains "Í" (narrow-path APIs on Windows
//           mangle it), removed again at the end. A "crash" is simulated by stopping
//           after write_temp(), before commit_temp(): exactly the window an atomic write must survive.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <chrono>
#include <filesystem>
#include <string>
#include <system_error>

#include <nlohmann/json.hpp>

#include "core/AtomicFile.hpp"
#include "core/SaveStore.hpp"
#include "core/Settings.hpp"

namespace fs = std::filesystem;
using nlohmann::json;

namespace {

// A fresh, uniquely named folder under the system temp dir, deleted with everything in it at scope exit.
struct TempDir {
    fs::path path;
    TempDir() {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        path = fs::temp_directory_path() / core::path_from_utf8("gamekit-shell-\xC3\x8D-" + std::to_string(stamp));
        fs::create_directories(path);
    }
    ~TempDir() {
        std::error_code ec;
        fs::remove_all(path, ec);
    }
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
};

std::string read(const fs::path& p) {
    return core::read_file(p).value_or("<missing>");
}

}  // namespace

TEST_CASE("atomic write replaces the file and leaves no temp file behind") {
    TempDir dir;
    const fs::path file = dir.path / "data.txt";
    std::string error;
    REQUIRE(core::write_file_atomic(file, "one", &error));
    REQUIRE(core::write_file_atomic(file, "two", &error));  // over an existing file
    CHECK(read(file) == "two");
    CHECK_FALSE(fs::exists(core::temp_path_for(file)));
}

TEST_CASE("a crash between write and rename leaves the old file intact") {
    TempDir dir;
    const fs::path file = dir.path / "data.txt";
    REQUIRE(core::write_file_atomic(file, "old", nullptr));
    REQUIRE(core::write_temp(file, "new but never committed", nullptr));  // the process dies here
    CHECK(read(file) == "old");
    REQUIRE(core::write_file_atomic(file, "next", nullptr));  // the stale .tmp is simply replaced
    CHECK(read(file) == "next");
}

TEST_CASE("read_file tells a missing file from a present one") {
    TempDir dir;
    std::string error = "x";
    CHECK_FALSE(core::read_file(dir.path / "nope.json", &error).has_value());
    CHECK(error.empty());  // missing is not an error
    REQUIRE(core::write_file_atomic(dir.path / "empty.json", "", nullptr));
    CHECK(core::read_file(dir.path / "empty.json") == std::string());
}

TEST_CASE("atomic write creates missing parent folders") {
    TempDir dir;
    const fs::path file = dir.path / "saves" / "slot1.json";
    REQUIRE(core::write_file_atomic(file, "{}", nullptr));
    CHECK(read(file) == "{}");
}

TEST_CASE("save keeps the previous good save as .bak") {
    TempDir dir;
    const core::SaveStore store(dir.path / "save.json");
    REQUIRE(store.save({{"level", 1}}));
    CHECK_FALSE(fs::exists(store.backup_file()));  // nothing to keep yet
    REQUIRE(store.save({{"level", 2}}));
    const core::SaveLoad loaded = store.load();
    CHECK(loaded.source == "primary");
    CHECK(loaded.envelope["version"] == core::kSaveVersion);
    CHECK(loaded.envelope["data"]["level"] == 2);
    const core::SaveLoad backup = core::save_load(core::read_file(store.backup_file()), std::nullopt);
    CHECK(backup.envelope["data"]["level"] == 1);
}

TEST_CASE("a corrupt save falls back to the backup and never replaces it") {
    TempDir dir;
    const core::SaveStore store(dir.path / "save.json");
    REQUIRE(store.save({{"level", 1}}));
    REQUIRE(store.save({{"level", 2}}));                                  // .bak = level 1
    REQUIRE(core::write_file_atomic(store.file(), "{\"format\": \"sa", nullptr));  // torn by some other tool
    core::SaveLoad loaded = store.load();
    CHECK(loaded.source == "backup");
    CHECK(loaded.problems.size() == 1);
    CHECK(loaded.envelope["data"]["level"] == 1);
    REQUIRE(store.save({{"level", 3}}));  // the corrupt file is not good, so .bak stays level 1
    loaded = core::save_load(core::read_file(store.backup_file()), std::nullopt);
    CHECK(loaded.envelope["data"]["level"] == 1);
    CHECK(store.load().envelope["data"]["level"] == 3);
}

TEST_CASE("a crash during save leaves the last save loadable") {
    TempDir dir;
    const core::SaveStore store(dir.path / "save.json");
    REQUIRE(store.save({{"level", 4}}));
    REQUIRE(core::write_temp(store.file(), core::save_envelope({{"level", 5}}).dump(), nullptr));  // dies here
    const core::SaveLoad loaded = store.load();
    CHECK(loaded.source == "primary");
    CHECK(loaded.envelope["data"]["level"] == 4);
}

TEST_CASE("a save from a newer game version is neither loaded nor overwritten") {
    TempDir dir;
    const core::SaveStore store(dir.path / "save.json");
    const std::string newer = json{{"format", "save"}, {"version", core::kSaveVersion + 1}, {"data", json::object()}}.dump();
    REQUIRE(core::write_file_atomic(store.file(), newer, nullptr));
    const core::SaveLoad loaded = store.load();
    CHECK(loaded.envelope.is_null());
    CHECK(loaded.newer);
    std::string error;
    CHECK_FALSE(store.save({{"level", 1}}, &error));
    CHECK_FALSE(error.empty());
    CHECK(read(store.file()) == newer);
}

TEST_CASE("a newer save in the backup blocks saving too") {
    // a newer build saved twice, then the primary was deleted: every port refuses the slot, so a later save
    // never copies this build's file over the newer .bak
    TempDir dir;
    const core::SaveStore store(dir.path / "save.json");
    const std::string newer = json{{"format", "save"}, {"version", core::kSaveVersion + 1}, {"data", json::object()}}.dump();
    REQUIRE(core::write_file_atomic(store.backup_file(), newer, nullptr));
    std::string error;
    CHECK_FALSE(store.save({{"level", 1}}, &error));
    CHECK_FALSE(std::filesystem::exists(store.file()));
    CHECK(read(store.backup_file()) == newer);
}

TEST_CASE("an old save on disk is migrated on load") {
    TempDir dir;
    const core::SaveStore store(dir.path / "save.json");
    REQUIRE(core::write_file_atomic(store.file(), R"({"format": "save", "version": 1, "data": {"hp": 3}})", nullptr));
    const core::SaveLoad loaded = store.load();
    CHECK(loaded.envelope["version"] == core::kSaveVersion);
    CHECK(loaded.envelope["data"]["health"] == 3);
    CHECK_FALSE(loaded.envelope["data"].contains("hp"));
}

TEST_CASE("settings survive a save and load, unknown keys included") {
    TempDir dir;
    const fs::path file = dir.path / "settings.json";
    CHECK(core::settings_load_file(file).problems.empty());  // no file yet: defaults, no problems
    json s = core::default_settings();
    s["access"]["text_scale"] = 1.5;
    s["language"] = "fr-CA";
    s["mod_options"] = {{"turbo", true}};  // a key only a newer build knows
    std::string error;
    REQUIRE(core::settings_save_file(file, s, &error));
    const core::SettingsLoad loaded = core::settings_load_file(file);
    CHECK(loaded.problems.empty());
    CHECK(loaded.settings == s);
}

TEST_CASE("a broken settings file loads as defaults with one problem") {
    TempDir dir;
    const fs::path file = dir.path / "settings.json";
    REQUIRE(core::write_file_atomic(file, "{\"audio\": ", nullptr));
    const core::SettingsLoad loaded = core::settings_load_file(file);
    CHECK(loaded.settings == core::default_settings());
    CHECK(loaded.problems.size() == 1);
}

// {{FOOTER}}
