// ---------------------------------------------------------------------------
// PlatformSteam.hpp
// Purpose : The Steam backend for the platform layer (#84, docs/PLATFORM.md): the Steamworks SDK called directly.
//           The mapping (which SDK call each platform call becomes) is plain C++ over a table of functions, so it
//           is unit tested with fakes; the SDK half fills that table and exists only in a build configured with
//           -DGAMEKIT_STEAM=ON and STEAMWORKS_SDK pointing at the unpacked SDK (it is never committed).
// Usage   : core::SteamCalls calls = ...;                        // tests: lambdas; a Steam build: steam_calls()
//           auto backend = std::make_unique<core::SteamBackend>(defs, data_dir, std::move(calls));
//           make_platform_backend(automated) does this when the SDK is compiled in and SteamAPI_Init succeeds.
// Notes   : A store StoreStats accepted that UserStatsStored_t later reports failed goes back to the layer through
//           take_store_failure() (its stats and unlocks are queued again). Steam starts whether or not
//           data/achievements.json exists (presence, the overlay and cloud saves need it too). Stats are read with GetStat after the SDK's init (Steamworks 1.61+ loads them without
//           RequestCurrentStats, verify). The overlay arrives through GameOverlayActivated_t (verify).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): UserStatsStored failures reach the layer
//           (stats_stored, take_store_failure); make_steam_backend starts Steam without achievements too
// ---------------------------------------------------------------------------
#pragma once

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/Platform.hpp"

namespace core {

// The SDK calls the backend needs, one function each (ISteamUserStats, ISteamFriends, ISteamRemoteStorage).
struct SteamCalls {
    std::function<bool(const std::string&)> set_achievement;
    std::function<bool(const std::string&, bool*)> get_achievement;
    std::function<bool(const std::string&, std::int32_t)> set_stat_int;
    std::function<bool(const std::string&, float)> set_stat_float;
    std::function<bool(const std::string&, std::int32_t*)> get_stat_int;
    std::function<bool(const std::string&, float*)> get_stat_float;
    std::function<bool()> store_stats;
    std::function<bool(const std::string&, std::uint32_t, std::uint32_t)> indicate_progress;
    std::function<bool(bool)> reset_all_stats;
    std::function<bool(const std::string&, const std::string&)> set_rich_presence;
    std::function<void()> clear_rich_presence;
    std::function<bool(const std::string&, const std::string&)> file_write;   // name, bytes
    std::function<void()> run_callbacks;
    std::function<void()> shutdown;
};

class SteamBackend : public PlatformBackend {
public:
    SteamBackend(nlohmann::json defs, std::filesystem::path data_dir, SteamCalls calls);
    ~SteamBackend() override;
    std::string name() const override { return "steam"; }
    bool available() override { return true; }
    nlohmann::json remote() override;
    bool send(const nlohmann::json& call) override;
    void update() override;
    // The SDK half reports the overlay here; update() hands it to on_overlay on the game's thread.
    void overlay_changed(bool active) { overlay_ = active; }
    // The SDK half reports UserStatsStored_t here (true: k_EResultOK); a failure queues that store's batch.
    void stats_stored(bool ok);
    std::optional<nlohmann::json> take_store_failure() override;

private:
    bool is_int(const std::string& id) const;
    nlohmann::json defs_;
    std::filesystem::path data_dir_;
    SteamCalls calls_;
    std::optional<bool> overlay_;
    nlohmann::json staged_ = nlohmann::json::array();   // set_stat / set_achievement since the last store_stats
    std::vector<nlohmann::json> inflight_;               // batches stores accepted, until their UserStatsStored
    std::vector<nlohmann::json> failed_;                 // batches whose UserStatsStored failed
};

// The Steam backend when init() succeeds (SteamAPI_Init in a Steam build), whatever defs holds (none is fine), else
// nullptr; automated: nullptr. make_platform_backend uses it with the SDK; tests pass fakes.
std::unique_ptr<SteamBackend> make_steam_backend(const nlohmann::json& defs, const std::filesystem::path& data_dir,
                                                 bool automated, const std::function<bool()>& init,
                                                 const std::function<SteamCalls()>& calls);

}  // namespace core
