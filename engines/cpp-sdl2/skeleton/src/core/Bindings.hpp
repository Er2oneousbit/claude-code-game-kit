// ---------------------------------------------------------------------------
// Bindings.hpp
// Purpose : Input bindings as data: the default action map, rebinding with conflict swaps, and which
//           button-prompt art to show (keyboard, Xbox, PlayStation, generic pad). Plain C++, no SDL.
// Usage   : core::Bindings b = core::bindings_from_json(settings["input"]["bindings"]);
//           if (auto r = core::rebind(b, "jump", core::kKeyboardSlot, "key:k")) b = r->bindings;
//           const std::string set = core::glyph_set(settings["input"]["glyphs"].get<std::string>(), last_device);
//           const std::string art = core::glyph_name(set, core::prompt_binding(b, "jump", set));  // "xbox_a"
// Notes   : A binding is "<kind>:<name>": key:space, mouse:left, pad:south (the bottom face button),
//           pad_axis:leftx- ; "" is an unbound slot. Slot 0 is keyboard and mouse, slot 1 the gamepad.
//           The SDL side (src/game) turns SDL key and button events into these strings; this file never
//           sees SDL. Actions starting with "ui_" form one conflict group (menus), the rest another (play),
//           so Escape can be both ui_cancel and pause. Matches tools/golden_vectors.py (rebind, glyph_set,
//           glyph_name, prompt_binding), checked against data/golden/shell.json.
//
// Pseudocode:
//   rebind(b, action, slot, binding):
//     old = b[action][slot] (or "" for a new slot); slot past the end -> nullopt
//     conflicts = every (other, s) in the same group holding binding, sorted by action then slot
//     b[action][slot] = binding ; every conflict gets old (a swap, or "" = unbound)
//   glyph_set(setting, device): the setting, or for "auto" the last device's family
//   glyph_name(set, binding)  : key_x, mouse_x, or the pad button in the set's names (xbox_a, ps_cross, pad_south)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <array>
#include <cstddef>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

// action -> bindings by slot ("" = unbound). std::map keeps actions sorted, which rebind's conflict order needs.
using Bindings = std::map<std::string, std::vector<std::string>>;

// ---- Constants ----
constexpr std::size_t kKeyboardSlot = 0;   // keyboard and mouse
constexpr std::size_t kPadSlot = 1;        // gamepad
constexpr std::string_view kUiPrefix = "ui_";
// Settings values for input.glyphs; "auto" follows the last device used
constexpr std::array<std::string_view, 5> kGlyphSets = {"auto", "keyboard", "xbox", "playstation", "generic"};

// The built-in action map (the "defaults" of settings input.bindings).
const Bindings& default_bindings();

struct RebindResult {
    Bindings bindings;
    std::vector<std::pair<std::string, std::size_t>> conflicts;  // (action, slot) that gave the binding up
};

// Puts binding into action's slot (slot == size appends a slot). Another action of the same group that used it
// gets this slot's old binding (a swap) or "" when there was none. nullopt when slot is past the end.
std::optional<RebindResult> rebind(const Bindings& bindings, const std::string& action, std::size_t slot,
                                   const std::string& binding);

// "ui" for ui_* actions, "game" for the rest.
std::string group_of(const std::string& action);

// Which prompt art to show: the player's setting, or for "auto" the last device ("keyboard", "mouse",
// "pad_xbox", "pad_playstation", anything else = "generic").
std::string glyph_set(const std::string& setting, const std::string& last_device);

// The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick, "unknown".
std::string glyph_name(const std::string& gset, const std::string& binding);

// The binding to show for action: slot 0 for the keyboard set, slot 1 otherwise; "" when there is none.
std::string prompt_binding(const Bindings& bindings, const std::string& action, const std::string& gset);

// From settings["input"]["bindings"] (an object of string arrays); anything else in it is skipped.
Bindings bindings_from_json(const nlohmann::json& j);
nlohmann::json bindings_to_json(const Bindings& bindings);

// What the narration says for one control (#165): "Music volume, slider, 70 percent"; no label says "unlabelled".
std::string narration_line(const std::string& label, const std::string& role, const std::string& value = "");

}  // namespace core

// {{FOOTER}}
