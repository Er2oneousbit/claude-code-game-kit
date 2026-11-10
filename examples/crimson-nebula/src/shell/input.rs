// ---------------------------------------------------------------------------
// shell/input.rs
// Purpose : The names the bindings use ("key:a", "pad:south") against Bevy's KeyCode and GamepadButton, both ways:
//           pressing a key finds the actions bound to it, and the "press a key" capture names the key pressed.
// Usage   : input::key_code("space") -> Some(KeyCode::Space);  input::key_name(KeyCode::KeyA) -> Some("a")
//           input::pad_button("south") -> Some(GamepadButton::South);  input::actions_for(&bindings, "key:escape")
// Notes   : Key names are the kit's (the same strings in every engine's settings.json): letters and digits as
//           themselves, arrows as up/down/left/right, and the common named keys below. A key with no name here cannot
//           be bound (the capture ignores it). Pad buttons are by position (south, east...), never by letter.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
use bevy::input::gamepad::GamepadButton;
use bevy::input::keyboard::KeyCode;

use crate::logic::bindings::Bindings;

/// (kit name, Bevy key) for every key the shell can bind.
const KEYS: &[(&str, KeyCode)] = &[
    ("a", KeyCode::KeyA),
    ("b", KeyCode::KeyB),
    ("c", KeyCode::KeyC),
    ("d", KeyCode::KeyD),
    ("e", KeyCode::KeyE),
    ("f", KeyCode::KeyF),
    ("g", KeyCode::KeyG),
    ("h", KeyCode::KeyH),
    ("i", KeyCode::KeyI),
    ("j", KeyCode::KeyJ),
    ("k", KeyCode::KeyK),
    ("l", KeyCode::KeyL),
    ("m", KeyCode::KeyM),
    ("n", KeyCode::KeyN),
    ("o", KeyCode::KeyO),
    ("p", KeyCode::KeyP),
    ("q", KeyCode::KeyQ),
    ("r", KeyCode::KeyR),
    ("s", KeyCode::KeyS),
    ("t", KeyCode::KeyT),
    ("u", KeyCode::KeyU),
    ("v", KeyCode::KeyV),
    ("w", KeyCode::KeyW),
    ("x", KeyCode::KeyX),
    ("y", KeyCode::KeyY),
    ("z", KeyCode::KeyZ),
    ("0", KeyCode::Digit0),
    ("1", KeyCode::Digit1),
    ("2", KeyCode::Digit2),
    ("3", KeyCode::Digit3),
    ("4", KeyCode::Digit4),
    ("5", KeyCode::Digit5),
    ("6", KeyCode::Digit6),
    ("7", KeyCode::Digit7),
    ("8", KeyCode::Digit8),
    ("9", KeyCode::Digit9),
    ("up", KeyCode::ArrowUp),
    ("down", KeyCode::ArrowDown),
    ("left", KeyCode::ArrowLeft),
    ("right", KeyCode::ArrowRight),
    ("space", KeyCode::Space),
    ("enter", KeyCode::Enter),
    ("escape", KeyCode::Escape),
    ("tab", KeyCode::Tab),
    ("backspace", KeyCode::Backspace),
    ("lshift", KeyCode::ShiftLeft),
    ("rshift", KeyCode::ShiftRight),
    ("lctrl", KeyCode::ControlLeft),
    ("rctrl", KeyCode::ControlRight),
    ("lalt", KeyCode::AltLeft),
    ("ralt", KeyCode::AltRight),
    ("comma", KeyCode::Comma),
    ("period", KeyCode::Period),
    ("slash", KeyCode::Slash),
    ("minus", KeyCode::Minus),
    ("equals", KeyCode::Equal),
    ("f1", KeyCode::F1),
    ("f2", KeyCode::F2),
    ("f3", KeyCode::F3),
    ("f4", KeyCode::F4),
    ("f5", KeyCode::F5),
    ("f6", KeyCode::F6),
    ("f7", KeyCode::F7),
    ("f8", KeyCode::F8),
    ("f9", KeyCode::F9),
    ("f10", KeyCode::F10),
    ("f11", KeyCode::F11),
    ("f12", KeyCode::F12),
];

/// (kit name, Bevy button) for the pad buttons the bindings name.
const PAD: &[(&str, GamepadButton)] = &[
    ("south", GamepadButton::South),
    ("east", GamepadButton::East),
    ("west", GamepadButton::West),
    ("north", GamepadButton::North),
    ("l1", GamepadButton::LeftTrigger),
    ("r1", GamepadButton::RightTrigger),
    ("l2", GamepadButton::LeftTrigger2),
    ("r2", GamepadButton::RightTrigger2),
    ("l3", GamepadButton::LeftThumb),
    ("r3", GamepadButton::RightThumb),
    ("start", GamepadButton::Start),
    ("select", GamepadButton::Select),
    ("dpad_up", GamepadButton::DPadUp),
    ("dpad_down", GamepadButton::DPadDown),
    ("dpad_left", GamepadButton::DPadLeft),
    ("dpad_right", GamepadButton::DPadRight),
];

pub fn key_code(name: &str) -> Option<KeyCode> {
    KEYS.iter().find(|(n, _)| *n == name).map(|(_, k)| *k)
}

pub fn key_name(key: KeyCode) -> Option<&'static str> {
    KEYS.iter().find(|(_, k)| *k == key).map(|(n, _)| *n)
}

pub fn pad_button(name: &str) -> Option<GamepadButton> {
    PAD.iter().find(|(n, _)| *n == name).map(|(_, b)| *b)
}

pub fn pad_name(button: GamepadButton) -> Option<&'static str> {
    PAD.iter().find(|(_, b)| *b == button).map(|(n, _)| *n)
}

/// Every key and button the shell can see, as bindings ("key:a", "pad:south"): the input systems poll these.
pub fn all_keys() -> impl Iterator<Item = (&'static str, KeyCode)> {
    KEYS.iter().copied()
}

pub fn all_pad_buttons() -> impl Iterator<Item = (&'static str, GamepadButton)> {
    PAD.iter().copied()
}

/// The actions bound to one binding, in sorted order (ui_cancel before pause for key:escape, so a menu backs out
/// and the game pauses).
pub fn actions_for(bindings: &Bindings, binding: &str) -> Vec<String> {
    bindings
        .iter()
        .filter(|(_, slots)| slots.iter().any(|b| b == binding))
        .map(|(action, _)| action.clone())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic::bindings::default_bindings;

    #[test]
    fn names_round_trip_and_escape_backs_out_before_it_pauses() {
        assert_eq!(key_name(key_code("space").unwrap()), Some("space"));
        assert_eq!(pad_name(pad_button("dpad_up").unwrap()), Some("dpad_up"));
        assert_eq!(key_code("hyperkey"), None);
        assert_eq!(
            actions_for(&default_bindings(), "key:escape"),
            vec!["pause", "ui_cancel"]
        );
    }
}
