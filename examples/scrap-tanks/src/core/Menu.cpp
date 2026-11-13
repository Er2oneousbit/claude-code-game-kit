// ---------------------------------------------------------------------------
// Menu.cpp
// Purpose : Implementation of the menu list, the row builders and the settings menu (see Menu.hpp).
// Usage   : compiled into the `core` library; call through Menu.hpp.
// Notes   : The settings rows mirror the schema in Settings.cpp: add a setting there first, then a row here (and
//           its label key in data/i18n/en.json). The option lists come from Settings.hpp and Bindings.hpp so the
//           menu can never offer a value the loader would reject.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): Display rows stage through core::DisplayStaging, the
//           Apply row, the keep-or-revert confirm, Back that warns once about unapplied Display changes (#308)
// ---------------------------------------------------------------------------
#include "core/Menu.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <type_traits>
#include <utility>

#include "core/Bindings.hpp"
#include "core/Settings.hpp"

namespace core {

using nlohmann::json;

namespace {

// ---- Tunables ----
const std::vector<std::pair<int, int>> kResolutions = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440},
                                                       {3840, 2160}};
constexpr double kSlideEps = 1e-9;   // a slider this close to its target is there

template <typename T, std::size_t N>
std::vector<json> as_options(const std::array<T, N>& values) {
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

std::string resolution_text(const json& res) {
    if (!res.is_array() || res.size() != 2) {
        return "";
    }
    return std::to_string(res[0].get<long long>()) + "x" + std::to_string(res[1].get<long long>());
}

// "1920x1080" -> (1920, 1080); false for anything else
bool parse_resolution(const json& v, int& w, int& h) {
    if (!v.is_string()) {
        return false;
    }
    std::istringstream in(v.get<std::string>());
    char x = 0;
    return static_cast<bool>(in >> w >> x >> h) && x == 'x' && w > 0 && h > 0;
}

}  // namespace

const char* narration_role_key(RowKind kind) {
    switch (kind) {
        case RowKind::Toggle: return "narrate.toggle";
        case RowKind::Slider: return "narrate.slider";
        case RowKind::Choice: return "narrate.choice";
        case RowKind::Button:
        case RowKind::Binding: break;
    }
    return "narrate.button";
}

// ---- MenuList ----------------------------------------------------------------------------------------------
MenuList::MenuList(std::vector<Row> rows_in) : rows(std::move(rows_in)) {
    fix_focus(1);
}

const Row* MenuList::focused() const {
    return index < rows.size() ? &rows[index] : nullptr;
}

Row* MenuList::focused() {
    return index < rows.size() ? &rows[index] : nullptr;
}

std::string MenuList::focused_id() const {
    const Row* r = focused();
    return r ? r->id : "";
}

bool MenuList::focus(const std::string& id) {
    for (std::size_t i = 0; i < rows.size(); ++i) {
        if (rows[i].id == id) {
            index = i;
            return true;
        }
    }
    return false;
}

void MenuList::fix_focus(int dir) {
    const std::size_t n = rows.size();
    if (n == 0) {
        return;
    }
    index = std::min(index, n - 1);
    for (std::size_t tries = 0; tries < n; ++tries) {
        if (rows[index].is_enabled()) {
            return;
        }
        index = (index + n + static_cast<std::size_t>(dir > 0 ? 1 : n - 1)) % n;
    }
}

void MenuList::move(int delta) {
    const std::size_t n = rows.size();
    if (n == 0) {
        return;
    }
    const std::size_t start = index;
    const std::size_t step = delta >= 0 ? 1 : n - 1;
    do {
        index = (index + step) % n;
    } while (!rows[index].is_enabled() && index != start);
    if (on_move) {
        on_move();
    }
}

bool MenuList::action(const std::string& name) {
    if (name == "ui_up") {
        move(-1);
        return true;
    }
    if (name == "ui_down") {
        move(1);
        return true;
    }
    Row* row = focused();
    if (!row) {
        return false;
    }
    if (name == "ui_left" && row->left) {
        row->left();
        return true;
    }
    if (name == "ui_right" && row->right) {
        row->right();
        return true;
    }
    if (name == "ui_accept" && row->accept) {
        row->accept();
        return true;
    }
    return false;
}

std::pair<std::size_t, std::size_t> MenuList::window(std::size_t max_rows) {
    const std::size_t n = rows.size();
    const std::size_t visible = std::max<std::size_t>(1, std::min(max_rows, n));
    if (index < top) {
        top = index;
    }
    if (index >= top + visible) {
        top = index + 1 - visible;
    }
    top = std::min(top, n > visible ? n - visible : 0);
    return {top, std::min(visible, n - top)};
}

// ---- Row builders ------------------------------------------------------------------------------------------
double nudge(double value, double lo, double hi, double step, int dir) {
    double v = value + (dir >= 0 ? step : -step);
    v = std::floor(v / step + 0.5) * step;
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.6f", v);   // "0.15", not 0.15000000000000002, in settings.json
    v = std::strtod(buf, nullptr);
    return std::min(hi, std::max(lo, v));
}

std::string slide_action(double now, double target) {
    if (std::abs(now - target) <= kSlideEps) {
        return "";
    }
    return now > target ? "ui_left" : "ui_right";
}

Row button_row(const std::string& id, Label label, std::function<void()> accept) {
    Row r;
    r.id = id;
    r.kind = RowKind::Button;
    r.label = std::move(label);
    r.value = [] { return std::string(); };
    r.accept = std::move(accept);
    return r;
}

Row toggle_row(const std::string& id, Label label, Getter get, Setter set, ValueText on_off) {
    Row r;
    r.id = id;
    r.kind = RowKind::Toggle;
    r.label = std::move(label);
    auto flip = [get, set] { set(json(!(get().is_boolean() && get().get<bool>()))); };
    r.value = [get, on_off] { return on_off(get()); };
    r.left = flip;
    r.right = flip;
    r.accept = flip;
    return r;
}

Row slider_row(const std::string& id, Label label, Getter get, Setter set, double lo, double hi, double step,
               ValueText format) {
    Row r;
    r.id = id;
    r.kind = RowKind::Slider;
    r.label = std::move(label);
    auto current = [get, lo] { const json v = get(); return v.is_number() ? v.get<double>() : lo; };
    r.value = [get, format] { return format(get()); };
    r.left = [current, set, lo, hi, step] { set(json(nudge(current(), lo, hi, step, -1))); };
    r.right = [current, set, lo, hi, step] { set(json(nudge(current(), lo, hi, step, 1))); };
    r.fraction = [current, lo, hi] { return hi > lo ? (current() - lo) / (hi - lo) : 0.0; };
    return r;
}

Row choice_row(const std::string& id, Label label, std::function<std::vector<json>()> options, Getter get,
               Setter set, ValueText show) {
    Row r;
    r.id = id;
    r.kind = RowKind::Choice;
    r.label = std::move(label);
    auto step = [options, get, set](int dir) {
        const std::vector<json> list = options();
        if (list.empty()) {
            return;
        }
        const json cur = get();
        std::size_t idx = 0;
        for (std::size_t i = 0; i < list.size(); ++i) {
            if (list[i] == cur) {
                idx = i;
            }
        }
        const std::size_t n = list.size();
        set(list[(idx + n + static_cast<std::size_t>(dir >= 0 ? 1 : n - 1)) % n]);
    };
    r.value = [get, show] { return show(get()); };
    r.left = [step] { step(-1); };
    r.right = [step] { step(1); };
    r.accept = [step] { step(1); };
    return r;
}

// ---- SettingsMenu ------------------------------------------------------------------------------------------
SettingsMenu::SettingsMenu(json& settings, SettingsHooks hooks) : s_(settings), hooks_(std::move(hooks)) {
    staging_ = DisplayStaging(s_["display"].is_object() ? s_["display"] : json::object());
    confirm_ = MenuList({button_row("keep", [this] { return t("settings.keep"); }, [this] { keep_display(); }),
                         button_row("revert", [this] { return t("settings.revert"); }, [this] { revert_display(); })});
    lists_["display"] = MenuList(display_rows());
    lists_["audio"] = MenuList(audio_rows());
    lists_["controls"] = MenuList(controls_rows());
    lists_["access"] = MenuList(access_rows());
    lists_["language"] = MenuList(language_rows());
}

std::string SettingsMenu::t(const std::string& key, const TrArgs& args) const {
    return hooks_.tr ? hooks_.tr(key, args) : key;
}

void SettingsMenu::changed(const std::string& section) {
    dirty = true;
    if (hooks_.changed) {
        hooks_.changed(section);
    }
}

Row SettingsMenu::field(const std::string& section, const std::string& name, RowKind kind,
                        const std::vector<json>& options, double lo, double hi, double step) {
    json* s = &s_;
    Getter get = [s, section, name]() -> json {
        const auto sec = s->find(section);
        if (sec == s->end() || !sec->is_object() || !sec->contains(name)) {
            return json();
        }
        return sec->at(name);
    };
    Setter set = [this, s, section, name](const json& v) {
        (*s)[section][name] = v;
        changed(section);
    };
    if (section == "display") {   // Display waits for Apply (#308): the row shows and changes the staged value
        get = [this, name]() -> json { return staging_.value(name); };
        set = [this, name](const json& v) { staging_.stage(name, v); };
    }
    Label label = [this, section, name] { return t("settings." + section + "." + name); };
    switch (kind) {
        case RowKind::Toggle:
            return toggle_row(name, label, get, set, [this](const json& v) {
                return t(v.is_boolean() && v.get<bool>() ? "value.on" : "value.off");
            });
        case RowKind::Slider: {
            const bool times = section == "display" || name == "text_scale";
            return slider_row(name, label, get, set, lo, hi, step, [this, times](const json& v) {
                const double x = v.is_number() ? v.get<double>() : 0.0;
                if (times) {
                    char buf[32];
                    std::snprintf(buf, sizeof buf, "%g", x);
                    return t("value.times", {{"n", buf}});
                }
                return t("value.percent", {{"n", std::to_string(static_cast<long long>(std::floor(x * 100 + 0.5)))}});
            });
        }
        case RowKind::Choice:
            return choice_row(name, label, [options] { return options; }, get, set, [this, name](const json& v) {
                return t("opt." + name + "." + (v.is_string() ? v.get<std::string>() : v.dump()));
            });
        case RowKind::Button:
        case RowKind::Binding: break;
    }
    return button_row(name, label, [] {});
}

Row SettingsMenu::back_row() {
    return button_row("back", [this] { return t("settings.back"); }, [this] { back(); });
}

std::vector<Row> SettingsMenu::display_rows() {
    std::vector<json> res_options;
    for (const auto& [w, h] : kResolutions) {
        res_options.emplace_back(std::to_string(w) + "x" + std::to_string(h));
    }
    Row res = choice_row(
        "resolution", [this] { return t("settings.display.resolution"); }, [res_options] { return res_options; },
        [this]() -> json { return resolution_text(staging_.value("resolution")); },
        [this](const json& v) {
            int w = 0;
            int h = 0;
            if (parse_resolution(v, w, h)) {
                staging_.stage("resolution", json::array({w, h}));
            }
        },
        [this](const json& v) {
            int w = 0;
            int h = 0;
            if (!parse_resolution(v, w, h)) {
                return t("value.raw", {{"v", v.dump()}});
            }
            return t("value.resolution", {{"w", std::to_string(w)}, {"h", std::to_string(h)}});
        });
    Row cap = choice_row(
        "frame_cap", [this] { return t("settings.display.frame_cap"); }, [] { return as_options(kFrameCaps); },
        [this]() -> json { return staging_.value("frame_cap"); },
        [this](const json& v) { staging_.stage("frame_cap", v); },
        [this](const json& v) {
            const long long n = v.is_number() ? v.get<long long>() : 0;
            return n == 0 ? t("opt.frame_cap.0") : t("value.fps", {{"n", std::to_string(n)}});
        });
    Row apply = button_row("apply", [this] { return t("settings.apply"); }, [this] { apply_display(); });
    apply.enabled = [this] { return staging_.has_pending(); };   // only while a Display change waits
    return {
        field("display", "mode", RowKind::Choice, as_options(kDisplayModes)),
        field("display", "vsync", RowKind::Toggle),
        cap,
        res,
        field("display", "ui_scale", RowKind::Slider, {}, 0.75, 2.0, 0.25),
        apply,
        back_row(),
    };
}

// ---- The Display tab's Apply (#308) ------------------------------------------------------------------------
void SettingsMenu::set_display(const DisplayStaging::Calls& calls) {
    if (calls.empty()) {
        return;
    }
    for (const auto& [field, v] : calls) {
        s_["display"][field] = v;
    }
    changed("display");
    if (hooks_.save) {
        hooks_.save();
    }
}

bool SettingsMenu::apply_display() {
    set_display(staging_.apply());
    lists_["display"].fix_focus(1);   // Apply is disabled now: focus moves on (to Back)
    if (staging_.confirming()) {
        confirm_.focus("keep");
        return true;
    }
    return false;
}

void SettingsMenu::tick(double real_dt) {
    if (staging_.confirming()) {
        set_display(staging_.tick(real_dt));
    }
}

void SettingsMenu::keep_display() {
    staging_.keep();
}

void SettingsMenu::revert_display() {
    set_display(staging_.revert());
}

void SettingsMenu::back() {
    auto [what, calls] = staging_.back();
    if (what == "revert") {
        set_display(calls);
    } else if (what == "warn") {
        if (hooks_.say) {
            hooks_.say(t("settings.unapplied"));
        }
    } else if (hooks_.close) {
        hooks_.close();
    }
}

std::vector<Row> SettingsMenu::audio_rows() {
    std::vector<Row> rows;
    for (const char* bus : {"master", "music", "sfx", "ui", "voice"}) {
        rows.push_back(field("audio", bus, RowKind::Slider, {}, 0.0, 1.0, 0.1));
    }
    rows.push_back(field("audio", "mono", RowKind::Toggle));
    rows.push_back(back_row());
    return rows;
}

Row SettingsMenu::binding_row(const std::string& action) {
    Row r;
    r.id = "bind_" + action;
    r.kind = RowKind::Binding;
    r.label = [this, action] { return t("action." + action); };
    json* s = &s_;
    SettingsHooks* hooks = &hooks_;
    r.value = [s, hooks, action] {
        // both cells, for the narration: "Space, A"
        std::string out;
        const json& list = (*s)["input"]["bindings"];
        for (std::size_t slot = 0; slot < 2; ++slot) {
            std::string b;
            if (list.is_object() && list.contains(action) && list[action].is_array() && slot < list[action].size() &&
                list[action][slot].is_string()) {
                b = list[action][slot].get<std::string>();
            }
            const std::string label = hooks->binding_label ? hooks->binding_label(b, slot) : b;
            out += (slot ? ", " : "") + label;
        }
        return out;
    };
    // the row object lives inside the list's vector: cell is read through the row the list hands back
    r.left = nullptr;
    r.right = nullptr;
    r.accept = [this, action] {
        const Row* row = list().focused();
        const std::size_t slot = row && row->cell == 1 ? kPadSlot : kKeyboardSlot;
        if (hooks_.capture) {
            hooks_.capture(action, slot);
        }
    };
    return r;
}

std::vector<Row> SettingsMenu::controls_rows() {
    std::vector<Row> rows;
    for (const char* action : kGameActions) {
        rows.push_back(binding_row(action));
    }
    rows.push_back(field("input", "glyphs", RowKind::Choice, as_options(kGlyphSets)));
    rows.push_back(field("input", "deadzone", RowKind::Slider, {}, 0.0, 0.9, 0.05));
    rows.push_back(field("input", "invert_y", RowKind::Toggle));
    rows.push_back(button_row("reset", [this] { return t("controls.reset"); }, [this] {
        reset_bindings();
        if (hooks_.say) {
            hooks_.say(t("controls.reset_done"));
        }
    }));
    // one-handed layouts (#166, motor access), from data/input/presets.json
    if (hooks_.presets.is_object()) {
        for (const char* preset : kPresetNames) {
            const std::string name = preset;
            rows.push_back(button_row("preset_" + name, [this, name] { return t("controls.preset." + name); },
                                      [this, name] {
                                          if (apply_preset(name) && hooks_.say) {
                                              hooks_.say(t("controls.preset_done"));
                                          }
                                      }));
        }
    }
    rows.push_back(back_row());
    return rows;
}

std::vector<Row> SettingsMenu::access_rows() {
    return {
        field("access", "text_scale", RowKind::Slider, {}, 0.75, 2.0, 0.25),
        field("access", "subtitles", RowKind::Toggle),
        field("access", "subtitle_size", RowKind::Choice, as_options(kSubtitleSizes)),
        field("access", "subtitle_background", RowKind::Slider, {}, 0.0, 1.0, 0.1),
        field("access", "speaker_names", RowKind::Toggle),
        field("access", "subtitle_barks", RowKind::Toggle),
        field("access", "captions_sfx", RowKind::Toggle),
        field("access", "colorblind", RowKind::Choice, as_options(kColorblindModes)),
        field("access", "reduce_motion", RowKind::Toggle),
        field("access", "shake_scale", RowKind::Slider, {}, 0.0, 1.0, 0.25),
        field("access", "flash_limit", RowKind::Toggle),
        field("access", "hold_to_toggle", RowKind::Toggle),
        field("access", "difficulty", RowKind::Choice, as_options(kDifficulties)),
        field("access", "game_speed", RowKind::Slider, {}, 0.5, 1.0, 0.1),
        field("access", "readable_font", RowKind::Toggle),                       // #167: cognitive access
        field("access", "line_spacing", RowKind::Slider, {}, 1.0, 2.0, 0.25),
        field("access", "subtitle_hold", RowKind::Toggle),
        field("access", "timing_scale", RowKind::Slider, {}, 1.0, 3.0, 0.5),    // #166: motor access
        field("access", "auto_repeat", RowKind::Toggle),
        field("access", "narration", RowKind::Toggle),                           // #165: menu narration
        back_row(),
    };
}

std::vector<Row> SettingsMenu::language_rows() {
    json* s = &s_;
    SettingsHooks* hooks = &hooks_;
    Row lang = choice_row(
        "language", [this] { return t("settings.language.language"); },
        [hooks] {
            std::vector<json> out;
            for (const std::string& loc : hooks->locales ? hooks->locales() : std::vector<std::string>{"en"}) {
                out.emplace_back(loc);
            }
            if (hooks->debug_build) {
                out.emplace_back("pseudo");
            }
            return out;
        },
        [s]() -> json { return (*s)["language"]; },
        [this, s](const json& v) {
            (*s)["language"] = v;
            changed("language");
        },
        [this, hooks](const json& v) {
            const std::string loc = v.is_string() ? v.get<std::string>() : v.dump();
            const std::string name = hooks->locale_name ? hooks->locale_name(loc) : loc;
            return t("value.raw", {{"v", name.empty() ? loc : name}});
        });
    return {
        lang,
        field("telemetry", "consent", RowKind::Choice, as_options(kConsentValues)),
        back_row(),
    };
}

bool SettingsMenu::action(const std::string& name) {
    if (staging_.confirming()) {   // the keep-or-revert confirm takes every press; cancel reverts
        if (name == "ui_cancel") {
            revert_display();
            return true;
        }
        confirm_.action(name);
        return true;
    }
    if (name == "ui_cancel") {
        back();
        return true;
    }
    MenuList& l = list();
    if (on_tabs) {
        if (name == "ui_left") {
            switch_tab(-1);
            return true;
        }
        if (name == "ui_right") {
            switch_tab(1);
            return true;
        }
        if (name == "ui_down" || name == "ui_accept") {
            on_tabs = false;
            l.index = 0;
            l.fix_focus(1);
            return true;
        }
        return name == "ui_up";
    }
    if (name == "ui_up" && l.index == 0) {
        on_tabs = true;
        return true;
    }
    Row* row = l.focused();
    if (row && row->kind == RowKind::Binding && (name == "ui_left" || name == "ui_right")) {
        row->cell = name == "ui_left" ? 0 : 1;
        return true;
    }
    return l.action(name);
}

void SettingsMenu::switch_tab(int delta) {
    std::size_t idx = 0;
    for (std::size_t i = 0; i < kTabs.size(); ++i) {
        if (tab == kTabs[i]) {
            idx = i;
        }
    }
    const std::size_t n = kTabs.size();
    tab = kTabs[(idx + n + static_cast<std::size_t>(delta >= 0 ? 1 : n - 1)) % n];
    if (list().on_move) {
        list().on_move();
    }
}

void SettingsMenu::open_tab(const std::string& name, const std::string& focus_row) {
    if (lists_.count(name)) {
        tab = name;
    }
    on_tabs = focus_row.empty();
    if (!focus_row.empty()) {
        list().focus(focus_row);
    }
}

std::string SettingsMenu::focus_id() const {
    if (staging_.confirming()) {
        return "confirm." + confirm_.focused_id();
    }
    if (on_tabs) {
        return "tabs." + tab;
    }
    return tab + "." + list().focused_id();
}

bool SettingsMenu::apply_preset(const std::string& name) {
    if (!core::apply_preset(s_, hooks_.presets, name)) {
        return false;
    }
    dirty = true;
    return true;
}

void SettingsMenu::reset_bindings() {
    s_["input"]["bindings"] = bindings_to_json(default_bindings());
    dirty = true;
}

bool apply_preset(json& settings, const json& presets, const std::string& name) {
    if (!presets.is_object() || !presets.contains("presets") || !presets["presets"].is_object() ||
        !presets["presets"].contains(name) || !presets["presets"][name].is_object() ||
        !presets["presets"][name].contains("bindings") || !presets["presets"][name]["bindings"].is_object()) {
        return false;
    }
    Bindings b = default_bindings();
    for (const auto& [action, pair] : presets["presets"][name]["bindings"].items()) {
        if (!pair.is_array() || pair.size() != 2 || !pair[0].is_string() || !pair[1].is_string()) {
            return false;
        }
        b[action] = {pair[0].get<std::string>(), pair[1].get<std::string>()};
    }
    settings["input"]["bindings"] = bindings_to_json(b);
    return true;
}

}  // namespace core
