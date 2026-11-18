// ---------------------------------------------------------------------------
// Platform.hpp
// Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
//           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null backend
//           (it records every call); the Steamworks adapter (src/core/PlatformSteam.cpp, built only with
//           -DGAMEKIT_STEAM=ON) replaces it in a store build. Plain C++, no SDL. Checked against
//           data/golden/platform.json (every case).
// Usage   : core::PlatformService& p = shell.platform();
//           p.unlock("first_win");  p.add_stat("enemies_defeated", 1);  p.flush();   // flush at checkpoints
//           p.set_presence("status", "In the crypt");  p.saved("save_1.json");     // after an atomic save
//           if (p.overlay(active, screen) == "pause") open_pause_menu();
//           pure parts: achievements_load(text), cloud_partition(path), overlay_action(active, screen),
//           core::Platform rules(defs, &backend, online, cloud), core::NullBackend, platform_state_load(defs, text)
// Notes   : Calls are JSON arrays (["set_stat", "coins", 7]) so tests compare them with the vectors as they are.
//           Stat values enter as JSON (set_stat(id, json)): a string, a boolean or a fraction for an int stat is
//           refused by the rules, never by a cast. With no data/achievements.json every call is "unknown" and
//           nothing is written, so a game without achievements runs exactly as before. The state file
//           (<user-data>/platform_state.json) is a cache, written atomically only when it changed.
//
// Pseudocode:
//   rules op -> update local state -> online: send calls to the backend one at a time, in order
//   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
//          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
//   service: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
//          connect(backend.remote()) ; after every op: write the state file when it changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): store_failed and take_store_failure: a store that failed
//           after it was accepted (Steam's UserStatsStored) goes back on the queue
// ---------------------------------------------------------------------------
#pragma once

#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

// ---- Constants (the same in every engine: data/golden/platform.json "names and limits") ----
constexpr const char* kPlatformFormat = "platform_state";
constexpr int kPlatformStateVersion = 1;
constexpr const char* kPlatformStateFile = "platform_state.json";
constexpr const char* kAchievementsFile = "data/achievements.json";
constexpr std::size_t kPlatformIdMax = 64;
constexpr std::size_t kPresenceMaxKeys = 30;          // Steam's rich presence limits (verify)
constexpr std::size_t kPresenceMaxValueBytes = 255;
constexpr const char* kCloudMode = "auto";            // "auto" (Steam Auto-Cloud, preferred) or "api"
const std::vector<std::string>& platform_stat_types();          // int, float
const std::vector<std::string>& platform_cloud_modes();         // auto, api
const std::vector<std::string>& cloud_local_names();
const std::vector<std::string>& cloud_local_suffixes();
const std::vector<std::string>& cloud_local_dirs();
const std::vector<std::string>& overlay_pause_screens();

// An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first.
bool platform_id_ok(const nlohmann::json& v);

struct AchievementsLoad {
    nlohmann::json defs;   // {"version", "stats": [...], "achievements": [...]} as the vectors write it
    int problems = 0;
};
// data/achievements.json text (nullopt or "" = no file).
AchievementsLoad achievements_load(const std::optional<std::string>& text);

// Which user-data file syncs: "cloud" or "local" (ASCII-only folding, never a locale's lowercase).
std::string cloud_partition(const std::string& path);

// The store overlay opened (active) or closed over `screen`: "pause" opens the pause menu; closing never resumes.
std::string overlay_action(bool active, const std::string& screen);

// The backend interface (PLATFORM.md section 4). send returns false only for a store_stats the store refused.
class PlatformBackend {
public:
    virtual ~PlatformBackend() = default;
    virtual std::string name() const = 0;
    virtual bool available() = 0;
    virtual nlohmann::json remote() = 0;               // {"unlocked": [...], "stats": {...}}
    virtual bool send(const nlohmann::json& call) = 0;
    virtual void update() {}                            // each frame: run the SDK's callbacks
    // A store that failed after send(["store_stats"]) returned true (Steam's UserStatsStored): its set_stat and
    // set_achievement calls, oldest first; nullopt when none.
    virtual std::optional<nlohmann::json> take_store_failure() { return std::nullopt; }
    std::function<void(bool)> on_overlay;               // the adapter calls it when the store overlay opens/closes
};

// The backend every game runs by default: records every call and keeps what a store would hold.
class NullBackend : public PlatformBackend {
public:
    std::string name() const override { return "null"; }
    bool available() override { return true; }
    nlohmann::json remote() override;
    bool send(const nlohmann::json& call) override;
    nlohmann::json presence_list() const;               // [[key, value], ...] sorted

    nlohmann::json calls = nlohmann::json::array();
    nlohmann::json unlocked = nlohmann::json::array();
    nlohmann::json stats = nlohmann::json::object();
    std::map<std::string, std::string> presence;
    nlohmann::json cloud = nlohmann::json::array();
    int fail_stores = 0;                                // test hook: the next N store_stats fail

private:
    std::vector<std::string> staged_unlocks_;
    nlohmann::json staged_stats_ = nlohmann::json::object();
};

struct PlatformOut {
    nlohmann::json out;     // the status word (a string), or null for a test hook step
    nlohmann::json calls;   // what was sent to the backend during the operation, in order
};

// The rules (PLATFORM.md section 3).
class Platform {
public:
    Platform(nlohmann::json defs, PlatformBackend* backend, bool online = false, std::string cloud = "auto");

    PlatformOut unlock(const std::string& id);
    PlatformOut set_stat(const std::string& id, const nlohmann::json& v);
    PlatformOut add_stat(const std::string& id, const nlohmann::json& d);
    PlatformOut flush();
    PlatformOut set_presence(const nlohmann::json& key, const nlohmann::json& value);
    PlatformOut clear_presence();
    PlatformOut saved(const std::string& path);
    PlatformOut connect(const nlohmann::json& remote);
    PlatformOut disconnect();
    PlatformOut reset_all();
    // A store the backend accepted failed later: the same as a refused store_stats. The batch's stats and unlocks
    // are pending again and the layer is offline until connect().
    PlatformOut store_failed(const nlohmann::json& batch);

    nlohmann::json state() const;                       // what the state file holds
    void restore(const nlohmann::json& state);          // takes over platform_state_load's state
    nlohmann::json presence_list() const;               // [[key, value], ...] sorted
    bool online() const { return online_; }
    void set_cloud(const std::string& mode) { cloud_ = mode; }
    const nlohmann::json& defs() const { return defs_; }
    const std::vector<std::string>& unlocked() const { return unlocked_; }

    // used by platform_state_load
    bool has_stat(const std::string& id) const { return stat_index_.count(id) > 0; }
    bool has_achievement(const std::string& id) const { return ach_index_.count(id) > 0; }

private:
    friend struct PlatformStateBuilder;
    void reset_local();
    bool send(const nlohmann::json& call);
    PlatformOut done(const char* out);
    void unlock_local(const std::string& id);
    bool check(const std::string& sid, double old, double now, bool notify);
    std::string flush_inner();
    const nlohmann::json& sdef(const std::string& id) const { return defs_["stats"][stat_index_.at(id)]; }

    nlohmann::json defs_;
    PlatformBackend* backend_;
    bool online_;
    std::string cloud_;
    std::map<std::string, std::size_t> stat_index_;
    std::map<std::string, std::size_t> ach_index_;
    std::vector<std::string> unlocked_;
    std::map<std::string, nlohmann::json> stats_;
    std::vector<std::string> pending_stats_;
    std::vector<std::string> pending_unlocks_;
    std::vector<std::string> pending_cloud_;
    std::map<std::string, std::string> presence_;
    nlohmann::json sent_ = nlohmann::json::array();
};

struct PlatformStateLoad {
    nlohmann::json state;
    int problems = 0;
};
// platform_state.json text (nullopt or "" = no file).
PlatformStateLoad platform_state_load(const nlohmann::json& defs, const std::optional<std::string>& text);

// The rules, the backend and the cached state file: what the shell owns (Shell::platform()).
class PlatformService {
public:
    // achievements_text: data/achievements.json (nullopt = none). backend: nullptr = a NullBackend.
    PlatformService(std::filesystem::path data_dir, const std::optional<std::string>& achievements_text,
                    std::unique_ptr<PlatformBackend> backend = nullptr, const std::string& cloud = kCloudMode);

    bool active() const { return active_; }   // false without achievements: nothing is ever written
    std::string unlock(const std::string& id) { return after(rules_.unlock(id)); }
    std::string set_stat(const std::string& id, double v) { return after(rules_.set_stat(id, v)); }
    std::string add_stat(const std::string& id, double d) { return after(rules_.add_stat(id, d)); }
    std::string flush() { return after(rules_.flush()); }   // at checkpoints: level end, pause, quit
    std::string set_presence(const std::string& k, const std::string& v) { return after(rules_.set_presence(k, v)); }
    std::string clear_presence() { return after(rules_.clear_presence()); }
    std::string saved(const std::string& path) { return after(rules_.saved(path)); }
    std::string overlay(bool active, const std::string& screen) const { return overlay_action(active, screen); }
    void update();   // the backend's callbacks; a store that failed late goes back on the queue, offline
    PlatformBackend& backend() { return *backend_; }
    Platform& rules() { return rules_; }

private:
    std::string after(const PlatformOut& r);
    void persist();

    std::filesystem::path file_;
    std::unique_ptr<PlatformBackend> backend_;
    Platform rules_;
    bool active_ = false;
    std::string last_;
};

// The store backend for this build (PlatformSteam.cpp): the Steamworks adapter when the game was built with
// -DGAMEKIT_STEAM=ON and Steam answered, else nullptr (PlatformService then uses a NullBackend). automated
// (dev.py smoke, tests): nullptr.
std::unique_ptr<PlatformBackend> make_platform_backend(const nlohmann::json& defs, const std::filesystem::path& data_dir,
                                                       bool automated);

}  // namespace core

// {{FOOTER}}
