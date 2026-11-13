// ---------------------------------------------------------------------------
// test_menu.cpp
// Purpose : Tests the shell's SDL-free logic: the menu list (focus, wrap, disabled rows), the row builders (slider
//           steps, choice wrap, toggles), the settings menu over the settings JSON (tabs, every schema field has a
//           row, rebinding capture, the one-handed presets), and the helpers (key names, wrapping, credits, the
//           dialogue history, hold-to-mash, palettes, subtitle hold), and which device events a drive's run takes
//           (#276).
// Usage   : python tools/dev.py test     (ctest lists one test per TEST_CASE)
// Notes   : No SDL: the rows are driven with the ui_* action names a player's key or button turns into.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): credits lines follow the shared rule (#284)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/Bindings.hpp"
#include "core/Menu.hpp"
#include "core/Settings.hpp"
#include "core/ShellLogic.hpp"

using nlohmann::json;

namespace {

core::Label text(const char* s) {
    return [s] { return std::string(s); };
}

// A settings menu with plain hooks: tr returns the key, so labels are checkable; captures are recorded.
struct Harness {
    json settings = core::default_settings();
    std::vector<std::string> changed;
    std::vector<std::string> captured;
    std::vector<std::string> said;
    bool closed = false;
    core::SettingsHooks hooks;

    Harness() {
        hooks.tr = [](const std::string& key, const core::TrArgs& args) {
            std::string out = key;
            for (const auto& [k, v] : args) out += " " + k + "=" + v;
            return out;
        };
        hooks.changed = [this](const std::string& section) { changed.push_back(section); };
        hooks.capture = [this](const std::string& action, std::size_t slot) {
            captured.push_back(action + ":" + std::to_string(slot));
        };
        hooks.say = [this](const std::string& t) { said.push_back(t); };
        hooks.locales = [] { return std::vector<std::string>{"en", "fr"}; };
        hooks.binding_label = [](const std::string& b, std::size_t) { return b; };
        hooks.close = [this] { closed = true; };
        hooks.presets = json::parse(R"({"presets": {"one_hand_left": {"bindings": {
            "ui_accept": ["key:space", "pad:l1"], "attack": ["key:f", "pad:l2"], "jump": ["key:space", "pad:l1"]}},
            "one_hand_right": {"bindings": {"attack": ["key:u", "pad:r2"]}}}})");
    }
};

}  // namespace

// ---- MenuList ----------------------------------------------------------------------------------------------
TEST_CASE("menu focus wraps around and skips disabled rows") {
    int pressed = 0;
    core::Row off = core::button_row("off", text("Off"), [] {});
    off.enabled = [] { return false; };
    core::MenuList list({core::button_row("a", text("A"), [&] { ++pressed; }), off,
                         core::button_row("c", text("C"), [] {})});
    CHECK(list.focused_id() == "a");
    CHECK(list.action("ui_down"));
    CHECK(list.focused_id() == "c");           // b is disabled
    CHECK(list.action("ui_down"));
    CHECK(list.focused_id() == "a");           // wrapped
    CHECK(list.action("ui_up"));
    CHECK(list.focused_id() == "c");
    list.focus("a");
    CHECK(list.action("ui_accept"));
    CHECK(pressed == 1);
    CHECK_FALSE(list.action("ui_left"));       // a button has no left
    CHECK_FALSE(list.focus("nope"));
}

TEST_CASE("an empty list takes actions without crashing") {
    core::MenuList list;
    CHECK(list.focused_id().empty());
    CHECK(list.action("ui_down"));
    CHECK_FALSE(list.action("ui_accept"));
    CHECK(list.window(5) == std::make_pair<std::size_t, std::size_t>(0, 0));
}

TEST_CASE("the list window scrolls to keep the focused row visible") {
    std::vector<core::Row> rows;
    for (int i = 0; i < 10; ++i) rows.push_back(core::button_row("r" + std::to_string(i), text("row"), [] {}));
    core::MenuList list(rows);
    CHECK(list.window(4) == std::make_pair<std::size_t, std::size_t>(0, 4));
    list.focus("r6");
    CHECK(list.window(4) == std::make_pair<std::size_t, std::size_t>(3, 4));   // rows 3..6
    list.focus("r1");
    CHECK(list.window(4) == std::make_pair<std::size_t, std::size_t>(1, 4));
    list.focus("r9");
    CHECK(list.window(4).first == 6);
    CHECK(list.window(20) == std::make_pair<std::size_t, std::size_t>(0, 10));
}

// ---- Row builders --------------------------------------------------------------------------------------------
TEST_CASE("a slider steps, rounds and clamps") {
    json v = 0.5;
    auto get = [&]() -> json { return v; };
    auto set = [&](const json& x) { v = x; };
    core::Row r = core::slider_row("s", text("S"), get, set, 0.0, 1.0, 0.1,
                                   [](const json& x) { return std::to_string(x.get<double>()); });
    r.right();
    CHECK(v.get<double>() == doctest::Approx(0.6));
    for (int i = 0; i < 10; ++i) r.right();
    CHECK(v.get<double>() == 1.0);             // clamped
    for (int i = 0; i < 20; ++i) r.left();
    CHECK(v.get<double>() == 0.0);
    CHECK(r.fraction() == 0.0);
    CHECK(core::nudge(0.1, 0.0, 1.0, 0.1, 1) == 0.2);    // no float dust: exactly 0.2 as a decimal
    CHECK(core::nudge(0.3, 0.0, 1.0, 0.1, -1) == doctest::Approx(0.2));
    CHECK(core::nudge(0.9, 0.0, 1.0, 0.1, 1) == 1.0);
    CHECK(core::slide_action(0.7, 0.5) == "ui_left");
    CHECK(core::slide_action(0.3, 0.5) == "ui_right");
    CHECK(core::slide_action(0.5, 0.5).empty());
}

TEST_CASE("a choice wraps both ways and accept steps forward") {
    json v = "normal";
    core::Row r = core::choice_row(
        "d", text("D"), [] { return std::vector<json>{"story", "easy", "normal", "hard"}; }, [&]() -> json { return v; },
        [&](const json& x) { v = x; }, [](const json& x) { return x.get<std::string>(); });
    r.right();
    CHECK(v == "hard");
    r.right();
    CHECK(v == "story");                       // wrapped
    r.left();
    CHECK(v == "hard");
    r.accept();
    CHECK(v == "story");
    CHECK(r.value() == "story");
}

TEST_CASE("a toggle flips on left, right and accept") {
    json v = false;
    core::Row r = core::toggle_row("t", text("T"), [&]() -> json { return v; }, [&](const json& x) { v = x; },
                                   [](const json& x) { return x.get<bool>() ? "On" : "Off"; });
    r.accept();
    CHECK(v == true);
    r.left();
    CHECK(v == false);
    r.right();
    CHECK(r.value() == "On");
}

// ---- SettingsMenu --------------------------------------------------------------------------------------------
TEST_CASE("the settings menu starts on the tabs and moves between them") {
    Harness h;
    core::SettingsMenu menu(h.settings, h.hooks);
    CHECK(menu.focus_id() == "tabs.display");
    CHECK(menu.action("ui_right"));
    CHECK(menu.focus_id() == "tabs.audio");
    CHECK(menu.action("ui_left"));
    CHECK(menu.action("ui_left"));
    CHECK(menu.focus_id() == "tabs.language");   // wrapped
    CHECK(menu.action("ui_down"));
    CHECK(menu.focus_id() == "language.language");
    CHECK(menu.action("ui_up"));                 // from the first row: back to the tabs
    CHECK(menu.focus_id() == "tabs.language");
    CHECK(menu.action("ui_cancel"));
    CHECK(h.closed);
}

TEST_CASE("every field of the settings schema has a row that changes it") {
    Harness h;
    core::SettingsMenu menu(h.settings, h.hooks);
    const json before = h.settings;
    // the sections with plain fields: each row's id is the field; stepping it changes the stored value
    const std::vector<std::pair<std::string, std::string>> tabs_sections = {
        {"display", "display"}, {"audio", "audio"}, {"access", "access"}};
    for (const auto& [tab, section] : tabs_sections) {
        menu.open_tab(tab);
        menu.action("ui_down");
        for (const auto& [field, value] : before[section].items()) {
            const std::string where = section + "." + field;
            REQUIRE_MESSAGE(menu.list().focus(field), where << " has no row");
            const json old = h.settings[section][field];
            menu.action("ui_right");
            if (h.settings[section][field] == old) {
                menu.action("ui_left");            // a slider already at its top end
            }
            CHECK_MESSAGE(h.settings[section][field] != old, where << " did not change");
            // every value the menu writes still passes the loader unchanged
            const core::SettingsLoad loaded = core::settings_load(h.settings.dump());
            CHECK_MESSAGE(loaded.problems.empty(), where << ": " << (loaded.problems.empty() ? "" : loaded.problems[0]));
        }
    }
    CHECK(h.changed.size() >= 25);
    // controls: glyphs, deadzone, invert_y; language: language, consent
    menu.open_tab("controls", "glyphs");
    menu.action("ui_right");
    CHECK(h.settings["input"]["glyphs"] == "keyboard");
    menu.list().focus("deadzone");
    menu.action("ui_right");
    CHECK(h.settings["input"]["deadzone"].get<double>() == doctest::Approx(0.25));
    menu.list().focus("invert_y");
    menu.action("ui_accept");
    CHECK(h.settings["input"]["invert_y"] == true);
    menu.open_tab("language", "language");
    menu.action("ui_right");
    CHECK(h.settings["language"] == "fr");
    menu.list().focus("consent");
    menu.action("ui_right");
    CHECK(h.settings["telemetry"]["consent"] == "yes");
    CHECK(menu.dirty);
}

TEST_CASE("display rows show resolutions and frame caps as choices") {
    Harness h;
    core::SettingsMenu menu(h.settings, h.hooks);
    menu.open_tab("display", "resolution");
    CHECK(menu.list().focused()->value() == "value.resolution h=1080 w=1920");   // args in key order
    menu.action("ui_right");
    CHECK(h.settings["display"]["resolution"] == json::array({2560, 1440}));
    menu.list().focus("frame_cap");
    CHECK(menu.list().focused()->value() == "opt.frame_cap.0");
    menu.action("ui_right");
    CHECK(h.settings["display"]["frame_cap"] == 30);
    CHECK(menu.list().focused()->value() == "value.fps n=30");
    menu.list().focus("ui_scale");
    CHECK(menu.list().focused()->value() == "value.times n=1");
    menu.open_tab("audio", "master");
    CHECK(menu.list().focused()->value() == "value.percent n=100");
}

TEST_CASE("controls rows rebind through the shell and reset to the defaults") {
    Harness h;
    core::SettingsMenu menu(h.settings, h.hooks);
    menu.open_tab("controls", "bind_jump");
    CHECK(menu.action("ui_accept"));
    CHECK(h.captured == std::vector<std::string>{"jump:0"});     // the keyboard cell
    CHECK(menu.action("ui_right"));                             // the gamepad cell
    CHECK(menu.action("ui_accept"));
    CHECK(h.captured.back() == "jump:1");
    CHECK(menu.list().focused()->value() == "key:space, pad:south");
    h.settings["input"]["bindings"]["jump"] = json::array({"key:k", "pad:south"});
    menu.list().focus("reset");
    CHECK(menu.action("ui_accept"));
    CHECK(h.settings["input"]["bindings"] == core::bindings_to_json(core::default_bindings()));
    CHECK(h.said == std::vector<std::string>{"controls.reset_done"});
    // every game action has a binding row
    for (const char* action : core::SettingsMenu::kGameActions) {
        CHECK(menu.list().focus(std::string("bind_") + action));
    }
}

TEST_CASE("the one-handed presets apply from Settings > Controls (#166)") {
    Harness h;
    core::SettingsMenu menu(h.settings, h.hooks);
    menu.open_tab("controls", "preset_one_hand_left");
    CHECK(menu.action("ui_accept"));
    CHECK(h.settings["input"]["bindings"]["attack"] == json::array({"key:f", "pad:l2"}));
    CHECK(h.settings["input"]["bindings"]["move_left"] == json::array({"key:a", "pad:dpad_left"}));   // the default
    CHECK(h.said.back() == "controls.preset_done");
    CHECK(menu.list().focus("preset_one_hand_right"));
    // the free function: a missing preset or a malformed one leaves settings alone
    json s = core::default_settings();
    CHECK_FALSE(core::apply_preset(s, h.hooks.presets, "two_hands"));
    CHECK_FALSE(core::apply_preset(s, json::parse(R"({"presets": {"x": {"bindings": {"jump": ["key:k"]}}}})"), "x"));
    CHECK(s == core::default_settings());
    CHECK_FALSE(core::apply_preset(s, json(), "one_hand_left"));
    // no presets file: no preset rows
    h.hooks.presets = json();
    core::SettingsMenu bare(h.settings, h.hooks);
    bare.open_tab("controls");
    CHECK_FALSE(bare.list().focus("preset_one_hand_left"));
}

TEST_CASE("narration describes a row by label, role and value (#165)") {
    Harness h;
    core::SettingsMenu menu(h.settings, h.hooks);
    menu.open_tab("audio", "music");
    const core::Row* row = menu.list().focused();
    const std::string line = core::narration_line(row->label(), core::narration_role_key(row->kind), row->value());
    CHECK(line == "settings.audio.music, narrate.slider, value.percent n=80");
    CHECK(std::string(core::narration_role_key(core::RowKind::Binding)) == "narrate.button");
}

// ---- ShellLogic ----------------------------------------------------------------------------------------------
TEST_CASE("SDL key and button names become the kit's bindings") {
    CHECK(core::key_binding("Return") == "key:enter");
    CHECK(core::key_binding("Keypad Enter") == "key:enter");
    CHECK(core::key_binding("Left Shift") == "key:shift");
    CHECK(core::key_binding("Right Shift") == "key:shift");
    CHECK(core::key_binding("Escape") == "key:escape");
    CHECK(core::key_binding("Space") == "key:space");
    CHECK(core::key_binding("A") == "key:a");
    CHECK(core::key_binding("Up") == "key:up");
    CHECK(core::pad_binding("a") == "pad:south");
    CHECK(core::pad_binding("dpup") == "pad:dpad_up");
    CHECK(core::pad_binding("back") == "pad:select");
    CHECK(core::pad_binding("leftshoulder") == "pad:l1");
    CHECK(core::pad_binding("misc1") == "pad:misc1");
    CHECK(core::device_of_pad("Xbox Wireless Controller") == "pad_xbox");
    CHECK(core::device_of_pad("DualSense Wireless Controller") == "pad_playstation");
    CHECK(core::device_of_pad("PS5 Controller") == "pad_playstation");
    CHECK(core::device_of_pad("Wireless Controller") == "pad_playstation");
    CHECK(core::device_of_pad("Some Pad") == "pad_other");
    const core::Bindings& d = core::default_bindings();
    CHECK(core::actions_for(d, "key:escape") == std::vector<std::string>{"pause", "ui_cancel"});
    CHECK(core::actions_for(d, "key:zzz").empty());
    CHECK(core::binding_with_prefix(d, "jump", "pad:") == "pad:south");
    CHECK(core::binding_with_prefix(d, "jump", "mouse:").empty());
}

TEST_CASE("fixed-width wrapping keeps words whole and cuts the ones too long") {
    CHECK(core::wrap_chars("Hit the box to feel the juice.", 12) ==
          std::vector<std::string>{"Hit the box", "to feel the", "juice."});
    CHECK(core::wrap_chars("", 10).empty());
    CHECK(core::wrap_chars("abcdefghij", 4) == std::vector<std::string>{"abcd", "efgh", "ij"});
    CHECK(core::wrap_chars("a b", 0) == std::vector<std::string>{"a", "b"});
}

TEST_CASE("CREDITS.md loses its markdown marks") {
    const auto lines = core::credits_lines("# Credits\r\n\n- **Art**: someone\n* Music by x\n  ## Thanks\n#\n+ y_z\n");
    CHECK(lines == std::vector<std::string>{"Credits", "", "Art: someone", "Music by x", "Thanks", "", "y_z"});
    CHECK(core::glyph_fallback_label("key_space") == "Space");
    CHECK(core::glyph_fallback_label("pad_dpad_up") == "Dpad up");
    CHECK(core::glyph_fallback_label("xbox_a") == "A");
}

TEST_CASE("CREDITS.md from tools/credits.py shows no HTML comment (#279)") {
    const std::string md = "# Credits\r\n\r\n<!-- Generated by tools/credits.py from docs/ASSET_LOG.md: edit the asset "
                           "log, not this file. -->\r\n\r\n## Music\r\n\r\n<!--\r\nnotes\r\n-->\r\n"
                           "- Song by **Zo\xC3\xAB** (CC0)\r\n";
    CHECK(core::credits_lines(md) ==
          std::vector<std::string>{"Credits", "", "Music", "", "Song by Zo\xC3\xAB (CC0)"});
    CHECK(core::credits_lines("<!-- nothing yet -->\n").empty());   // the screen shows its placeholder then
}

TEST_CASE("the dialogue history keeps the last 50 lines and feeds What now? (#167)") {
    core::LineHistory history;
    CHECK(history.empty());
    for (int i = 0; i < 60; ++i) history.record("Guide", "line " + std::to_string(i));
    CHECK(history.entries().size() == core::LineHistory::kMax);
    CHECK(history.entries().front().text == "line 10");
    CHECK(history.last()->text == "line 59");
    auto tr = [](const std::string& key, const core::TrArgs& args) {
        std::string out = key;
        for (const auto& [k, v] : args) out += " " + k + "=" + v;
        return out;
    };
    const auto lines = core::help_lines(tr, "Find the exit", history, {{"jump", "Space"}, {"pause", "Esc"}});
    CHECK(lines == std::vector<std::string>{"help.objective text=Find the exit", "help.last_line name=Guide text=line 59",
                                            "help.controls", "action.jump: Space", "action.pause: Esc"});
    CHECK(core::help_lines(tr, "", core::LineHistory(), {}) ==
          std::vector<std::string>{"help.no_objective", "help.controls"});
}

TEST_CASE("hold to mash repeats after the delay, then at the interval (#166)") {
    core::AutoRepeat rep;
    int fired = 0;
    for (int i = 0; i < 60; ++i) {                 // one second held at 60 Hz
        if (rep.update(1.0 / 60.0, true)) ++fired;
    }
    // first at 0.35 s, then every 0.15 s: 0.35, 0.50, 0.65, 0.80, 0.95
    CHECK(fired == 5);
    CHECK_FALSE(rep.update(1.0 / 60.0, false));   // released: reset
    CHECK_FALSE(rep.update(0.2, true));            // under the delay again
}

TEST_CASE("palettes fall back to the none palette (#169)") {
    const json colours = json::parse(R"({"palettes": {"none": {"player": "#f2bf4c", "floor": "#404552"},
                                                      "protanopia": {"player": "#f2b233"}}})");
    CHECK(core::palette_colour(colours, "protanopia", "player") == std::string("#f2b233"));
    CHECK(core::palette_colour(colours, "protanopia", "floor") == std::string("#404552"));
    CHECK(core::palette_colour(colours, "tritanopia", "player") == std::string("#f2bf4c"));
    CHECK_FALSE(core::palette_colour(colours, "none", "hit").has_value());
    CHECK_FALSE(core::palette_colour(json(), "none", "player").has_value());
}

TEST_CASE("a held subtitle stays until accept and then goes (#167)") {
    const json built = json::parse(R"({"lines": {"guide.welcome": {"name": "Guide", "text": "Hi", "duration_s": 1.0,
                                       "kind": "line", "cooldown_s": 0}, "box.ouch": {"name": "Box", "text": "Oof!",
                                       "kind": "bark", "duration_s": 0.5, "cooldown_s": 3}}})");
    const auto lines = core::subtitle_lines_from_json(built);
    REQUIRE(lines.size() == 2);
    const core::SubtitleLine* welcome = core::find_line(lines, "guide.welcome");
    const core::SubtitleLine* ouch = core::find_line(lines, "box.ouch");
    REQUIRE(welcome);
    REQUIRE(ouch);
    CHECK(core::find_line(lines, "nope") == nullptr);
    json settings = core::default_settings();
    CHECK(core::subtitle_allowed(*welcome, settings));
    CHECK_FALSE(core::subtitle_allowed(*ouch, settings));           // a bark needs subtitle_barks
    settings["access"]["subtitle_barks"] = true;
    CHECK(core::subtitle_allowed(*ouch, settings));
    settings["access"]["subtitles"] = false;
    CHECK_FALSE(core::subtitle_allowed(*welcome, settings));

    core::SubtitleTrack track;
    CHECK(track.play(*welcome, 0.0));
    track.update(0.5, true);
    CHECK(track.current());
    CHECK_FALSE(track.holding());
    track.update(0.6, true);                      // past its duration with hold on: stays
    CHECK(track.current());
    CHECK(track.holding());
    track.dismiss();
    CHECK(track.current() == nullptr);
    CHECK_FALSE(track.holding());
    CHECK(track.play(*welcome, 1.0));
    track.update(1.1, false);                     // hold off: gone on its own
    CHECK(track.current() == nullptr);
    CHECK(track.play(*ouch, 2.0));
    CHECK_FALSE(track.play(*ouch, 3.0));          // inside its cooldown
    CHECK(track.play(*ouch, 5.5));
}

// #276. No ";" in a test name: CTest cuts the name there, and the cut name matches no test, so it "passes" empty
TEST_CASE("a drive run ignores the real keyboard and mouse and pads while normal play reads them") {
    using Ev = core::ShellDeviceEvent;
    // the player's input: read in play, dropped while a drive presses (a stray key, a virtual pad)
    for (const Ev kind : {Ev::Key, Ev::MouseButton, Ev::MouseMotion, Ev::PadButton, Ev::PadAxis}) {
        CHECK(core::admits_device_event(kind, false));
        CHECK_FALSE(core::admits_device_event(kind, true));
    }
    // the window and the devices themselves: always (quit still quits, a pad plugged in is still opened)
    for (const Ev kind : {Ev::PadAdded, Ev::PadRemoved, Ev::Quit, Ev::FocusLost, Ev::Other}) {
        CHECK(core::admits_device_event(kind, false));
        CHECK(core::admits_device_event(kind, true));
    }
}
