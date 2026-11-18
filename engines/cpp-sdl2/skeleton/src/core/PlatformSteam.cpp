// ---------------------------------------------------------------------------
// PlatformSteam.cpp
// Purpose : SteamBackend (see PlatformSteam.hpp) and make_platform_backend: the null backend in every build, the
//           Steamworks SDK's when the build defines GAMEKIT_STEAM (CMake -DGAMEKIT_STEAM=ON) and Steam starts.
// Usage   : see PlatformSteam.hpp
// Notes   : The #if GAMEKIT_STEAM half is compiled only against the real SDK (STEAMWORKS_SDK), which this kit never
//           ships or downloads; its calls follow the Steamworks API reference (verify against your SDK version).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): UserStatsStored failures reach the layer; make_steam_backend
// ---------------------------------------------------------------------------
#include "core/PlatformSteam.hpp"

#include <cmath>
#include <utility>

#include "core/AtomicFile.hpp"
#include "core/Log.hpp"

#if defined(GAMEKIT_STEAM)
#include <steam/steam_api.h>
#endif

namespace core {

using nlohmann::json;

SteamBackend::SteamBackend(json defs, std::filesystem::path data_dir, SteamCalls calls)
    : defs_(std::move(defs)), data_dir_(std::move(data_dir)), calls_(std::move(calls)) {}

SteamBackend::~SteamBackend() {
    if (calls_.shutdown) {
        calls_.shutdown();
    }
}

bool SteamBackend::is_int(const std::string& id) const {
    for (const auto& s : defs_["stats"]) {
        if (s["id"] == id) {
            return s["type"] == "int";
        }
    }
    return false;
}

json SteamBackend::remote() {
    json unlocked = json::array();
    for (const auto& a : defs_["achievements"]) {
        bool achieved = false;
        const std::string id = a["id"].get<std::string>();
        if (calls_.get_achievement(id, &achieved) && achieved) {
            unlocked.push_back(id);
        }
    }
    json stats = json::object();
    for (const auto& s : defs_["stats"]) {
        const std::string id = s["id"].get<std::string>();
        if (s["type"] == "int") {
            std::int32_t v = 0;
            if (calls_.get_stat_int(id, &v)) {
                stats[id] = v;
            }
        } else {
            float v = 0.0f;
            if (calls_.get_stat_float(id, &v)) {
                stats[id] = v;
            }
        }
    }
    return {{"unlocked", unlocked}, {"stats", stats}};
}

bool SteamBackend::send(const json& call) {
    const std::string name = call.at(0).get<std::string>();
    auto str = [&call](std::size_t i) { return call.at(i).get<std::string>(); };
    if (name == "set_achievement" || name == "set_stat") {
        staged_.push_back(call);
    }
    if (name == "set_achievement") {
        calls_.set_achievement(str(1));
    } else if (name == "set_stat") {
        if (is_int(str(1))) {
            calls_.set_stat_int(str(1), static_cast<std::int32_t>(call.at(2).get<double>()));
        } else {
            calls_.set_stat_float(str(1), static_cast<float>(call.at(2).get<double>()));
        }
    } else if (name == "store_stats") {
        const bool ok = calls_.store_stats();
        if (ok) {
            inflight_.push_back(staged_);
        }
        staged_ = json::array();
        return ok;
    } else if (name == "indicate_progress") {
        calls_.indicate_progress(str(1), static_cast<std::uint32_t>(call.at(2).get<double>()),
                                 static_cast<std::uint32_t>(call.at(3).get<double>()));
    } else if (name == "reset_all_stats") {
        calls_.reset_all_stats(call.at(1).get<bool>());
    } else if (name == "set_presence") {
        calls_.set_rich_presence(str(1), str(2));
    } else if (name == "clear_presence") {
        calls_.clear_rich_presence();
    } else if (name == "cloud_write") {
        const std::optional<std::string> bytes = read_file(data_dir_ / path_from_utf8(str(1)));
        if (bytes) {
            calls_.file_write(str(1), *bytes);
        }
    }
    return true;
}

void SteamBackend::stats_stored(bool ok) {
    if (inflight_.empty()) {
        return;
    }
    json batch = std::move(inflight_.front());
    inflight_.erase(inflight_.begin());
    if (!ok) {
        failed_.push_back(std::move(batch));
    }
}

std::optional<json> SteamBackend::take_store_failure() {
    if (failed_.empty()) {
        return std::nullopt;
    }
    json batch = std::move(failed_.front());
    failed_.erase(failed_.begin());
    return batch;
}

std::unique_ptr<SteamBackend> make_steam_backend(const json& defs, const std::filesystem::path& data_dir, bool automated,
                                                 const std::function<bool()>& init,
                                                 const std::function<SteamCalls()>& calls) {
    if (automated) {
        return nullptr;   // a smoke run never asks a store
    }
    if (!init()) {
        LOG_WARN("platform", "built with Steam, but Steam did not start (not running, or the app is not owned): "
                             "the null backend runs");
        return nullptr;
    }
    return std::make_unique<SteamBackend>(defs, data_dir, calls());
}

void SteamBackend::update() {
    if (calls_.run_callbacks) {
        calls_.run_callbacks();
    }
    if (overlay_ && on_overlay) {
        on_overlay(*overlay_);
    }
    overlay_.reset();
}

#if defined(GAMEKIT_STEAM)
namespace {

// The SDK's overlay and stats-stored callbacks, forwarded to the backend (registered while it lives).
struct OverlayListener {
    SteamBackend* backend = nullptr;
    STEAM_CALLBACK(OverlayListener, on_overlay, GameOverlayActivated_t);
    STEAM_CALLBACK(OverlayListener, on_stats_stored, UserStatsStored_t);
};

void OverlayListener::on_overlay(GameOverlayActivated_t* e) {
    if (backend) {
        backend->overlay_changed(e->m_bActive != 0);
    }
}

void OverlayListener::on_stats_stored(UserStatsStored_t* e) {
    if (backend) {
        backend->stats_stored(e->m_eResult == k_EResultOK);
    }
}

OverlayListener* g_listener = nullptr;

SteamCalls steam_calls() {
    SteamCalls c;
    c.set_achievement = [](const std::string& id) { return SteamUserStats()->SetAchievement(id.c_str()); };
    c.get_achievement = [](const std::string& id, bool* out) { return SteamUserStats()->GetAchievement(id.c_str(), out); };
    c.set_stat_int = [](const std::string& id, std::int32_t v) { return SteamUserStats()->SetStat(id.c_str(), v); };
    c.set_stat_float = [](const std::string& id, float v) { return SteamUserStats()->SetStat(id.c_str(), v); };
    c.get_stat_int = [](const std::string& id, std::int32_t* out) { return SteamUserStats()->GetStat(id.c_str(), out); };
    c.get_stat_float = [](const std::string& id, float* out) { return SteamUserStats()->GetStat(id.c_str(), out); };
    c.store_stats = [] { return SteamUserStats()->StoreStats(); };
    c.indicate_progress = [](const std::string& id, std::uint32_t cur, std::uint32_t max) {
        return SteamUserStats()->IndicateAchievementProgress(id.c_str(), cur, max);
    };
    c.reset_all_stats = [](bool achievements) { return SteamUserStats()->ResetAllStats(achievements); };
    c.set_rich_presence = [](const std::string& k, const std::string& v) {
        return SteamFriends()->SetRichPresence(k.c_str(), v.c_str());
    };
    c.clear_rich_presence = [] { SteamFriends()->ClearRichPresence(); };
    c.file_write = [](const std::string& name, const std::string& bytes) {
        return SteamRemoteStorage()->FileWrite(name.c_str(), bytes.data(), static_cast<int32>(bytes.size()));
    };
    c.run_callbacks = [] { SteamAPI_RunCallbacks(); };
    c.shutdown = [] {
        delete g_listener;
        g_listener = nullptr;
        SteamAPI_Shutdown();
    };
    return c;
}

}  // namespace
#endif

std::unique_ptr<PlatformBackend> make_platform_backend(const json& defs, const std::filesystem::path& data_dir,
                                                       bool automated) {
#if defined(GAMEKIT_STEAM)
    auto backend = make_steam_backend(defs, data_dir, automated, [] { return SteamAPI_Init(); }, steam_calls);
    if (backend) {
        g_listener = new OverlayListener();
        g_listener->backend = backend.get();
    }
    return backend;
#else
    (void)defs;
    (void)data_dir;
    (void)automated;
    return nullptr;   // the null backend: this build has no Steam
#endif
}

}  // namespace core

// {{FOOTER}}
