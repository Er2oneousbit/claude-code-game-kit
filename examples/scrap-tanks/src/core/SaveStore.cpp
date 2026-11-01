// ---------------------------------------------------------------------------
// SaveStore.cpp
// Purpose : Implementation of the save envelope, migrations and the crash-safe store (see SaveStore.hpp).
// Usage   : compiled into the `core` library; call through SaveStore.hpp.
// Notes   : kMigrations is the example chain from the kit's reference (v2 renamed hp to health, v3 added
//           the difficulty the game was started on). Replace it with your game's own steps; keep one step
//           per version and never edit a step that has shipped (old saves still need it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/SaveStore.hpp"

#include <cmath>
#include <iterator>
#include <utility>

#include "core/AtomicFile.hpp"

namespace core {

using nlohmann::json;

namespace {

// ---- Tunables ----
constexpr int kSaveIndent = 1;  // small but still readable when a bug report attaches a save

// ---- Migrations: kMigrations[v - 1] turns a version v save's data into version v + 1 ----
void migrate_1_to_2(json& data) {
    if (data.contains("hp")) {  // v2 renamed hp to health
        data["health"] = data["hp"];
        data.erase("hp");
    }
}

void migrate_2_to_3(json& data) {
    if (!data.contains("difficulty")) {  // v3 added the difficulty the game was started on
        data["difficulty"] = "normal";
    }
}

using Migration = void (*)(json& data);
constexpr Migration kMigrations[] = {migrate_1_to_2, migrate_2_to_3};
static_assert(static_cast<int>(std::size(kMigrations)) == kSaveVersion - 1,
              "kSaveVersion changed: add one migration step per version to kMigrations");

struct Parsed {
    json envelope;        // null on a problem
    std::string problem;  // "" when envelope is good
};

// One file's text as an envelope at its own version, or the reason it cannot be loaded.
Parsed parse_save(const std::optional<std::string>& text) {
    if (!text) {
        return {nullptr, "missing"};
    }
    json env = json::parse(*text, nullptr, /*allow_exceptions*/ false);
    if (env.is_discarded()) {
        return {nullptr, "unreadable"};
    }
    if (!env.is_object() || !env.contains("format") || env["format"] != kSaveFormat || !env.contains("data") ||
        !env["data"].is_object()) {
        return {nullptr, "not a save"};
    }
    const auto v = env.find("version");
    if (v == env.end() || !v->is_number()) {  // is_number() is false for true/false
        return {nullptr, "bad version"};
    }
    const double version = v->get<double>();
    if (!std::isfinite(version) || version != std::floor(version) || version < 1.0) {
        return {nullptr, "bad version"};
    }
    if (version > kSaveVersion) {
        return {nullptr, "newer"};
    }
    env["version"] = static_cast<int>(version);  // 2.0 in the file reads as version 2
    return {std::move(env), ""};
}

}  // namespace

json save_migrate(json envelope) {
    int version = envelope["version"].get<int>();
    while (version >= 1 && version < kSaveVersion) {
        kMigrations[version - 1](envelope["data"]);
        ++version;
        envelope["version"] = version;
    }
    return envelope;
}

json save_envelope(const json& data) {
    json env = json::object();
    env["format"] = kSaveFormat;
    env["version"] = kSaveVersion;
    env["data"] = data;
    return env;
}

SaveLoad save_load(const std::optional<std::string>& primary, const std::optional<std::string>& backup) {
    SaveLoad r;
    const std::pair<const char*, const std::optional<std::string>*> files[] = {{"primary", &primary},
                                                                               {"backup", &backup}};
    for (const auto& [source, text] : files) {
        Parsed p = parse_save(*text);
        if (p.problem.empty()) {
            r.envelope = save_migrate(std::move(p.envelope));
            r.source = source;
            return r;
        }
        r.newer = r.newer || p.problem == "newer";
        r.problems.push_back(std::string(source) + ": " + p.problem);
    }
    r.envelope = nullptr;
    r.source = "none";
    return r;
}

std::filesystem::path SaveStore::backup_file() const {
    return backup_path_for(file_);
}

SaveLoad SaveStore::load() const {
    return save_load(read_file(file_), read_file(backup_file()));
}

bool SaveStore::save(const json& data, std::string* error) const {
    const std::optional<std::string> current = read_file(file_);
    const Parsed now = parse_save(current);
    if (now.problem == "newer" || parse_save(read_file(backup_file())).problem == "newer") {
        if (error) {
            *error = "a newer version of the game wrote this save; not overwriting it";
        }
        return false;
    }
    const std::string text = save_envelope(data).dump(kSaveIndent, ' ', false, json::error_handler_t::replace) + "\n";
    if (!write_temp(file_, text, error)) {
        return false;  // nothing on disk changed
    }
    // Keep the previous save only when it is a good one: a corrupt file must not replace a good backup
    if (now.problem.empty() && !write_file_atomic(backup_file(), *current, error)) {
        std::error_code ec;
        std::filesystem::remove(temp_path_for(file_), ec);
        return false;
    }
    return commit_temp(file_, error);
}

}  // namespace core
