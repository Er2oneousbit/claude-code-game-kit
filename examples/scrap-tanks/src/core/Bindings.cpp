// ---------------------------------------------------------------------------
// Bindings.cpp
// Purpose : Implementation of the action map, rebinding and button glyphs (see Bindings.hpp).
// Usage   : compiled into the `core` library; call through Bindings.hpp.
// Notes   : The pad names follow SDL's GameController layout by position (south = A on Xbox, Cross on
//           PlayStation). Add an action by adding it to the defaults below and to docs/GDD.md's controls.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/Bindings.hpp"

#include <sstream>

namespace core {

namespace {

// ---- Tunables: the default controls (slot 0 keyboard, slot 1 pad) ----
// A function-local static, so code that runs during static initialization can call default_bindings() safely.
const Bindings& make_default_bindings() {
    static const Bindings defaults = {
        {"ui_up", {"key:up", "pad:dpad_up"}},          {"ui_down", {"key:down", "pad:dpad_down"}},
        {"ui_left", {"key:left", "pad:dpad_left"}},    {"ui_right", {"key:right", "pad:dpad_right"}},
        {"ui_accept", {"key:enter", "pad:south"}},     {"ui_cancel", {"key:escape", "pad:east"}},
        {"move_left", {"key:a", "pad:dpad_left"}},     {"move_right", {"key:d", "pad:dpad_right"}},
        {"move_up", {"key:w", "pad:dpad_up"}},         {"move_down", {"key:s", "pad:dpad_down"}},
        {"jump", {"key:space", "pad:south"}},          {"attack", {"key:j", "pad:west"}},
        {"interact", {"key:e", "pad:north"}},          {"pause", {"key:escape", "pad:start"}},
    };
    return defaults;
}

using NameMap = std::pair<std::string_view, std::string_view>;

// Pad button -> the name on the controller (prompt art files are named <prefix>_<name>)
constexpr NameMap kXboxNames[] = {
    {"south", "a"}, {"east", "b"}, {"west", "x"}, {"north", "y"}, {"l1", "lb"}, {"r1", "rb"},
    {"l2", "lt"}, {"r2", "rt"}, {"start", "menu"}, {"select", "view"},
};
constexpr NameMap kPlayStationNames[] = {
    {"south", "cross"}, {"east", "circle"}, {"west", "square"}, {"north", "triangle"},
    {"start", "options"}, {"select", "share"},
};
// Last device -> glyph set for "auto"
constexpr NameMap kDeviceSets[] = {
    {"keyboard", "keyboard"}, {"mouse", "keyboard"}, {"pad_xbox", "xbox"}, {"pad_playstation", "playstation"},
};

// The mapped name, or nullopt when the table has no entry.
template <std::size_t N>
std::optional<std::string> find_name(const NameMap (&table)[N], const std::string& name) {
    for (const auto& [from, to] : table) {
        if (from == name) {
            return std::string(to);
        }
    }
    return std::nullopt;
}

bool starts_with(const std::string& text, std::string_view prefix) {
    return text.compare(0, prefix.size(), prefix) == 0;
}

}  // namespace

const Bindings& default_bindings() {
    return make_default_bindings();
}

std::string group_of(const std::string& action) {
    return starts_with(action, kUiPrefix) ? "ui" : "game";
}

std::optional<RebindResult> rebind(const Bindings& bindings, const std::string& action, std::size_t slot,
                                   const std::string& binding) {
    RebindResult r{bindings, {}};
    std::vector<std::string>& list = r.bindings[action];  // creates the action when it is new
    if (slot > list.size()) {
        return std::nullopt;
    }
    const std::string old = slot < list.size() ? list[slot] : "";
    const std::string group = group_of(action);
    if (!binding.empty()) {
        for (const auto& [other, names] : r.bindings) {  // sorted by action, then slot
            if (group_of(other) != group) {
                continue;
            }
            for (std::size_t s = 0; s < names.size(); ++s) {
                if (names[s] == binding && !(other == action && s == slot)) {
                    r.conflicts.emplace_back(other, s);
                }
            }
        }
    }
    if (slot == list.size()) {
        list.push_back(binding);
    } else {
        list[slot] = binding;
    }
    for (const auto& [other, s] : r.conflicts) {
        r.bindings[other][s] = old;  // the swap: the other action takes this slot's old binding
    }
    return r;
}

std::string glyph_set(const std::string& setting, const std::string& last_device) {
    if (setting != "auto") {
        return setting;
    }
    return find_name(kDeviceSets, last_device).value_or("generic");  // an unknown pad: generic pad art
}

std::string glyph_name(const std::string& gset, const std::string& binding) {
    const std::size_t colon = binding.find(':');
    const std::string kind = binding.substr(0, colon);
    std::string name = colon == std::string::npos ? "" : binding.substr(colon + 1);
    if (kind == "key") {
        return "key_" + name;
    }
    if (kind == "mouse") {
        return "mouse_" + name;
    }
    if (kind == "pad_axis") {
        name = starts_with(name, "left") ? "lstick" : "rstick";
    } else if (kind != "pad") {
        return "unknown";
    }
    if (gset == "xbox") {
        return "xbox_" + find_name(kXboxNames, name).value_or(name);
    }
    if (gset == "playstation") {
        return "ps_" + find_name(kPlayStationNames, name).value_or(name);
    }
    return "pad_" + name;
}

std::string prompt_binding(const Bindings& bindings, const std::string& action, const std::string& gset) {
    const auto it = bindings.find(action);
    const std::size_t slot = gset == "keyboard" ? kKeyboardSlot : kPadSlot;
    if (it == bindings.end() || slot >= it->second.size()) {
        return "";
    }
    return it->second[slot];
}

Bindings bindings_from_json(const nlohmann::json& j) {
    Bindings out;
    if (!j.is_object()) {
        return out;
    }
    for (const auto& [action, list] : j.items()) {
        if (!list.is_array()) {
            continue;
        }
        std::vector<std::string>& names = out[action];
        for (const auto& b : list) {
            if (b.is_string()) {
                names.push_back(b.get<std::string>());
            }
        }
    }
    return out;
}

nlohmann::json bindings_to_json(const Bindings& bindings) {
    nlohmann::json j = nlohmann::json::object();
    for (const auto& [action, names] : bindings) {
        j[action] = names;
    }
    return j;
}

std::string narration_line(const std::string& label, const std::string& role, const std::string& value) {
    auto one_line = [](const std::string& s) {
        std::istringstream in(s);
        std::string word, out;
        while (in >> word) out += (out.empty() ? "" : " ") + word;
        return out;
    };
    std::string line = one_line(label).empty() ? "unlabelled" : one_line(label);
    if (!one_line(role).empty()) line += ", " + one_line(role);
    if (!one_line(value).empty()) line += ", " + one_line(value);
    return line;
}

}  // namespace core
