// ---------------------------------------------------------------------------
// AudioAccess.hpp
// Purpose : Audio accessibility rules with no SDL in them: which settings slider turns which bus of
//           data/audio_events.json up or down (never twice down one branch), and which arrow a directional caption
//           gets when its sound comes from off screen.
// Usage   : const auto gains = core::user_bus_gains(events_json["buses"], settings_json["audio"]);   // bus -> 0..1
//           const int k = core::caption_direction(src_x - cam_x, src_y - cam_y, view_w / 2, view_h / 2);
//           if (k >= 0) draw_arrow(core::kCaptionArrows[k]);                                       // UTF-8
// Notes   : A port of tools/audio/wavesmith/access.py (the reference); data/golden/access.json must come out the same.
//           Sliders are linear 0..1; a missing or non-numeric one counts as 1 and others clamp. Parents default to
//           "master"; a cycle stops after one step per bus. Directions: screen y grows downwards, -1 while the
//           source is inside the view (edges included), else k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8,
//           clockwise from the right. std::round is not the rule (it rounds halves away from zero).
//
// Pseudocode:
//   gains: for each bus: slider = kSliderForBus[bus]; a parent with the same slider -> 1; none -> 1; else clamp
//   direction: inside the half sizes -> -1; else k from atan2
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

namespace core {

// Bus name -> settings slider. Edit it when your audio_events.json uses other bus names.
inline const std::map<std::string, std::string> kSliderForBus = {
    {"master", "master"}, {"music", "music"}, {"sfx", "sfx"}, {"ambience", "sfx"},
    {"ui", "ui"},         {"dialogue", "voice"}, {"voice", "voice"}};

// Clockwise from the right (y down): right, down-right, down, down-left, left, up-left, up, up-right. Written as
// UTF-8 bytes, not \u escapes: MSVC encodes \u in a narrow string with the build's code page unless /utf-8 is on.
inline const std::array<const char*, 8> kCaptionArrows = {"\xE2\x86\x92", "\xE2\x86\x98", "\xE2\x86\x93",
                                                          "\xE2\x86\x99", "\xE2\x86\x90", "\xE2\x86\x96",
                                                          "\xE2\x86\x91", "\xE2\x86\x97"};

inline double slider_value(const nlohmann::json& sliders, const std::string& name) {
    if (!sliders.is_object() || !sliders.contains(name)) return 1.0;
    const auto& v = sliders.at(name);
    if (!v.is_number() || v.is_boolean()) return 1.0;
    const double x = v.get<double>();
    return std::isfinite(x) ? std::clamp(x, 0.0, 1.0) : 1.0;
}

// {bus: linear gain} from the player's sliders, a slider never applied twice down one branch
inline std::map<std::string, double> user_bus_gains(const nlohmann::json& buses, const nlohmann::json& sliders) {
    auto parent_of = [&buses](const std::string& b) -> std::optional<std::string> {
        if (buses.contains(b) && buses.at(b).is_object() && buses.at(b).contains("parent") &&
            buses.at(b).at("parent").is_string())
            return buses.at(b).at("parent").get<std::string>();
        if (b == "master") return std::nullopt;
        return std::string("master");
    };
    std::map<std::string, double> out;
    const std::size_t count = buses.size();
    for (const auto& item : buses.items()) {
        const std::string name = item.key();
        const auto s = kSliderForBus.find(name);
        bool inherited = false;
        auto p = parent_of(name);
        for (std::size_t n = 0; p && n < count; ++n, p = parent_of(*p)) {
            const auto ps = kSliderForBus.find(*p);
            if (s != kSliderForBus.end() && ps != kSliderForBus.end() && ps->second == s->second) inherited = true;
        }
        out[name] = (s == kSliderForBus.end() || inherited) ? 1.0 : slider_value(sliders, s->second);
    }
    return out;
}

// -1 while the source is inside the view (edges included), else 0..7 clockwise from the right
inline int caption_direction(double dx, double dy, double half_w, double half_h) {
    if (!std::isfinite(dx) || !std::isfinite(dy)) return -1;
    if (std::abs(dx) <= half_w && std::abs(dy) <= half_h) return -1;
    const auto k = static_cast<long long>(std::floor(std::atan2(dy, dx) / (std::acos(-1.0) / 4) + 0.5));
    return static_cast<int>(((k % 8) + 8) % 8);
}

inline std::string caption_arrow(double dx, double dy, double half_w, double half_h) {
    const int k = caption_direction(dx, dy, half_w, half_h);
    return k < 0 ? std::string() : std::string(kCaptionArrows[static_cast<std::size_t>(k)]);
}

}  // namespace core
