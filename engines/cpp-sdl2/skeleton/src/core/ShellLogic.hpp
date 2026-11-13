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
//   label_problem: cut off -> its reason; outside the screen -> "past the screen edge"; pseudo, not raw and no
//     leading "[" -> untranslated
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the pseudo-locale layout check (#275)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): admits_device_event, no real input in a drive (#276)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): DeviceEvent is ShellDeviceEvent, leaving the
//           generic name to games
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
// CREDITS.md without HTML comments (tools/credits.py writes one, #279): one line or many, an unclosed one runs to the
// end; a comment-only line goes, with one blank line after it when a blank line came before. CRLF -> LF.
// tools/golden_vectors.py strip_html_comments is the spec, data/golden/credits.json the cases.
std::string strip_html_comments(const std::string& text);
// CREDITS.md as every engine's credits screen shows it (#284): HTML comments out, then per line a heading's marks
// ('#' then a space, tab or the line end) or a list marker ('-', '*', '+' then a space or tab), every '*', and the
// spaces and tabs at both ends; blank lines at the start and the end go. "" when nothing is left. Byte-wise (the
// marks are ASCII). tools/golden_vectors.py credits_text is the spec, data/golden/credits.json the cases.
std::string credits_text(const std::string& markdown);
// credits_text split into lines. Empty when nothing is left (the screen shows its placeholder then).
std::vector<std::string> credits_lines(const std::string& markdown);
// "key_space" -> "Space", "xbox_a" -> "A", "pad_dpad_up" -> "Dpad up" (the glyph table's own text wins in the shell)
std::string glyph_fallback_label(const std::string& glyph_name);

// ---- The pseudo-locale layout check (#275) ------------------------------------------------------------------
// One label as drawn: its text, whether it fit its box (and why not), its ink box in design pixels, and raw = not
// UI copy (a key name, CREDITS.md, an arrow), which is exempt from the "went through t()" rule.
struct DrawnLabel {
    std::string id;
    std::string text;
    bool fits = true;
    std::string why;
    double x = 0, y = 0, w = 0, h = 0;
    bool raw = false;
};
// What is wrong with a label ("" = nothing): cut off, past the screen edge, or (pseudo) not starting with "[".
std::string label_problem(const DrawnLabel& label, double screen_w, double screen_h, bool pseudo);

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

// ---- Scripted runs (#276) -----------------------------------------------------------------------------------
// The kinds of SDL event the shell handles, without SDL (Shell.cpp sorts SDL's event types into these). Named
// for the shell: a game's own core::DeviceEvent (an input recorder, a replay) must still compile.
enum class ShellDeviceEvent {
    Key, MouseButton, MouseMotion, PadButton, PadAxis, PadAdded, PadRemoved, Quit, FocusLost, Other
};
// Does a device event reach the shell? In normal play every one. In a scripted run (a smoke run: every one follows
// a drive) none of the player's input (keys, mouse, pad buttons and axes): a stray key or a virtual pad on a shared
// machine must not break the tour, so only the drive's own presses count. The window's events and pads being
// plugged in or out still do.
bool admits_device_event(ShellDeviceEvent kind, bool scripted);

}  // namespace core

// {{FOOTER}}
