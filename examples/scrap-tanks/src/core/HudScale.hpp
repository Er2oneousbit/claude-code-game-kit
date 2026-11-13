// ---------------------------------------------------------------------------
// HudScale.hpp
// Purpose : The player's text size for a game HUD (#309): display.ui_scale times access.text_scale, and a watch that
//           says when it changed, so a HUD sized by hand follows the settings like the shell's own menus do.
//           Pure logic, no SDL.
// Usage   : const double k = core::hud_text_scale(shell.settings());   // 1.0 at the defaults
//           core::HudScaleWatch watch;  each frame: if (watch.update(settings)) relayout(watch.scale());
//           in the kit's shell: shell.hud_scale(), or shell.play.hud_scale_changed = [](double k) { ... }
// Notes   : Text drawn through shell::Draw already uses this factor (Shell::render passes it to begin_frame), so a
//           HUD label drawn with draw.text follows by itself; use the factor for what a game sizes on its own (its
//           own font, a panel around the text, an icon next to it). ui_scale changes on the Display tab's Apply
//           (#308), text_scale at once. SOP-20: text size reaches all text.
//
// Pseudocode:
//   hud_text_scale(s) = number(s.display.ui_scale, 1) * number(s.access.text_scale, 1)
//   watch.update(s): k = hud_text_scale(s); changed = first call or k != last; last = k; return changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <optional>

#include <nlohmann/json.hpp>

namespace core {

// settings[section][key] as a number, or fallback.
inline double settings_number(const nlohmann::json& settings, const char* section, const char* key, double fallback) {
    if (!settings.is_object() || !settings.contains(section) || !settings[section].is_object()) {
        return fallback;
    }
    const nlohmann::json& sec = settings[section];
    return sec.contains(key) && sec[key].is_number() ? sec[key].get<double>() : fallback;
}

// The factor a HUD multiplies its text size by: display.ui_scale * access.text_scale (1.0 each when missing).
inline double hud_text_scale(const nlohmann::json& settings) {
    return settings_number(settings, "display", "ui_scale", 1.0) * settings_number(settings, "access", "text_scale", 1.0);
}

// Says when the factor changed: true on the first update (the HUD's first layout) and whenever it differs after.
class HudScaleWatch {
public:
    bool update(const nlohmann::json& settings) {
        const double k = hud_text_scale(settings);
        const bool changed = !last_ || *last_ != k;
        last_ = k;
        return changed;
    }
    double scale() const { return last_.value_or(1.0); }

private:
    std::optional<double> last_;
};

}  // namespace core
