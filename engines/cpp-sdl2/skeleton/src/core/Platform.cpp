// ---------------------------------------------------------------------------
// Platform.cpp
// Purpose : The platform layer's rules, the null backend and the service (see Platform.hpp).
// Usage   : see Platform.hpp
// Notes   : Ported from tools/golden_vectors.py (achievements_load, Platform, NullBackend, cloud_partition,
//           overlay_action, platform_state_load). A stat value is kept as JSON: an int stat as an integer, a float
//           stat as a double, so the state file and the calls carry the same numbers as the reference.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/Platform.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <utility>

#include "core/AtomicFile.hpp"
#include "core/Log.hpp"

namespace core {

using nlohmann::json;

namespace {

// ---- Constants ----
constexpr int kStateIndent = 1;   // as the web port writes it

template <typename T>
bool contains(const std::vector<T>& list, const T& v) {
    return std::find(list.begin(), list.end(), v) != list.end();
}

template <typename T>
void erase_one(std::vector<T>& list, const T& v) {
    const auto it = std::find(list.begin(), list.end(), v);
    if (it != list.end()) {
        list.erase(it);
    }
}

// A finite number (a JSON boolean is never one).
bool num_ok(const json& v) {
    return v.is_number() && std::isfinite(v.get<double>());
}

// Whole by value, never by type (5.0 is 5).
bool whole(const json& v) {
    return num_ok(v) && std::floor(v.get<double>()) == v.get<double>();
}

bool ok_for(const std::string& kind, const json& v) {
    return kind == "int" ? whole(v) : num_ok(v);
}

// A stat value as every port stores it: an int stat as an integer, a float stat as a double.
json stat_value(const json& sdef, double v) {
    if (sdef["type"] == "int") {
        return static_cast<std::int64_t>(v);
    }
    return v;
}

double clamp_stat(const json& sdef, double v) {
    v = std::max(v, sdef["min"].get<double>());
    if (!sdef["max"].is_null()) {
        v = std::min(v, sdef["max"].get<double>());
    }
    return v;
}

double stat_initial(const json& sdef) {
    return clamp_stat(sdef, 0.0);
}

json empty_defs() {
    return {{"version", kPlatformStateVersion}, {"stats", json::array()}, {"achievements", json::array()}};
}

// Python's dict.get(key, default): a key holding null is null, not the default.
json get(const json& obj, const char* key, const json& dflt) {
    const auto it = obj.find(key);
    return it == obj.end() ? dflt : *it;
}

json strings(const std::vector<std::string>& list) {
    json out = json::array();
    for (const auto& s : list) {
        out.push_back(s);
    }
    return out;
}

json sorted_pairs(const std::map<std::string, std::string>& map) {
    json out = json::array();
    for (const auto& [k, v] : map) {   // std::map is sorted by key (bytewise: ids are ASCII)
        out.push_back(json::array({k, v}));
    }
    return out;
}

}  // namespace

const std::vector<std::string>& platform_stat_types() {
    static const std::vector<std::string> v{"int", "float"};
    return v;
}
const std::vector<std::string>& platform_cloud_modes() {
    static const std::vector<std::string> v{"auto", "api"};
    return v;
}
const std::vector<std::string>& cloud_local_names() {
    static const std::vector<std::string> v{"settings.json", kPlatformStateFile, "telemetry.csv", "log_tail.txt"};
    return v;
}
const std::vector<std::string>& cloud_local_suffixes() {
    static const std::vector<std::string> v{".tmp", ".log"};
    return v;
}
const std::vector<std::string>& cloud_local_dirs() {
    static const std::vector<std::string> v{"logs", "crashes", "captures"};
    return v;
}
const std::vector<std::string>& overlay_pause_screens() {
    static const std::vector<std::string> v{"play"};
    return v;
}

bool platform_id_ok(const json& v) {
    if (!v.is_string()) {
        return false;
    }
    const auto& s = v.get_ref<const std::string&>();
    if (s.empty() || s.size() > kPlatformIdMax) {
        return false;
    }
    for (std::size_t i = 0; i < s.size(); ++i) {
        const char c = s[i];
        const bool letter = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
        if (i == 0 && !letter) {
            return false;
        }
        if (!(letter || (c >= '0' && c <= '9') || c == '_')) {
            return false;
        }
    }
    return true;
}

AchievementsLoad achievements_load(const std::optional<std::string>& text) {
    if (!text || text->empty()) {
        return {empty_defs(), 0};
    }
    const json raw = json::parse(*text, nullptr, false);
    if (raw.is_discarded() || !raw.is_object()) {
        return {empty_defs(), 1};
    }
    int problems = 0;
    json stats = json::array();
    json achievements = json::array();
    std::map<std::string, json> by_id;
    json raw_stats = get(raw, "stats", json::array());
    if (!raw_stats.is_array()) {
        raw_stats = json::array();
        ++problems;
    }
    for (const auto& s : raw_stats) {
        bool ok = s.is_object() && platform_id_ok(get(s, "id", nullptr)) && !by_id.count(s["id"].get<std::string>());
        json kind, lo, hi, inc;
        if (ok) {
            kind = get(s, "type", "int");
            lo = get(s, "min", 0);
            hi = get(s, "max", nullptr);
            inc = get(s, "increment_only", false);
            ok = kind.is_string() && contains(platform_stat_types(), kind.get<std::string>()) &&
                 ok_for(kind.get<std::string>(), lo) &&
                 (hi.is_null() || (ok_for(kind.get<std::string>(), hi) && hi.get<double>() >= lo.get<double>())) &&
                 inc.is_boolean();
        }
        if (!ok) {
            ++problems;
            continue;
        }
        const bool is_int = kind == "int";
        auto conv = [&](const json& x) -> json {
            return is_int ? json(static_cast<std::int64_t>(x.get<double>())) : json(x.get<double>());
        };
        json sdef = {{"id", s["id"]}, {"type", kind}, {"min", conv(lo)}, {"max", hi.is_null() ? json(nullptr) : conv(hi)},
                     {"increment_only", inc}};
        by_id[s["id"].get<std::string>()] = sdef;
        stats.push_back(std::move(sdef));
    }
    json raw_ach = get(raw, "achievements", json::array());
    if (!raw_ach.is_array()) {
        raw_ach = json::array();
        ++problems;
    }
    std::vector<std::string> seen;
    for (const auto& a : raw_ach) {
        bool ok = a.is_object() && platform_id_ok(get(a, "id", nullptr)) &&
                  !contains(seen, a["id"].get<std::string>()) && get(a, "name", nullptr).is_string() &&
                  a["name"] != "" && get(a, "description", "").is_string();
        json stat, threshold, every;
        json sdef;
        if (ok) {
            stat = get(a, "stat", nullptr);
            threshold = get(a, "threshold", nullptr);
            every = get(a, "progress_every", nullptr);
            if (!stat.is_null()) {
                if (stat.is_string() && by_id.count(stat.get<std::string>())) {
                    sdef = by_id[stat.get<std::string>()];
                }
                const std::string kind = sdef.is_object() ? sdef["type"].get<std::string>() : "float";
                ok = sdef.is_object() && ok_for(kind, threshold) && threshold.get<double>() > stat_initial(sdef) &&
                     (sdef["max"].is_null() || threshold.get<double>() <= sdef["max"].get<double>()) &&
                     (every.is_null() || (ok_for(kind, every) && every.get<double>() > 0 &&
                                          every.get<double>() < threshold.get<double>()));
            } else {
                ok = threshold.is_null() && every.is_null();   // a threshold without a stat is a mistake
            }
        }
        if (!ok) {
            ++problems;
            continue;
        }
        seen.push_back(a["id"].get<std::string>());
        achievements.push_back(
            {{"id", a["id"]}, {"name", a["name"]}, {"description", get(a, "description", "")}, {"stat", stat},
             {"threshold", stat.is_null() ? json(nullptr) : stat_value(sdef, threshold.get<double>())},
             {"progress_every", every.is_null() ? json(nullptr) : stat_value(sdef, every.get<double>())}});
    }
    return {{{"version", kPlatformStateVersion}, {"stats", stats}, {"achievements", achievements}}, problems};
}

std::string cloud_partition(const std::string& path) {
    std::vector<std::string> parts;
    std::string part;
    auto end_part = [&] {
        if (!part.empty() && part != ".") {
            parts.push_back(part);
        }
        part.clear();
    };
    for (char c : path) {
        if (c == '/' || c == '\\') {
            end_part();
        } else {
            part.push_back(c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c);   // ASCII only, in every port
        }
    }
    end_part();
    if (parts.empty()) {
        return "local";
    }
    const std::string& name = parts.back();
    if ((parts.size() > 1 && contains(cloud_local_dirs(), parts.front())) || contains(cloud_local_names(), name)) {
        return "local";
    }
    for (const auto& s : cloud_local_suffixes()) {
        if (name.size() >= s.size() && name.compare(name.size() - s.size(), s.size(), s) == 0) {
            return "local";
        }
    }
    return "cloud";
}

std::string overlay_action(bool active, const std::string& screen) {
    return active && contains(overlay_pause_screens(), screen) ? "pause" : "none";
}

// ---- NullBackend ----

json NullBackend::remote() {
    return {{"unlocked", unlocked}, {"stats", stats}};
}

json NullBackend::presence_list() const {
    return sorted_pairs(presence);
}

bool NullBackend::send(const json& call) {
    calls.push_back(call);
    const std::string name = call.at(0).get<std::string>();
    if (name == "set_achievement") {
        const std::string id = call.at(1).get<std::string>();
        if (!contains(staged_unlocks_, id)) {
            staged_unlocks_.push_back(id);
        }
    } else if (name == "set_stat") {
        staged_stats_[call.at(1).get<std::string>()] = call.at(2);
    } else if (name == "store_stats") {
        if (fail_stores > 0) {
            --fail_stores;
            return false;
        }
        for (const auto& u : staged_unlocks_) {
            if (std::find(unlocked.begin(), unlocked.end(), json(u)) == unlocked.end()) {
                unlocked.push_back(u);
            }
        }
        for (const auto& [k, v] : staged_stats_.items()) {
            stats[k] = v;
        }
        staged_unlocks_.clear();
        staged_stats_ = json::object();
    } else if (name == "reset_all_stats") {
        unlocked = json::array();
        stats = json::object();
        staged_unlocks_.clear();
        staged_stats_ = json::object();
    } else if (name == "set_presence") {
        const std::string key = call.at(1).get<std::string>();
        const std::string value = call.at(2).get<std::string>();
        if (value.empty()) {
            presence.erase(key);
        } else {
            presence[key] = value;
        }
    } else if (name == "clear_presence") {
        presence.clear();
    } else if (name == "cloud_write") {
        if (std::find(cloud.begin(), cloud.end(), call.at(1)) == cloud.end()) {
            cloud.push_back(call.at(1));
        }
    }
    return true;
}

// ---- Platform (the rules) ----

Platform::Platform(json defs, PlatformBackend* backend, bool online, std::string cloud)
    : defs_(std::move(defs)), backend_(backend), online_(online), cloud_(std::move(cloud)) {
    for (std::size_t i = 0; i < defs_["stats"].size(); ++i) {
        stat_index_[defs_["stats"][i]["id"].get<std::string>()] = i;
    }
    for (std::size_t i = 0; i < defs_["achievements"].size(); ++i) {
        ach_index_[defs_["achievements"][i]["id"].get<std::string>()] = i;
    }
    reset_local();
}

void Platform::reset_local() {
    unlocked_.clear();
    stats_.clear();
    for (const auto& s : defs_["stats"]) {
        stats_[s["id"].get<std::string>()] = stat_value(s, stat_initial(s));
    }
    pending_stats_.clear();
    pending_unlocks_.clear();
    pending_cloud_.clear();
}

json Platform::state() const {
    json ps = json::array();
    json stats = json::object();
    for (const auto& s : defs_["stats"]) {
        const std::string id = s["id"].get<std::string>();
        if (contains(pending_stats_, id)) {
            ps.push_back(id);
        }
        stats[id] = stats_.at(id);
    }
    return {{"format", kPlatformFormat},
            {"version", kPlatformStateVersion},
            {"unlocked", strings(unlocked_)},
            {"stats", stats},
            {"pending", {{"stats", ps}, {"unlocks", strings(pending_unlocks_)}, {"cloud", strings(pending_cloud_)}}}};
}

void Platform::restore(const json& st) {
    unlocked_ = st["unlocked"].get<std::vector<std::string>>();
    for (const auto& [k, v] : st["stats"].items()) {
        stats_[k] = v;
    }
    pending_stats_ = st["pending"]["stats"].get<std::vector<std::string>>();
    pending_unlocks_ = st["pending"]["unlocks"].get<std::vector<std::string>>();
    pending_cloud_ = st["pending"]["cloud"].get<std::vector<std::string>>();
}

json Platform::presence_list() const {
    return sorted_pairs(presence_);
}

bool Platform::send(const json& call) {
    sent_.push_back(call);
    return backend_->send(call);
}

PlatformOut Platform::done(const char* out) {
    PlatformOut r{out, std::move(sent_)};
    sent_ = json::array();
    return r;
}

void Platform::unlock_local(const std::string& id) {
    unlocked_.push_back(id);
    pending_unlocks_.push_back(id);
}

PlatformOut Platform::unlock(const std::string& id) {
    if (!ach_index_.count(id)) {
        return done("unknown");
    }
    if (contains(unlocked_, id)) {
        return done("already");
    }
    unlock_local(id);
    if (online_) {
        flush_inner();
    }
    return done("unlocked");
}

bool Platform::check(const std::string& sid, double old, double now, bool notify) {
    bool did = false;
    for (const auto& a : defs_["achievements"]) {
        const std::string id = a["id"].get<std::string>();
        if (a["stat"] != sid || contains(unlocked_, id)) {
            continue;
        }
        if (now >= a["threshold"].get<double>()) {
            unlock_local(id);
            did = true;
        } else if (notify && online_ && !a["progress_every"].is_null()) {
            const double step = a["progress_every"].get<double>();
            if (std::floor(now / step) > std::floor(old / step)) {
                send(json::array({"indicate_progress", id, stats_.at(sid), a["threshold"]}));
            }
        }
    }
    return did;
}

PlatformOut Platform::set_stat(const std::string& id, const json& v) {
    if (!stat_index_.count(id)) {
        return done("unknown");
    }
    const json& s = sdef(id);
    if (!ok_for(s["type"].get<std::string>(), v)) {
        return done("refused");
    }
    const double c = clamp_stat(s, v.get<double>());
    const double old = stats_.at(id).get<double>();
    if (s["increment_only"].get<bool>() && c < old) {
        return done("refused");
    }
    if (c == old) {
        return done("same");
    }
    stats_[id] = stat_value(s, c);
    if (!contains(pending_stats_, id)) {
        pending_stats_.push_back(id);
    }
    if (check(id, old, c, true) && online_) {
        flush_inner();
    }
    return done(c != v.get<double>() ? "clamped" : "ok");
}

PlatformOut Platform::add_stat(const std::string& id, const json& d) {
    if (!stat_index_.count(id)) {
        return done("unknown");
    }
    const json& s = sdef(id);
    if (!ok_for(s["type"].get<std::string>(), d)) {
        return done("refused");
    }
    return set_stat(id, stats_.at(id).get<double>() + d.get<double>());
}

std::string Platform::flush_inner() {
    if (!online_) {
        return "offline";
    }
    if (pending_stats_.empty() && pending_unlocks_.empty() && pending_cloud_.empty()) {
        return "nothing";
    }
    if (!pending_stats_.empty() || !pending_unlocks_.empty()) {
        for (const auto& s : defs_["stats"]) {
            const std::string id = s["id"].get<std::string>();
            if (contains(pending_stats_, id)) {
                send(json::array({"set_stat", id, stats_.at(id)}));
            }
        }
        for (const auto& id : pending_unlocks_) {
            send(json::array({"set_achievement", id}));
        }
        if (!send(json::array({"store_stats"}))) {
            online_ = false;   // the store said no: keep everything, wait for connect()
            return "failed";
        }
        pending_stats_.clear();
        pending_unlocks_.clear();
    }
    for (const auto& p : pending_cloud_) {
        send(json::array({"cloud_write", p}));
    }
    pending_cloud_.clear();
    return "sent";
}

PlatformOut Platform::flush() {
    const std::string out = flush_inner();
    return done(out.c_str());
}

PlatformOut Platform::set_presence(const json& key, const json& value) {
    if (!platform_id_ok(key) || !value.is_string() ||
        value.get_ref<const std::string&>().size() > kPresenceMaxValueBytes) {   // bytes: std::string is UTF-8
        return done("refused");
    }
    const std::string k = key.get<std::string>();
    const std::string v = value.get<std::string>();
    const auto it = presence_.find(k);
    if (v.empty()) {
        if (it == presence_.end()) {
            return done("same");
        }
        presence_.erase(it);
    } else {
        if (it != presence_.end() && it->second == v) {
            return done("same");
        }
        if (it == presence_.end() && presence_.size() >= kPresenceMaxKeys) {
            return done("refused");
        }
        presence_[k] = v;
    }
    if (online_) {
        send(json::array({"set_presence", k, v}));
    }
    return done("ok");
}

PlatformOut Platform::clear_presence() {
    if (presence_.empty()) {
        return done("same");
    }
    presence_.clear();
    if (online_) {
        send(json::array({"clear_presence"}));
    }
    return done("ok");
}

PlatformOut Platform::saved(const std::string& path) {
    const std::string part = cloud_partition(path);
    if (part == "cloud" && cloud_ == "api") {
        if (online_) {
            send(json::array({"cloud_write", path}));
        } else if (!contains(pending_cloud_, path)) {
            pending_cloud_.push_back(path);
        }
    }
    return done(part.c_str());
}

PlatformOut Platform::connect(const json& remote) {
    online_ = true;
    const json ru = remote.is_object() ? get(remote, "unlocked", json::array()) : json::array();
    if (ru.is_array()) {
        for (const auto& v : ru) {
            if (!v.is_string()) {
                continue;
            }
            const std::string id = v.get<std::string>();
            if (ach_index_.count(id) && !contains(unlocked_, id)) {
                unlocked_.push_back(id);
            }
            erase_one(pending_unlocks_, id);
        }
    }
    json rs = remote.is_object() ? get(remote, "stats", json::object()) : json::object();
    if (!rs.is_object()) {
        rs = json::object();
    }
    for (const auto& s : defs_["stats"]) {
        const std::string sid = s["id"].get<std::string>();
        const json r0 = get(rs, sid.c_str(), nullptr);
        if (!ok_for(s["type"].get<std::string>(), r0)) {
            continue;
        }
        const double r = clamp_stat(s, r0.get<double>());
        const double old = stats_.at(sid).get<double>();
        const bool pend = contains(pending_stats_, sid);
        double now;
        if (s["increment_only"].get<bool>()) {
            if (r >= old && pend) {
                erase_one(pending_stats_, sid);
            }
            now = std::max(old, r);
        } else {
            now = pend ? old : r;
        }
        stats_[sid] = stat_value(s, now);
        check(sid, old, now, false);
    }
    flush_inner();
    if (online_) {
        for (const auto& [k, v] : presence_) {
            send(json::array({"set_presence", k, v}));
        }
    }
    return done(online_ ? "online" : "failed");
}

PlatformOut Platform::disconnect() {
    online_ = false;
    return done("offline");
}

PlatformOut Platform::reset_all() {
    if (!online_) {
        return done("offline");
    }
    reset_local();
    send(json::array({"reset_all_stats", true}));
    return done("reset");
}

// ---- platform_state_load ----

struct PlatformStateBuilder {
    static PlatformStateLoad load(const json& defs, const std::optional<std::string>& text) {
        NullBackend nb;
        Platform p(defs, &nb);
        if (!text || text->empty()) {
            return {p.state(), 0};
        }
        const json raw = json::parse(*text, nullptr, false);
        if (raw.is_discarded() || !raw.is_object() || get(raw, "format", nullptr) != kPlatformFormat ||
            !whole(get(raw, "version", nullptr)) || raw["version"].get<double>() != kPlatformStateVersion) {
            return {p.state(), 1};
        }
        int problems = 0;
        auto items = [&](const json& v, bool want_array) -> json {
            if (want_array ? v.is_array() : v.is_object()) {
                return v;
            }
            if (!v.is_null()) {
                ++problems;
            }
            return want_array ? json::array() : json::object();
        };
        for (const auto& id : items(get(raw, "unlocked", nullptr), true)) {
            if (id.is_string() && p.has_achievement(id.get<std::string>()) &&
                !contains(p.unlocked_, id.get<std::string>())) {
                p.unlocked_.push_back(id.get<std::string>());
            } else {
                ++problems;
            }
        }
        const json stats = items(get(raw, "stats", nullptr), false);   // a local: items() of a temporary dangles
        for (const auto& [sid, v] : stats.items()) {
            if (!p.has_stat(sid) || !ok_for(p.sdef(sid)["type"].get<std::string>(), v)) {
                ++problems;
                continue;
            }
            p.stats_[sid] = stat_value(p.sdef(sid), clamp_stat(p.sdef(sid), v.get<double>()));
        }
        const json pending = items(get(raw, "pending", nullptr), false);
        for (const auto& id : items(get(pending, "stats", nullptr), true)) {
            if (id.is_string() && p.has_stat(id.get<std::string>()) && !contains(p.pending_stats_, id.get<std::string>())) {
                p.pending_stats_.push_back(id.get<std::string>());
            } else {
                ++problems;
            }
        }
        for (const auto& id : items(get(pending, "unlocks", nullptr), true)) {
            if (id.is_string() && contains(p.unlocked_, id.get<std::string>()) &&
                !contains(p.pending_unlocks_, id.get<std::string>())) {
                p.pending_unlocks_.push_back(id.get<std::string>());
            } else {
                ++problems;
            }
        }
        for (const auto& path : items(get(pending, "cloud", nullptr), true)) {
            if (path.is_string() && cloud_partition(path.get<std::string>()) == "cloud" &&
                !contains(p.pending_cloud_, path.get<std::string>())) {
                p.pending_cloud_.push_back(path.get<std::string>());
            } else {
                ++problems;
            }
        }
        return {p.state(), problems};
    }
};

PlatformStateLoad platform_state_load(const json& defs, const std::optional<std::string>& text) {
    return PlatformStateBuilder::load(defs, text);
}

// ---- PlatformService ----

namespace {
json defs_or_empty(const std::optional<std::string>& text) {
    AchievementsLoad r = achievements_load(text);
    if (r.problems > 0) {
        LOG_WARN("platform", kAchievementsFile << ": " << r.problems << " problem(s), those entries were dropped");
    }
    return r.defs;
}
}  // namespace

PlatformService::PlatformService(std::filesystem::path data_dir, const std::optional<std::string>& achievements_text,
                                 std::unique_ptr<PlatformBackend> backend, const std::string& cloud)
    : file_(std::move(data_dir) / kPlatformStateFile),
      backend_(backend ? std::move(backend) : std::make_unique<NullBackend>()),
      rules_(defs_or_empty(achievements_text), backend_.get(), false, cloud) {
    active_ = !rules_.defs()["stats"].empty() || !rules_.defs()["achievements"].empty();
    if (active_) {
        const std::optional<std::string> text = read_file(file_);
        const PlatformStateLoad st = platform_state_load(rules_.defs(), text);
        if (st.problems > 0) {
            LOG_WARN("platform", kPlatformStateFile << ": " << st.problems << " problem(s), the store's copy wins");
        }
        rules_.restore(st.state);
        last_ = text.value_or("");
    }
    if (backend_->available()) {
        rules_.connect(backend_->remote());
    }
    persist();
}

void PlatformService::persist() {
    if (!active_) {
        return;
    }
    const std::string text = rules_.state().dump(kStateIndent, ' ', false, json::error_handler_t::replace) + "\n";
    if (text == last_) {
        return;
    }
    std::string error;
    if (write_file_atomic(file_, text, &error)) {
        last_ = text;
    } else {
        LOG_WARN("platform", kPlatformStateFile << " not written: " << error);
    }
}

std::string PlatformService::after(const PlatformOut& r) {
    persist();
    return r.out.is_string() ? r.out.get<std::string>() : "";
}

}  // namespace core

// {{FOOTER}}
