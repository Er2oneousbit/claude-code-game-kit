// ---------------------------------------------------------------------------
// logic/hud_scale.rs
// Purpose : The player's text size for a game HUD (#309): display.ui_scale and access.text_scale, so a HUD sized by
//           hand follows the settings like the shell's own menus do. Pure, no ECS.
// Usage   : let k = hud_scale::hud_text_scale(&shell.settings);       // ui_scale * text_scale, 1.0 at the defaults
//           in the game: Res<HudScale> (shell/mod.rs) and `if hud.is_changed() { ... }`, or its font_px(base)
// Notes   : Under bevy_ui, UiScale already multiplies every node by ui_scale (the shell keeps it in step), so a HUD
//           Text there sizes its font by text_scale alone: HudScale::ui_font_px. A HUD drawn any other way (Text2d,
//           its own panel or icon size) takes both: HudScale::font_px. ui_scale changes on the Display tab's Apply
//           (#308), text_scale at once. SOP-20: text size reaches all text.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use serde_json::Value;

/// settings[section][key] as a number, or 1.0.
fn factor(settings: &Value, section: &str, key: &str) -> f64 {
    settings[section][key].as_f64().unwrap_or(1.0)
}

/// (display.ui_scale, access.text_scale), 1.0 each when missing.
pub fn hud_scales(settings: &Value) -> (f64, f64) {
    (
        factor(settings, "display", "ui_scale"),
        factor(settings, "access", "text_scale"),
    )
}

/// The factor a HUD multiplies its text size by: display.ui_scale * access.text_scale.
pub fn hud_text_scale(settings: &Value) -> f64 {
    let (ui, text) = hud_scales(settings);
    ui * text
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn the_factor_is_ui_scale_times_text_scale() {
        assert_eq!(hud_text_scale(&json!({})), 1.0);
        let s = json!({"display": {"ui_scale": 2.0}, "access": {"text_scale": 1.5}});
        assert_eq!(hud_scales(&s), (2.0, 1.5));
        assert_eq!(hud_text_scale(&s), 3.0);
    }
}

// {{FOOTER}}
