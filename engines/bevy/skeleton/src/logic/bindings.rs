// ---------------------------------------------------------------------------
// logic/bindings.rs
// Purpose : Input bindings as data (action -> slots of "kind:name" strings), rebinding with conflict swaps, and
//           the button-prompt art names for each glyph set (keyboard, Xbox, PlayStation, generic pad).
// Usage   : let (new, conflicts) = rebind(&bindings, "jump", 0, "key:k")?;
//           let set = glyph_set(settings::text(&s, "input", "glyphs"), last_device);   // "auto" follows the device
//           let art = glyph_name(set, prompt_binding(&bindings, "jump", set));        // "xbox_a", "key_space"
// Notes   : Slot 0 is the keyboard binding, slot 1 the pad binding, more slots are extras. A binding is
//           "key:space", "mouse:left", "pad:south" (face buttons by position) or "pad_axis:leftx-"; "" is unbound.
//           Groups: ui_* actions and game actions may share a key (Enter in menus, Space in game); inside a
//           group a key belongs to one action. Mapping these names to Bevy's KeyCode and GamepadButton happens in
//           game/present.rs. Tested in tests/golden.rs against data/golden/shell.json.
//
// Pseudocode:
//   rebind(b, action, slot, binding): old = b[action][slot] (or "") -> every other slot in the same group that
//   holds binding gets old (a swap) -> b[action][slot] = binding (slot == len appends) -> (b, sorted conflicts)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;

/// Action -> its bindings by slot. BTreeMap: sorted, so conflicts come out in the same order on every engine.
pub type Bindings = BTreeMap<String, Vec<String>>;

// ---- Defaults ------------------------------------------------------------------
/// (action, [keyboard, pad]). Add your game's actions here; the settings defaults are built from this table.
pub const DEFAULT_BINDINGS: [(&str, [&str; 2]); 14] = [
    ("ui_up", ["key:up", "pad:dpad_up"]),
    ("ui_down", ["key:down", "pad:dpad_down"]),
    ("ui_left", ["key:left", "pad:dpad_left"]),
    ("ui_right", ["key:right", "pad:dpad_right"]),
    ("ui_accept", ["key:enter", "pad:south"]),
    ("ui_cancel", ["key:escape", "pad:east"]),
    ("move_left", ["key:a", "pad:dpad_left"]),
    ("move_right", ["key:d", "pad:dpad_right"]),
    ("move_up", ["key:w", "pad:dpad_up"]),
    ("move_down", ["key:s", "pad:dpad_down"]),
    ("jump", ["key:space", "pad:south"]),
    ("attack", ["key:j", "pad:west"]),
    ("interact", ["key:e", "pad:north"]),
    ("pause", ["key:escape", "pad:start"]),
];

/// The glyph setting's choices: "auto" picks by the last device used.
pub const GLYPH_SETS: [&str; 5] = ["auto", "keyboard", "xbox", "playstation", "generic"];

/// Pad buttons by position -> the Xbox and PlayStation names on the prompt art.
const XBOX: [(&str, &str); 10] = [
    ("south", "a"),
    ("east", "b"),
    ("west", "x"),
    ("north", "y"),
    ("l1", "lb"),
    ("r1", "rb"),
    ("l2", "lt"),
    ("r2", "rt"),
    ("start", "menu"),
    ("select", "view"),
];
const PLAYSTATION: [(&str, &str); 6] = [
    ("south", "cross"),
    ("east", "circle"),
    ("west", "square"),
    ("north", "triangle"),
    ("start", "options"),
    ("select", "share"),
];

pub fn default_bindings() -> Bindings {
    DEFAULT_BINDINGS
        .iter()
        .map(|(action, slots)| (action.to_string(), slots.iter().map(|s| s.to_string()).collect()))
        .collect()
}

/// "ui" for menu actions (ui_*), "game" for the rest. Conflicts only count inside one group.
pub fn group_of(action: &str) -> &'static str {
    if action.starts_with("ui_") { "ui" } else { "game" }
}

/// Puts `binding` in `action`'s `slot` (slot == the current length appends). Another action of the same group
/// that used it gets this slot's old binding (a swap), or "" (unbound) when there was none.
/// Returns the new bindings and the slots that changed hands, as (action, slot) in sorted order.
pub fn rebind(
    bindings: &Bindings,
    action: &str,
    slot: usize,
    binding: &str,
) -> Result<(Bindings, Vec<(String, usize)>), String> {
    let mut b = bindings.clone();
    let len = b.entry(action.to_string()).or_default().len();
    if slot > len {
        return Err(format!("{action}: slot {slot} is past the end ({len} slot(s))"));
    }
    let old = b[action].get(slot).cloned().unwrap_or_default();
    let mut conflicts = Vec::new();
    if !binding.is_empty() {
        for (other, list) in &b {
            if group_of(other) != group_of(action) {
                continue;
            }
            for (s, name) in list.iter().enumerate() {
                if (other != action || s != slot) && name == binding {
                    conflicts.push((other.clone(), s));
                }
            }
        }
    }
    // unwrap: the entry was created above
    let list = b.get_mut(action).unwrap();
    if slot == list.len() {
        list.push(binding.to_string());
    } else {
        list[slot] = binding.to_string();
    }
    for (other, s) in &conflicts {
        // unwrap: conflicts only name existing actions and slots
        b.get_mut(other).unwrap()[*s] = old.clone();
    }
    Ok((b, conflicts))
}

/// Which prompt art to show: the player's choice, or (auto) the last device used:
/// "keyboard", "mouse", "pad_xbox", "pad_playstation", anything else is a generic pad.
pub fn glyph_set<'a>(setting: &'a str, last_device: &str) -> &'a str {
    if setting != "auto" {
        return setting;
    }
    match last_device {
        "keyboard" | "mouse" => "keyboard",
        "pad_xbox" => "xbox",
        "pad_playstation" => "playstation",
        _ => "generic",
    }
}

fn lookup<'a>(table: &[(&str, &'a str)], name: &'a str) -> &'a str {
    table.iter().find(|(k, _)| *k == name).map_or(name, |(_, v)| *v)
}

/// The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick...
/// "unknown" for a binding of no known kind.
pub fn glyph_name(gset: &str, binding: &str) -> String {
    let (kind, name) = binding.split_once(':').unwrap_or((binding, ""));
    let name = match kind {
        "key" => return format!("key_{name}"),
        "mouse" => return format!("mouse_{name}"),
        "pad_axis" if name.starts_with("left") => "lstick",
        "pad_axis" => "rstick",
        "pad" => name,
        _ => return "unknown".to_string(),
    };
    match gset {
        "xbox" => format!("xbox_{}", lookup(&XBOX, name)),
        "playstation" => format!("ps_{}", lookup(&PLAYSTATION, name)),
        _ => format!("pad_{name}"),
    }
}

/// The binding to show for an action: slot 0 (keyboard) for the keyboard set, slot 1 (pad) otherwise; "" if none.
pub fn prompt_binding<'a>(bindings: &'a Bindings, action: &str, gset: &str) -> &'a str {
    let slot = if gset == "keyboard" { 0 } else { 1 };
    bindings
        .get(action)
        .and_then(|list| list.get(slot))
        .map_or("", String::as_str)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_slot_past_the_end_is_an_error() {
        assert!(rebind(&default_bindings(), "jump", 3, "key:k").is_err());
    }

    #[test]
    fn unbinding_never_steals_from_another_action() {
        let (b, conflicts) = rebind(&default_bindings(), "jump", 0, "").unwrap();
        assert!(conflicts.is_empty());
        assert_eq!(b["jump"][0], "");
    }
}

// {{FOOTER}}
