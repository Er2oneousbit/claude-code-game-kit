// ---------------------------------------------------------------------------
// Menu.hpp
// Purpose : The shell's menu logic with no SDL in it: a list of rows (button, toggle, slider, choice, binding) with
//           keyboard and gamepad focus, and the settings menu (tabs Display, Audio, Controls, Accessibility,
//           Language) built from the settings JSON, so every row reads and writes the same fields the settings
//           schema (Settings.hpp) validates. src/shell draws it; tests/test_menu.cpp checks it.
// Usage   : core::MenuList list({core::button_row("play", [] { return "Play"; }, start)});
//           list.action("ui_down"); list.focused_id();
//           core::SettingsMenu menu(settings, hooks); menu.action("ui_right"); menu.focus_id()  // "tabs.audio"
// Notes   : Actions are the shell's ui_* names (ui_up, ui_down, ui_left, ui_right, ui_accept, ui_cancel). Focus
//           wraps around and skips disabled rows. A slider rounds to its step and to six decimals (no float dust in
//           settings.json). A choice wraps around; accept steps it forward. The settings menu starts with focus on
//           the tab bar: left and right switch tabs, down or accept enters the rows, up from the first row goes
//           back to the tabs. ui_* actions are not rebindable (Bindings.hpp has the groups). Matches what the kit's
//           other shells do (Godot, LÖVE, web), not their code.
//
// Pseudocode:
//   MenuList::action(name): up/down -> move (wrap, skip disabled) ; left/right/accept -> the row's callback
//   SettingsMenu: per tab a MenuList of rows bound to settings[section][field], each change -> hooks.changed(section)
//     controls tab: a binding row per game action (left/right pick the keyboard or pad cell, accept asks the shell
//     to capture a press), glyphs, deadzone, invert_y, reset, the one-handed presets, back
//   apply_preset(settings, presets, name): the defaults, then every action of the preset as [keyboard, pad]
//   display tab (#308): its rows read and stage through core::DisplayStaging; Apply writes the changed fields,
//     applies and saves; a mode or resolution change opens the keep-or-revert confirm, tick(real_dt) counts it
//     down; Back (row or ui_cancel, any tab) goes through DisplayStaging::back (revert, warn once, or leave)
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the Display tab's Apply button and its keep-or-revert
//           confirm (core::DisplayStaging, #308)
// ---------------------------------------------------------------------------
#pragma once

#include <array>
#include <cstddef>
#include <functional>
#include <map>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/DisplayStaging.hpp"
#include "core/I18n.hpp"

namespace core {

enum class RowKind { Button, Toggle, Slider, Choice, Binding };

// One menu row. Labels and values are functions, so a language change shows at once and the narration (#165)
// can ask what a row says right now.
struct Row {
    std::string id;
    RowKind kind = RowKind::Button;
    std::function<std::string()> label;      // the text on the left (or the button's text)
    std::function<std::string()> value;      // the value text on the right ("" for buttons)
    std::function<void()> left;              // ui_left (empty: not used)
    std::function<void()> right;             // ui_right
    std::function<void()> accept;            // ui_accept
    std::function<bool()> enabled;           // empty = enabled; a disabled row is skipped by focus
    std::function<double()> fraction;        // sliders: 0..1 of the range, for the bar
    int cell = 0;                            // binding rows: 0 = keyboard, 1 = gamepad

    bool is_enabled() const { return !enabled || enabled(); }
};

// The role word the narration uses for a row kind: "button", "toggle", "slider", "choice" (keys narrate.*).
const char* narration_role_key(RowKind kind);

// A vertical list with one focused row. Rows are indexed from 0.
class MenuList {
public:
    MenuList() = default;
    explicit MenuList(std::vector<Row> rows);

    std::vector<Row> rows;
    std::size_t index = 0;     // the focused row
    std::size_t top = 0;       // the first visible row when the list scrolls (the drawing side keeps it current)
    std::function<void()> on_move;   // called after focus moved (a blip sound)

    bool empty() const { return rows.empty(); }
    const Row* focused() const;
    Row* focused();
    std::string focused_id() const;      // "" with no rows
    bool focus(const std::string& id);   // true when a row has that id
    void move(int delta);                // wraps, skips disabled rows
    void fix_focus(int dir);             // if the focused row is disabled, step until one is not
    bool action(const std::string& name);   // true when the action was used

    // The first visible row and how many fit, given how many rows fit on screen (updates `top`).
    std::pair<std::size_t, std::size_t> window(std::size_t max_rows);
};

// ---- Row builders ------------------------------------------------------------------------------------------
using Label = std::function<std::string()>;
using Getter = std::function<nlohmann::json()>;
using Setter = std::function<void(const nlohmann::json&)>;
using ValueText = std::function<std::string(const nlohmann::json&)>;

Row button_row(const std::string& id, Label label, std::function<void()> accept);
Row toggle_row(const std::string& id, Label label, Getter get, Setter set, ValueText on_off);
Row slider_row(const std::string& id, Label label, Getter get, Setter set, double lo, double hi, double step,
               ValueText format);
Row choice_row(const std::string& id, Label label, std::function<std::vector<nlohmann::json>()> options, Getter get,
               Setter set, ValueText show);

// A slider value moved one step up or down, rounded to the step and to six decimals, clamped to [lo, hi].
double nudge(double value, double lo, double hi, double step, int dir);

// The press that moves a slider from `now` towards `target`: "ui_left", "ui_right", or "" once it is there.
std::string slide_action(double now, double target);

// ---- The settings menu -------------------------------------------------------------------------------------
struct SettingsHooks {
    std::function<std::string(const std::string& key, const TrArgs& args)> tr;   // string tables
    std::function<void(const std::string& section)> changed;                     // a value changed (apply it)
    std::function<void(const std::string& action, std::size_t slot)> capture;    // "press a key" for a binding
    std::function<void(const std::string& text)> say;                            // a message for the hint line
    std::function<std::vector<std::string>()> locales;                           // the language choices
    std::function<std::string(const std::string& locale)> locale_name;           // "English" for "en"
    std::function<std::string(const std::string& binding, std::size_t slot)> binding_label;  // "Space", "A"
    std::function<void()> close;                                                 // Back: save and leave
    std::function<void()> save;                  // Apply and its revert write settings.json (#308)
    nlohmann::json presets;                      // data/input/presets.json (null: no preset rows)
    bool debug_build = false;                    // adds the pseudo locale to the language choices
};

class SettingsMenu {
public:
    static constexpr std::array<const char*, 5> kTabs = {"display", "audio", "controls", "access", "language"};
    static constexpr std::array<const char*, 2> kPresetNames = {"one_hand_left", "one_hand_right"};
    static constexpr std::array<const char*, 8> kGameActions = {"move_left", "move_right", "move_up", "move_down",
                                                                "jump", "attack", "interact", "pause"};

    SettingsMenu(nlohmann::json& settings, SettingsHooks hooks);
    SettingsMenu(const SettingsMenu&) = delete;              // rows hold callbacks into this object
    SettingsMenu& operator=(const SettingsMenu&) = delete;

    std::string tab = "display";
    bool on_tabs = true;                 // focus on the tab bar, else on the rows
    bool dirty = false;                  // something changed since the menu opened

    MenuList& list() { return lists_.at(tab); }
    const MenuList& list() const { return lists_.at(tab); }
    const std::map<std::string, MenuList>& lists() const { return lists_; }

    bool action(const std::string& name);   // the shell's ui_* actions; true when used
    void switch_tab(int delta);
    void open_tab(const std::string& name, const std::string& focus_row = "");
    std::string focus_id() const;           // "tabs.<tab>", "<tab>.<row id>" or "confirm.<keep|revert>"

    // ---- The Display tab's Apply (#308) ----
    const DisplayStaging& staging() const { return staging_; }
    bool confirming() const { return staging_.confirming(); }
    MenuList& confirm_list() { return confirm_; }       // Keep, Revert: the shell draws it over the screen
    const MenuList& confirm_list() const { return confirm_; }
    // Applies the staged Display changes: true when it opened the confirm.
    bool apply_display();
    // The confirm's countdown, in REAL seconds (not game time, not paused): it reverts when it runs out.
    void tick(double real_dt);
    void keep_display();
    void revert_display();
    // Back from any tab: during the confirm reverts, with unapplied Display changes warns once, else closes.
    void back();

    // Puts a one-handed layout from hooks.presets into settings.input.bindings. False when there is no such preset.
    bool apply_preset(const std::string& name);
    void reset_bindings();

private:
    nlohmann::json& s_;
    SettingsHooks hooks_;
    std::map<std::string, MenuList> lists_;
    DisplayStaging staging_;
    MenuList confirm_;

    void set_display(const DisplayStaging::Calls& calls);   // writes calls into settings.display, applies, saves

    std::string t(const std::string& key, const TrArgs& args = {}) const;
    Row field(const std::string& section, const std::string& name, RowKind kind,
              const std::vector<nlohmann::json>& options = {}, double lo = 0, double hi = 1, double step = 0.1);
    Row back_row();
    Row binding_row(const std::string& action);
    std::vector<Row> display_rows();
    std::vector<Row> audio_rows();
    std::vector<Row> controls_rows();
    std::vector<Row> access_rows();
    std::vector<Row> language_rows();
    void changed(const std::string& section);
};

// settings.input.bindings = the defaults, then every action of presets["presets"][name]["bindings"] as
// [keyboard, pad]. False (settings untouched) when the preset is missing or malformed.
bool apply_preset(nlohmann::json& settings, const nlohmann::json& presets, const std::string& name);

}  // namespace core

// {{FOOTER}}
