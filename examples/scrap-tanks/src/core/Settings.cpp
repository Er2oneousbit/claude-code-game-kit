// ---------------------------------------------------------------------------
// Settings.cpp
// Purpose : Implementation of the settings defaults, schema and loader (see Settings.hpp).
// Usage   : compiled into the `core` library; call through Settings.hpp.
// Notes   : The defaults are built field by field (not from a nested initializer list), because
//           nlohmann::json reads a two-element list that starts with a string as an object member.
//           Add a setting in three places: default_settings(), schema() and docs/GDD.md's settings list
//           (and the reference, tools/golden_vectors.py, when the kit itself changes).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/Settings.hpp"

#include <algorithm>
#include <array>
#include <climits>
#include <cmath>
#include <type_traits>
#include <utility>

#include "core/AtomicFile.hpp"
#include "core/Bindings.hpp"
#include "core/I18n.hpp"

namespace core {

using nlohmann::json;

namespace {

// ---- Tunables ----
constexpr int kSettingsIndent = 2;            // pretty-printed: players open this file in a text editor
constexpr double kMaxResolutionSide = INT_MAX;  // the reference takes any whole number; C++ must not overflow

enum class Rule { Num, Bool, Enum, Res };

struct Field {
    const char* name;
    Rule rule;
    double lo = 0.0;            // Num: allowed range
    double hi = 0.0;
    std::vector<json> values;   // Enum: allowed values
};

struct Section {
    const char* name;
    std::vector<Field> fields;
};

template <typename T, std::size_t N>
std::vector<json> choices(const std::array<T, N>& values) {
    std::vector<json> out;
    for (const auto& v : values) {
        if constexpr (std::is_same_v<T, std::string_view>) {
            out.emplace_back(std::string(v));
        } else {
            out.emplace_back(v);
        }
    }
    return out;
}

Field num(const char* name, double lo, double hi) { return {name, Rule::Num, lo, hi, {}}; }
Field flag(const char* name) { return {name, Rule::Bool, 0.0, 0.0, {}}; }
Field one_of(const char* name, std::vector<json> values) { return {name, Rule::Enum, 0.0, 0.0, std::move(values)}; }
Field resolution(const char* name) { return {name, Rule::Res, 0.0, 0.0, {}}; }

// The validation rules per section and field. Section order does not change the result.
const std::vector<Section>& schema() {
    static const std::vector<Section> sections = {
        {"display", {one_of("mode", choices(kDisplayModes)), flag("vsync"), one_of("frame_cap", choices(kFrameCaps)),
                     resolution("resolution"), num("ui_scale", 0.75, 2.0)}},
        {"audio", {num("master", 0.0, 1.0), num("music", 0.0, 1.0), num("sfx", 0.0, 1.0), num("ui", 0.0, 1.0),
                   num("voice", 0.0, 1.0), flag("mono")}},
        {"access", {num("text_scale", 0.75, 2.0), flag("subtitles"), one_of("subtitle_size", choices(kSubtitleSizes)),
                    num("subtitle_background", 0.0, 1.0), flag("speaker_names"), flag("subtitle_barks"),
                    flag("captions_sfx"), one_of("colorblind", choices(kColorblindModes)), flag("reduce_motion"),
                    num("shake_scale", 0.0, 1.0), flag("flash_limit"), flag("hold_to_toggle"),
                    one_of("difficulty", choices(kDifficulties)), num("game_speed", 0.5, 1.0)}},
        {"input", {num("deadzone", 0.0, 0.9), flag("invert_y"), one_of("glyphs", choices(kGlyphSets))}},
        {"telemetry", {one_of("consent", choices(kConsentValues))}},
    };
    return sections;
}

// One field's value after validation, and whether it had to be fixed.
std::pair<json, bool> fix(const Field& f, const json& value, const json& fallback) {
    switch (f.rule) {
        case Rule::Bool:
            return value.is_boolean() ? std::make_pair(value, false) : std::make_pair(fallback, true);
        case Rule::Num: {
            if (!value.is_number() || std::isnan(value.get<double>())) {  // is_number() is false for true/false
                return {fallback, true};
            }
            const double v = value.get<double>();
            const double clamped = std::min(std::max(v, f.lo), f.hi);
            return {json(clamped), clamped != v};
        }
        case Rule::Enum:
            for (const json& allowed : f.values) {
                const bool both_numbers = allowed.is_number() && value.is_number();
                const bool both_strings = allowed.is_string() && value.is_string();
                if ((both_numbers && allowed.get<double>() == value.get<double>()) ||
                    (both_strings && allowed == value)) {
                    return {allowed, false};  // 60.0 in the file becomes the choice 60
                }
            }
            return {fallback, true};
        case Rule::Res: {
            bool ok = value.is_array() && value.size() == 2;
            for (std::size_t i = 0; ok && i < 2; ++i) {
                const json& n = value[i];
                ok = n.is_number() && n.get<double>() >= 1.0 && n.get<double>() <= kMaxResolutionSide &&
                     n.get<double>() == std::floor(n.get<double>());
            }
            if (!ok) {
                return {fallback, true};
            }
            // Whole numbers in any spelling (1280.0) become integers without counting as a problem
            return {json::array({static_cast<long long>(value[0].get<double>()),
                                 static_cast<long long>(value[1].get<double>())}),
                    false};
        }
    }
    return {fallback, true};
}

// input.bindings: the defaults, with each action the file names replaced by its string entries.
json fix_bindings(const json& value, std::vector<std::string>& problems) {
    json out = bindings_to_json(default_bindings());
    if (!value.is_object()) {
        problems.emplace_back("input.bindings");
        return out;
    }
    for (const auto& [action, list] : value.items()) {
        if (!list.is_array()) {
            problems.push_back("input.bindings." + action);
            continue;  // keeps the default for a known action
        }
        json clean = json::array();
        for (const json& b : list) {
            if (b.is_string()) {
                clean.push_back(b);
            }
        }
        if (clean.size() != list.size()) {
            problems.push_back("input.bindings." + action);
        }
        out[action] = clean;
    }
    return out;
}

}  // namespace

json default_settings() {
    json s = json::object();
    s["version"] = kSettingsVersion;
    json& display = s["display"];
    display["mode"] = "windowed";
    display["vsync"] = true;
    display["frame_cap"] = 0;
    display["resolution"] = json::array({1920, 1080});
    display["ui_scale"] = 1.0;
    json& audio = s["audio"];
    audio["master"] = 1.0;
    audio["music"] = 0.8;
    audio["sfx"] = 1.0;
    audio["ui"] = 1.0;
    audio["voice"] = 1.0;
    audio["mono"] = false;
    s["language"] = kFallbackLocale;
    json& access = s["access"];
    access["text_scale"] = 1.0;
    access["subtitles"] = true;
    access["subtitle_size"] = "medium";
    access["subtitle_background"] = 0.6;
    access["speaker_names"] = true;
    access["subtitle_barks"] = false;
    access["captions_sfx"] = false;
    access["colorblind"] = "none";
    access["reduce_motion"] = false;
    access["shake_scale"] = 1.0;
    access["flash_limit"] = true;
    access["hold_to_toggle"] = false;
    access["difficulty"] = "normal";
    access["game_speed"] = 1.0;
    json& input = s["input"];
    input["bindings"] = bindings_to_json(default_bindings());
    input["deadzone"] = 0.2;
    input["invert_y"] = false;
    input["glyphs"] = "auto";
    s["telemetry"]["consent"] = "unset";
    return s;
}

SettingsLoad settings_load(const std::optional<std::string>& text) {
    const json defaults = default_settings();
    json raw = json::object();
    if (text) {
        raw = json::parse(*text, nullptr, /*allow_exceptions*/ false);
        if (raw.is_discarded()) {
            return {defaults, {"unreadable"}};
        }
    }
    if (!raw.is_object()) {
        return {defaults, {"not an object"}};
    }
    SettingsLoad r;
    r.settings = raw;  // unknown top-level keys are kept
    r.settings["version"] = kSettingsVersion;
    const auto lang = raw.find("language");
    const bool lang_ok = lang != raw.end() && lang->is_string() &&
                         utf8_length(lang->get_ref<const std::string&>()) >= kLanguageMinLength &&
                         utf8_length(lang->get_ref<const std::string&>()) <= kLanguageMaxLength;
    if (!lang_ok) {
        r.settings["language"] = kFallbackLocale;
        if (lang != raw.end()) {
            r.problems.emplace_back("language");
        }
    }
    const json empty = json::object();
    for (const Section& section : schema()) {
        const json* src = &empty;
        const auto found = raw.find(section.name);
        if (found != raw.end()) {
            if (found->is_object()) {
                src = &*found;
            } else {
                r.problems.emplace_back(section.name);
            }
        }
        json out = *src;  // unknown keys inside a section are kept too
        for (const Field& f : section.fields) {
            const json& fallback = defaults.at(section.name).at(f.name);
            const auto value = src->find(f.name);
            if (value == src->end()) {
                out[f.name] = fallback;
                continue;
            }
            auto [fixed, bad] = fix(f, *value, fallback);
            if (bad) {
                r.problems.push_back(std::string(section.name) + "." + f.name);
            }
            out[f.name] = std::move(fixed);
        }
        if (std::string(section.name) == "input") {
            const auto b = src->find("bindings");
            out["bindings"] = b != src->end() ? fix_bindings(*b, r.problems) : defaults.at("input").at("bindings");
        }
        r.settings[section.name] = std::move(out);
    }
    return r;
}

SettingsLoad settings_load_file(const std::filesystem::path& file) {
    std::string error;
    const std::optional<std::string> text = read_file(file, &error);
    if (!text && !error.empty()) {
        return {default_settings(), {"unreadable"}};
    }
    return settings_load(text);
}

bool settings_save_file(const std::filesystem::path& file, const json& settings, std::string* error) {
    const std::string text = settings.dump(kSettingsIndent, ' ', false, json::error_handler_t::replace) + "\n";
    return write_file_atomic(file, text, error);
}

double effective_shake(const json& settings) {
    const auto access = settings.find("access");
    if (access == settings.end() || !access->is_object()) {
        return 1.0;
    }
    const auto reduce = access->find("reduce_motion");
    if (reduce != access->end() && reduce->is_boolean() && reduce->get<bool>()) {
        return 0.0;
    }
    const auto scale = access->find("shake_scale");
    return scale != access->end() && scale->is_number() ? scale->get<double>() : 1.0;
}

bool telemetry_allowed(const json& settings) {
    const auto telemetry = settings.find("telemetry");
    if (telemetry == settings.end() || !telemetry->is_object()) {
        return false;
    }
    const auto consent = telemetry->find("consent");
    return consent != telemetry->end() && consent->is_string() && consent->get<std::string>() == "yes";
}

}  // namespace core
