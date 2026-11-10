// ---------------------------------------------------------------------------
// ShellLogic.cpp
// Purpose : Implementation of the SDL-free shell helpers (see ShellLogic.hpp).
// Usage   : compiled into the `core` library; call through ShellLogic.hpp.
// Notes   : The name tables are the tunables: a key SDL names differently on your platform gets an alias here.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): admits_device_event, no real input in a drive (#276)
// ---------------------------------------------------------------------------
#include "core/ShellLogic.hpp"

#include <algorithm>
#include <cctype>
#include <sstream>
#include <utility>

namespace core {

using nlohmann::json;

namespace {

// ---- Tunables ----
// SDL key name (lowercased, spaces removed) -> the kit's name. Both shifts are "shift": a binding is a key, not a side.
const std::vector<std::pair<std::string, std::string>> kKeyAliases = {
    {"return", "enter"},   {"keypadenter", "enter"}, {"leftshift", "shift"}, {"rightshift", "shift"},
    {"leftctrl", "ctrl"},  {"rightctrl", "ctrl"},    {"leftalt", "alt"},     {"rightalt", "alt"},
    {"leftgui", "gui"},    {"rightgui", "gui"},      {"leftwindows", "gui"}, {"rightwindows", "gui"},
    {"leftcommand", "gui"}, {"rightcommand", "gui"},
};
// SDL gamepad button string -> the kit's positional name
const std::vector<std::pair<std::string, std::string>> kButtons = {
    {"a", "south"}, {"b", "east"}, {"x", "west"}, {"y", "north"}, {"back", "select"}, {"start", "start"},
    {"guide", "home"}, {"leftshoulder", "l1"}, {"rightshoulder", "r1"}, {"leftstick", "l3"}, {"rightstick", "r3"},
    {"dpup", "dpad_up"}, {"dpdown", "dpad_down"}, {"dpleft", "dpad_left"}, {"dpright", "dpad_right"},
};
const std::vector<std::string> kPlayStationHints = {"playstation", "dualshock", "dualsense", "ps3", "ps4", "ps5",
                                                    "wireless controller"};
const std::vector<std::string> kXboxHints = {"xbox", "xinput", "x-box"};

std::string lower_no_spaces(const std::string& text) {
    std::string out;
    for (const unsigned char c : text) {
        if (c != ' ') {
            out.push_back(static_cast<char>(std::tolower(c)));
        }
    }
    return out;
}

bool starts_with(const std::string& text, const std::string& prefix) {
    return text.compare(0, prefix.size(), prefix) == 0;
}

std::string trim_left(const std::string& s) {
    const auto i = s.find_first_not_of(" \t");
    return i == std::string::npos ? "" : s.substr(i);
}

}  // namespace

// ---- Input names --------------------------------------------------------------------------------------------
std::string key_binding(const std::string& sdl_key_name) {
    std::string name = lower_no_spaces(sdl_key_name);
    for (const auto& [from, to] : kKeyAliases) {
        if (name == from) {
            name = to;
            break;
        }
    }
    return "key:" + name;
}

std::string pad_binding(const std::string& sdl_button_name) {
    for (const auto& [from, to] : kButtons) {
        if (sdl_button_name == from) {
            return "pad:" + to;
        }
    }
    return "pad:" + sdl_button_name;
}

std::string device_of_pad(const std::string& name) {
    std::string lower;
    for (const unsigned char c : name) {
        lower.push_back(static_cast<char>(std::tolower(c)));
    }
    // Xbox first: SDL names them "Xbox Wireless Controller", and "wireless controller" alone is Sony's name
    for (const std::string& hint : kXboxHints) {
        if (lower.find(hint) != std::string::npos) {
            return "pad_xbox";
        }
    }
    for (const std::string& hint : kPlayStationHints) {
        if (lower.find(hint) != std::string::npos) {
            return "pad_playstation";
        }
    }
    return "pad_other";
}

std::vector<std::string> actions_for(const Bindings& bindings, const std::string& binding) {
    std::vector<std::string> out;
    for (const auto& [action, list] : bindings) {   // std::map: already sorted by action
        if (std::find(list.begin(), list.end(), binding) != list.end()) {
            out.push_back(action);
        }
    }
    return out;
}

std::string binding_with_prefix(const Bindings& bindings, const std::string& action, const std::string& prefix) {
    const auto it = bindings.find(action);
    if (it == bindings.end()) {
        return "";
    }
    for (const std::string& b : it->second) {
        if (starts_with(b, prefix)) {
            return b;
        }
    }
    return "";
}

// ---- Text ---------------------------------------------------------------------------------------------------
std::vector<std::string> wrap_chars(const std::string& text, std::size_t max_chars) {
    std::vector<std::string> lines;
    if (max_chars == 0) {
        max_chars = 1;
    }
    std::istringstream words(text);
    std::string word;
    std::string line;
    while (words >> word) {
        while (word.size() > max_chars) {           // a word longer than the line: cut it
            if (!line.empty()) {
                lines.push_back(line);
                line.clear();
            }
            lines.push_back(word.substr(0, max_chars));
            word = word.substr(max_chars);
        }
        if (line.empty()) {
            line = word;
        } else if (line.size() + 1 + word.size() <= max_chars) {
            line += " " + word;
        } else {
            lines.push_back(line);
            line = word;
        }
    }
    if (!line.empty()) {
        lines.push_back(line);
    }
    return lines;
}

std::vector<std::string> credits_lines(const std::string& markdown) {
    std::vector<std::string> out;
    std::istringstream in(markdown);
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        std::string s = trim_left(line);
        if (!s.empty() && s[0] == '#') {              // heading marks
            s = trim_left(s.substr(s.find_first_not_of('#')));
        } else if (s.size() >= 2 && (s[0] == '-' || s[0] == '*') && s[1] == ' ') {   // list markers
            s = trim_left(s.substr(2));
        }
        std::string clean;                            // bold stars
        for (std::size_t i = 0; i < s.size(); ++i) {
            if (s[i] == '*' && i + 1 < s.size() && s[i + 1] == '*') {
                ++i;
                continue;
            }
            clean.push_back(s[i]);
        }
        out.push_back(clean);
    }
    return out;
}

std::string glyph_fallback_label(const std::string& glyph_name) {
    const auto cut = glyph_name.find('_');
    std::string name = cut == std::string::npos ? glyph_name : glyph_name.substr(cut + 1);
    std::replace(name.begin(), name.end(), '_', ' ');
    if (!name.empty()) {
        name[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(name[0])));
    }
    return name;
}

// ---- The pseudo-locale layout check (#275) ------------------------------------------------------------------
std::string label_problem(const DrawnLabel& label, double screen_w, double screen_h, bool pseudo) {
    constexpr double kSlack = 0.5;   // rounding of design pixels
    if (!label.fits) {
        return label.why.empty() ? "cut off" : label.why;
    }
    if (label.x < -kSlack || label.y < -kSlack || label.x + label.w > screen_w + kSlack ||
        label.y + label.h > screen_h + kSlack) {
        return "past the screen edge";
    }
    if (pseudo && !label.raw && !label.text.empty() && label.text.front() != '[') {
        return "not through t() (untranslated)";
    }
    return "";
}

// ---- Keeping track (#167) -----------------------------------------------------------------------------------
void LineHistory::record(const std::string& name, const std::string& text) {
    entries_.push_back({name, text});
    while (entries_.size() > kMax) {
        entries_.pop_front();
    }
}

std::vector<std::string> help_lines(const std::function<std::string(const std::string&, const TrArgs&)>& tr,
                                    const std::string& objective, const LineHistory& history,
                                    const std::vector<std::pair<std::string, std::string>>& controls) {
    std::vector<std::string> lines;
    lines.push_back(objective.empty() ? tr("help.no_objective", {}) : tr("help.objective", {{"text", objective}}));
    if (const HistoryEntry* last = history.last()) {
        lines.push_back(tr("help.last_line", {{"name", last->name}, {"text", last->text}}));
    }
    lines.push_back(tr("help.controls", {}));
    for (const auto& [action, label] : controls) {
        lines.push_back(tr("action." + action, {}) + ": " + label);
    }
    return lines;
}

// ---- Hands and timing (#166) --------------------------------------------------------------------------------
bool AutoRepeat::update(double dt, bool held) {
    if (!held) {
        held_ = 0.0;
        next_ = kDelay;
        return false;
    }
    held_ += dt;
    if (held_ >= next_) {
        next_ += kInterval;
        return true;
    }
    return false;
}

// ---- Colour (#169) ------------------------------------------------------------------------------------------
std::optional<std::string> palette_colour(const json& colours, const std::string& mode, const std::string& name) {
    if (!colours.is_object() || !colours.contains("palettes") || !colours["palettes"].is_object()) {
        return std::nullopt;
    }
    const json& palettes = colours["palettes"];
    for (const std::string& m : {mode, std::string("none")}) {
        if (palettes.contains(m) && palettes[m].is_object() && palettes[m].contains(name) &&
            palettes[m][name].is_string()) {
            return palettes[m][name].get<std::string>();
        }
    }
    return std::nullopt;
}

// ---- Subtitles ----------------------------------------------------------------------------------------------
std::vector<SubtitleLine> subtitle_lines_from_json(const json& built) {
    std::vector<SubtitleLine> out;
    if (!built.is_object() || !built.contains("lines") || !built["lines"].is_object()) {
        return out;
    }
    for (const auto& [id, row] : built["lines"].items()) {
        if (!row.is_object()) {
            continue;
        }
        SubtitleLine line;
        line.id = id;
        if (row.contains("name") && row["name"].is_string()) line.name = row["name"].get<std::string>();
        if (row.contains("text") && row["text"].is_string()) line.text = row["text"].get<std::string>();
        if (row.contains("kind") && row["kind"].is_string()) line.kind = row["kind"].get<std::string>();
        if (row.contains("duration_s") && row["duration_s"].is_number()) line.duration_s = row["duration_s"].get<double>();
        if (row.contains("cooldown_s") && row["cooldown_s"].is_number()) line.cooldown_s = row["cooldown_s"].get<double>();
        out.push_back(line);
    }
    return out;
}

const SubtitleLine* find_line(const std::vector<SubtitleLine>& lines, const std::string& id) {
    for (const SubtitleLine& l : lines) {
        if (l.id == id) {
            return &l;
        }
    }
    return nullptr;
}

bool subtitle_allowed(const SubtitleLine& line, const json& settings) {
    const json* access = settings.is_object() && settings.contains("access") ? &settings["access"] : nullptr;
    auto flag = [access](const char* key, bool fallback) {
        return access && access->contains(key) && (*access)[key].is_boolean() ? (*access)[key].get<bool>() : fallback;
    };
    if (!flag("subtitles", true)) {
        return false;
    }
    return line.kind != "bark" || flag("subtitle_barks", false);
}

bool SubtitleTrack::play(const SubtitleLine& line, double now) {
    const auto last = last_played_.find(line.id);
    if (last != last_played_.end() && line.cooldown_s > 0.0 && now - last->second < line.cooldown_s) {
        return false;
    }
    last_played_[line.id] = now;
    current_ = line;
    t_ = 0.0;
    holding_ = false;
    return true;
}

void SubtitleTrack::update(double dt, bool hold) {
    if (!current_) {
        return;
    }
    t_ += dt;
    if (t_ >= current_->duration_s) {
        if (hold) {
            holding_ = true;              // stays until dismiss()
        } else {
            current_.reset();
            holding_ = false;
        }
    }
}

void SubtitleTrack::dismiss() {
    current_.reset();
    holding_ = false;
}

// ---- Scripted runs (#276) -----------------------------------------------------------------------------------
bool admits_device_event(ShellDeviceEvent kind, bool scripted) {
    switch (kind) {
        case ShellDeviceEvent::Key:
        case ShellDeviceEvent::MouseButton:
        case ShellDeviceEvent::MouseMotion:
        case ShellDeviceEvent::PadButton:
        case ShellDeviceEvent::PadAxis:
            return !scripted;   // the player's input: only outside a drive
        case ShellDeviceEvent::PadAdded:
        case ShellDeviceEvent::PadRemoved:
        case ShellDeviceEvent::Quit:
        case ShellDeviceEvent::FocusLost:
        case ShellDeviceEvent::Other:
            break;
    }
    return true;
}

}  // namespace core

// {{FOOTER}}
