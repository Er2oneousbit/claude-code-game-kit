// ---------------------------------------------------------------------------
// ShellLogic.hpp
// Purpose : The rest of the shell's logic that needs no SDL: SDL's key and button names as the kit's binding
//           strings, which actions a binding triggers, text wrapping for a fixed-width font, CREDITS.md as plain
//           lines, the dialogue history and "What now?" page (#167), hold-to-mash (#166), the colour-blind palettes
//           (#169) and the subtitle track with subtitle_hold (#167). src/shell uses it with real events; the tests
//           in tests/test_menu.cpp check it.
// Usage   : core::key_binding("Left Shift") == "key:shift";  core::pad_binding("dpup") == "pad:dpad_up"
//           core::wrap_chars("Hit the box to feel the juice.", 12) -> {"Hit the box", "to feel the", "juice."}
//           core::SubtitleTrack track; track.play(line, settings, now); track.update(dt, hold); track.holding()
// Notes   : Key names are SDL_GetKeyName()'s, lowercased with spaces removed, then the kit's aliases ("Return" is
//           key:enter, either Shift is key:shift). Pad names are SDL_GetGamepadStringForButton()'s ("a" is
//           pad:south: positional names, see Bindings.hpp). The pad brand comes from the gamepad's name, a
//           heuristic (verify with your controllers). The hold-to-mash times are the kit's starting point (a tip).
//
// Pseudocode:
//   actions_for(bindings, binding): every action (sorted) whose slots hold binding
//   wrap_chars: words joined while the line stays within max_chars; a word longer than that is cut
//   SubtitleTrack::update: t += dt; past duration -> holding when hold is on and not dismissed, else gone
//   AutoRepeat::update(dt, held): held for DELAY, then true every INTERVAL
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include <cstddef>
#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/Bindings.hpp"
#include "core/I18n.hpp"

namespace core {

// ---- Input names --------------------------------------------------------------------------------------------
// "key:<name>" for an SDL key name ("Return" -> key:enter, "Left Shift" -> key:shift, "A" -> key:a).
std::string key_binding(const std::string& sdl_key_name);
// "pad:<name>" for an SDL gamepad button string ("a" -> pad:south, "dpup" -> pad:dpad_up, "back" -> pad:select).
std::string pad_binding(const std::string& sdl_button_name);
// "pad_xbox" | "pad_playstation" | "pad_other" from a gamepad's name.
std::string device_of_pad(const std::string& name);
// Every action (sorted) that binding triggers.
std::vector<std::string> actions_for(const Bindings& bindings, const std::string& binding);
// The first binding of action that starts with prefix ("key:" or "pad:"), or "".
std::string binding_with_prefix(const Bindings& bindings, const std::string& action, const std::string& prefix);

// ---- Text ---------------------------------------------------------------------------------------------------
// Word-wrapped lines for a fixed-width font that fits max_chars per line (a longer word is cut).
std::vector<std::string> wrap_chars(const std::string& text, std::size_t max_chars);
// CREDITS.md as plain lines: heading marks, list markers and bold stars stripped.
std::vector<std::string> credits_lines(const std::string& markdown);
// "key_space" -> "Space", "xbox_a" -> "A", "pad_dpad_up" -> "Dpad up" (the glyph table's own text wins in the shell)
std::string glyph_fallback_label(const std::string& glyph_name);

// ---- Keeping track (#167) -----------------------------------------------------------------------------------
struct HistoryEntry {
    std::string name;
    std::string text;
};

class LineHistory {
public:
    static constexpr std::size_t kMax = 50;   // lines the dialogue history keeps
    void record(const std::string& name, const std::string& text);
    const std::deque<HistoryEntry>& entries() const { return entries_; }
    const HistoryEntry* last() const { return entries_.empty() ? nullptr : &entries_.back(); }
    bool empty() const { return entries_.empty(); }

private:
    std::deque<HistoryEntry> entries_;
};

// The "What now?" page: the goal (or that none is set), the last line said, then the controls.
std::vector<std::string> help_lines(const std::function<std::string(const std::string&, const TrArgs&)>& tr,
                                    const std::string& objective, const LineHistory& history,
                                    const std::vector<std::pair<std::string, std::string>>& controls);

// ---- Hands and timing (#166) --------------------------------------------------------------------------------
// "Hold to mash": a held button repeats its press after kDelay, then every kInterval while held.
class AutoRepeat {
public:
    static constexpr double kDelay = 0.35;
    static constexpr double kInterval = 0.15;
    // Call every frame with whether the button is held; true on a frame that repeats the press.
    bool update(double dt, bool held);

private:
    double held_ = 0.0;
    double next_ = kDelay;
};

// ---- Colour (#169) ------------------------------------------------------------------------------------------
// The "#rrggbb" of colours.json's palettes[mode][name], falling back to the "none" palette; nullopt when neither
// has it.
std::optional<std::string> palette_colour(const nlohmann::json& colours, const std::string& mode,
                                          const std::string& name);

// ---- Subtitles ----------------------------------------------------------------------------------------------
struct SubtitleLine {
    std::string id;
    std::string name;         // the speaker as shown
    std::string text;
    std::string kind = "line";   // "line" or "bark"
    double duration_s = 3.0;
    double cooldown_s = 0.0;
};

// data/dialogue/*.built.json "lines" -> SubtitleLine per id (fields it lacks take the defaults above).
std::vector<SubtitleLine> subtitle_lines_from_json(const nlohmann::json& built);
const SubtitleLine* find_line(const std::vector<SubtitleLine>& lines, const std::string& id);
// Subtitles on, and barks only with subtitle_barks.
bool subtitle_allowed(const SubtitleLine& line, const nlohmann::json& settings);

class SubtitleTrack {
public:
    // Starts a line at time now (seconds): false when its cooldown refuses it. Replaces whatever plays.
    bool play(const SubtitleLine& line, double now);
    // hold: access.subtitle_hold. A finished line stays (holding) until dismiss() with hold on.
    void update(double dt, bool hold);
    void dismiss();
    const SubtitleLine* current() const { return current_ ? &*current_ : nullptr; }
    double elapsed() const { return t_; }
    bool holding() const { return holding_; }

private:
    std::optional<SubtitleLine> current_;
    double t_ = 0.0;
    bool holding_ = false;
    std::map<std::string, double> last_played_;
};

}  // namespace core

// {{FOOTER}}
