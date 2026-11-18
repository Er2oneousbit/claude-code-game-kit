// ---------------------------------------------------------------------------
// test_golden_platform.cpp
// Purpose : Checks the platform layer (src/core/Platform) against every case of data/golden/platform.json, then
//           the PlatformService the shell owns (the cached state file, the save hook, nothing written without
//           data/achievements.json).
// Usage   : python tools/dev.py test     (build/debug/bin/Debug/unit_tests.exe -tc="*platform*")
// Notes   : A case type this file does not know fails. A step's calls are what the rules sent to their backend
//           during that step; "fail_store" is the null backend's hook (its next store_stats fails). Expected
//           values are read from the file at test time. Numbers compare within the file's tolerance.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <chrono>
#include <cmath>
#include <filesystem>
#include <functional>
#include <map>
#include <string>
#include <system_error>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/AtomicFile.hpp"
#include "core/Platform.hpp"
#include "core/PlatformSteam.hpp"
#include "core/SaveStore.hpp"

#ifndef GOLDEN_DIR
#error "GOLDEN_DIR must name the folder with platform.json (CMakeLists.txt sets it)"
#endif

namespace fs = std::filesystem;
using nlohmann::json;

namespace {

double g_tol = 1e-6;

std::string diff(const json& got, const json& want, const std::string& at = "$") {
    if (want.is_number() && got.is_number()) {
        return std::fabs(got.get<double>() - want.get<double>()) <= g_tol ? "" : at + ": got " + got.dump() + ", want " + want.dump();
    }
    if (got.type() != want.type()) {
        return at + ": got " + got.dump() + ", want " + want.dump();
    }
    if (want.is_array()) {
        if (got.size() != want.size()) {
            return at + ": " + std::to_string(got.size()) + " items, want " + std::to_string(want.size()) + " " + got.dump();
        }
        for (std::size_t i = 0; i < want.size(); ++i) {
            const std::string d = diff(got[i], want[i], at + "[" + std::to_string(i) + "]");
            if (!d.empty()) {
                return d;
            }
        }
        return "";
    }
    if (want.is_object()) {
        for (const auto& [key, value] : got.items()) {
            if (!want.contains(key)) {
                return at + "." + key + ": not expected";
            }
        }
        for (const auto& [key, value] : want.items()) {
            if (!got.contains(key)) {
                return at + "." + key + ": missing";
            }
            const std::string d = diff(got.at(key), value, at + "." + key);
            if (!d.empty()) {
                return d;
            }
        }
        return "";
    }
    return got == want ? "" : at + ": got " + got.dump() + ", want " + want.dump();
}

void same(const json& got, const json& want, const std::string& what) {
    const std::string d = diff(got, want);
    CHECK_MESSAGE(d.empty(), what << " " << d);
}

std::optional<std::string> optional_text(const json& j) {
    return j.is_string() ? std::optional<std::string>(j.get<std::string>()) : std::nullopt;
}

json strings(const std::vector<std::string>& v) {
    json out = json::array();
    for (const auto& s : v) {
        out.push_back(s);
    }
    return out;
}

core::PlatformOut step(core::Platform& p, core::NullBackend& nb, const json& op) {
    const std::string kind = op.at(0).get<std::string>();
    if (kind == "fail_store") {
        ++nb.fail_stores;
        return {nullptr, json::array()};
    }
    if (kind == "overlay") {
        return {core::overlay_action(op.at(1).get<bool>(), op.at(2).get<std::string>()), json::array()};
    }
    if (kind == "unlock") return p.unlock(op.at(1).get<std::string>());
    if (kind == "set_stat") return p.set_stat(op.at(1).get<std::string>(), op.at(2));
    if (kind == "add_stat") return p.add_stat(op.at(1).get<std::string>(), op.at(2));
    if (kind == "flush") return p.flush();
    if (kind == "set_presence") return p.set_presence(op.at(1), op.at(2));
    if (kind == "clear_presence") return p.clear_presence();
    if (kind == "saved") return p.saved(op.at(1).get<std::string>());
    if (kind == "connect") return p.connect(op.at(1));
    if (kind == "disconnect") return p.disconnect();
    if (kind == "reset_all") return p.reset_all();
    FAIL("unknown step " << kind);
    return {};
}

void check_format(const json& c) {
    json mine = c;
    mine["state_format"] = core::kPlatformFormat;
    mine["state_file"] = core::kPlatformStateFile;
    mine["state_version"] = core::kPlatformStateVersion;
    mine["id_max"] = core::kPlatformIdMax;
    mine["stat_types"] = strings(core::platform_stat_types());
    mine["presence_max_keys"] = core::kPresenceMaxKeys;
    mine["presence_max_value_bytes"] = core::kPresenceMaxValueBytes;
    mine["cloud_modes"] = strings(core::platform_cloud_modes());
    mine["cloud_local_names"] = strings(core::cloud_local_names());
    mine["cloud_local_suffixes"] = strings(core::cloud_local_suffixes());
    mine["cloud_local_dirs"] = strings(core::cloud_local_dirs());
    mine["overlay_pause_screens"] = strings(core::overlay_pause_screens());
    same(mine, c, "format");
}

void check_achievements_load(const json& c) {
    for (const json& p : c.at("points")) {
        const core::AchievementsLoad r = core::achievements_load(optional_text(p.at(1)));
        same(r.defs, p.at(2), p.at(0).get<std::string>() + ": defs");
        same(r.problems, p.at(3), p.at(0).get<std::string>() + ": problems");
    }
}

void check_cloud_partition(const json& c) {
    for (const json& p : c.at("points")) {
        same(core::cloud_partition(p.at(0).get<std::string>()), p.at(1), "\"" + p.at(0).get<std::string>() + "\"");
    }
}

void check_overlay(const json& c) {
    for (const json& p : c.at("points")) {
        same(core::overlay_action(p.at(0).get<bool>(), p.at(1).get<std::string>()), p.at(2), p.dump());
    }
}

void check_script(const json& c) {
    core::NullBackend nb;
    core::Platform p(c.at("defs"), &nb, c.at("online").get<bool>(), c.at("cloud").get<std::string>());
    int i = 0;
    for (const json& s : c.at("steps")) {
        const core::PlatformOut r = step(p, nb, s.at("op"));
        const std::string w = c.at("name").get<std::string>() + " step " + std::to_string(i++) + " " + s.at("op").dump();
        same(r.out, s.at("out"), w + ": out");
        same(r.calls, s.at("calls"), w + ": calls");
        same(p.state(), s.at("state"), w + ": state");
        same(p.presence_list(), s.at("presence"), w + ": presence");
        same(p.online(), s.at("online"), w + ": online");
    }
}

void check_state_load(const json& c) {
    for (const json& p : c.at("points")) {
        const core::PlatformStateLoad r = core::platform_state_load(c.at("defs"), optional_text(p.at(1)));
        same(r.state, p.at(2), p.at(0).get<std::string>() + ": state");
        same(r.problems, p.at(3), p.at(0).get<std::string>() + ": problems");
    }
}

void check_null_backend(const json& c) {
    core::NullBackend nb;
    int i = 0;
    for (const json& s : c.at("sends")) {
        const json& call = s.at(0);
        json got = nullptr;
        if (call.size() == 1 && call.at(0) == "fail_next_store") {
            ++nb.fail_stores;
        } else {
            got = nb.send(call);
        }
        const std::string w = "send " + std::to_string(i++) + " " + call.dump();
        same(got, s.at(1), w + ": ok");
        same(nb.remote(), s.at(2), w + ": remote");
        same(nb.presence_list(), s.at(3), w + ": presence");
        same(nb.cloud, s.at(4), w + ": cloud");
    }
    same(nb.calls, c.at("calls"), "calls");
}

struct TempDir {
    fs::path path;
    TempDir() {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        path = fs::temp_directory_path() / core::path_from_utf8("gamekit-platform-\xC3\x8D-" + std::to_string(stamp));
        fs::create_directories(path);
    }
    ~TempDir() {
        std::error_code ec;
        fs::remove_all(path, ec);
    }
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
};

const char* kSample = R"({"stats": [{"id": "kills", "max": 100, "increment_only": true}], "achievements": [{"id": "first", "name": "First"}, {"id": "kills_10", "name": "Ten", "stat": "kills", "threshold": 10}]})";

}  // namespace

TEST_CASE("golden vectors: platform.json") {
    const auto path = core::path_from_utf8(GOLDEN_DIR) / "platform.json";
    const auto text = core::read_file(path);
    REQUIRE_MESSAGE(text.has_value(), "cannot read " << core::path_to_utf8(path));
    const json vectors = json::parse(*text);
    g_tol = vectors.at("tolerance").get<double>();
    const std::map<std::string, std::function<void(const json&)>> checkers{
        {"platform_format", check_format}, {"achievements_load", check_achievements_load},
        {"cloud_partition", check_cloud_partition}, {"overlay", check_overlay}, {"platform_script", check_script},
        {"platform_state_load", check_state_load}, {"null_backend", check_null_backend}};
    int checked = 0;
    for (const json& c : vectors.at("cases")) {
        const std::string type = c.at("type").get<std::string>();
        const auto it = checkers.find(type);
        REQUIRE_MESSAGE(it != checkers.end(), "unknown case type " << type << ": port it, then add a checker here");
        INFO(c.at("name").get<std::string>());
        it->second(c);
        ++checked;
    }
    MESSAGE("platform.json: " << checked << " cases checked");
    CHECK(checked >= 19);
}

TEST_CASE("the platform service writes nothing without data/achievements.json") {
    TempDir dir;
    core::PlatformService ps(dir.path, std::nullopt);
    CHECK_FALSE(ps.active());
    CHECK(ps.unlock("first") == "unknown");
    CHECK(ps.flush() == "nothing");
    CHECK(ps.saved("save_1.json") == "cloud");
    CHECK(fs::is_empty(dir.path));
}

TEST_CASE("the platform service caches its state file and reloads it") {
    TempDir dir;
    {
        core::PlatformService ps(dir.path, std::string(kSample));
        CHECK(ps.add_stat("kills", 12) == "ok");
        CHECK(ps.unlock("first") == "unlocked");
    }
    core::PlatformService again(dir.path, std::string(kSample));
    same(strings(again.rules().unlocked()), json::array({"kills_10", "first"}), "reloaded unlocks");
    CHECK(again.unlock("first") == "already");
    CHECK_FALSE(fs::exists(core::temp_path_for(dir.path / core::kPlatformStateFile)));
}

TEST_CASE("a save calls the platform layer's saved() once it is on disk") {
    TempDir dir;
    core::PlatformService ps(dir.path, std::string(kSample), nullptr, "api");
    core::SaveStore store(dir.path / "save_1.json");
    std::vector<std::string> seen;
    store.on_saved = [&](const std::string& name) {
        seen.push_back(name);
        ps.saved(name);
    };
    REQUIRE(store.save(json{{"level", 1}}));
    CHECK(seen == std::vector<std::string>{"save_1.json"});
    same(static_cast<core::NullBackend&>(ps.backend()).cloud, json::array({"save_1.json"}), "cloud writes");
}

TEST_CASE("the Steam backend maps platform calls to the SDK calls (fake SDK) and a refused StoreStats fails the store") {
    TempDir dir;
    std::vector<std::string> log;
    bool store_ok = true;
    core::SteamCalls calls;
    calls.set_achievement = [&](const std::string& id) { log.push_back("SetAchievement " + id); return true; };
    calls.get_achievement = [](const std::string& id, bool* out) { *out = id == "first"; return true; };
    calls.set_stat_int = [&](const std::string& id, std::int32_t v) { log.push_back("SetStat " + id + " " + std::to_string(v)); return true; };
    calls.set_stat_float = [&](const std::string& id, float) { log.push_back("SetStatF " + id); return true; };
    calls.get_stat_int = [](const std::string&, std::int32_t* out) { *out = 4; return true; };
    calls.get_stat_float = [](const std::string&, float* out) { *out = 0.0f; return true; };
    calls.store_stats = [&] { log.push_back("StoreStats"); return store_ok; };
    calls.set_rich_presence = [&](const std::string& k, const std::string& v) { log.push_back("SetRichPresence " + k + " " + v); return true; };
    calls.run_callbacks = [&] { log.push_back("RunCallbacks"); };
    const json defs = core::achievements_load(std::string(kSample)).defs;
    auto backend = std::make_unique<core::SteamBackend>(defs, dir.path, calls);
    core::SteamBackend* steam = backend.get();
    same(steam->remote(), json{{"unlocked", {"first"}}, {"stats", {{"kills", 4}}}}, "remote");
    core::PlatformService ps(dir.path, std::string(kSample), std::move(backend));
    CHECK(ps.add_stat("kills", 12) == "ok");   // the store had 4: 16, and kills_10 unlocks
    CHECK(log == std::vector<std::string>{"SetStat kills 16", "SetAchievement kills_10", "StoreStats"});
    log.clear();
    store_ok = false;
    CHECK(ps.unlock("first") == "already");
    CHECK(ps.set_presence("status", "Menu") == "ok");
    CHECK(log == std::vector<std::string>{"SetRichPresence status Menu"});
    ps.rules().set_stat("kills", 20);
    CHECK(ps.flush() == "failed");
    CHECK_FALSE(ps.rules().online());
    bool seen = false;
    steam->on_overlay = [&](bool active) { seen = active; };
    steam->overlay_changed(true);
    ps.update();
    CHECK(seen);
    CHECK(log.back() == "RunCallbacks");
}

TEST_CASE("an enabled Steam backend starts without data/achievements.json (docs/PLATFORM.md section 6)") {
    TempDir dir;
    std::vector<std::string> log;
    core::SteamCalls calls;
    calls.set_rich_presence = [&](const std::string& k, const std::string& v) { log.push_back(k + " " + v); return true; };
    calls.get_achievement = [](const std::string&, bool* out) { *out = false; return true; };
    const json none = core::achievements_load(std::nullopt).defs;
    auto backend = core::make_steam_backend(none, dir.path, false, [] { return true; }, [&] { return calls; });
    REQUIRE(backend != nullptr);
    core::PlatformService ps(dir.path, std::nullopt, std::move(backend));
    CHECK(ps.set_presence("status", "Menu") == "ok");
    CHECK(log == std::vector<std::string>{"status Menu"});
    CHECK(core::make_steam_backend(none, dir.path, false, [] { return false; }, [&] { return calls; }) == nullptr);
    CHECK(core::make_steam_backend(none, dir.path, true, [] { return true; }, [&] { return calls; }) == nullptr);
}

TEST_CASE("a store UserStatsStored reports failed after StoreStats accepted it goes back on the queue, offline") {
    TempDir dir;
    std::vector<std::string> log;
    core::SteamCalls calls;
    calls.set_achievement = [&](const std::string& id) { log.push_back("SetAchievement " + id); return true; };
    calls.get_achievement = [](const std::string&, bool* out) { *out = false; return true; };
    calls.set_stat_int = [&](const std::string& id, std::int32_t v) { log.push_back("SetStat " + id + " " + std::to_string(v)); return true; };
    calls.get_stat_int = [](const std::string&, std::int32_t* out) { *out = 0; return true; };
    calls.store_stats = [&] { log.push_back("StoreStats"); return true; };
    auto backend = std::make_unique<core::SteamBackend>(core::achievements_load(std::string(kSample)).defs, dir.path, calls);
    core::SteamBackend* steam = backend.get();
    core::PlatformService ps(dir.path, std::string(kSample), std::move(backend));
    CHECK(ps.add_stat("kills", 12) == "ok");   // kills_10 unlocks and flushes; StoreStats accepts it
    CHECK(ps.rules().online());
    steam->stats_stored(false);                // UserStatsStored_t: k_EResultFail
    ps.update();
    CHECK_FALSE(ps.rules().online());
    same(ps.rules().state()["pending"], json{{"stats", {"kills"}}, {"unlocks", {"kills_10"}}, {"cloud", json::array()}}, "queued again");
    log.clear();
    ps.rules().connect(json::object());
    CHECK(log == std::vector<std::string>{"SetStat kills 12", "SetAchievement kills_10", "StoreStats"});
    steam->stats_stored(true);
    ps.update();
    CHECK(ps.rules().online());
}

TEST_CASE("without GAMEKIT_STEAM (or in an automated run) the backend is the null one") {
    TempDir dir;
    CHECK(core::make_platform_backend(json::object(), dir.path, true) == nullptr);
#if !defined(GAMEKIT_STEAM)
    CHECK(core::make_platform_backend(json::object(), dir.path, false) == nullptr);
#endif
}
