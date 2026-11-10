// ---------------------------------------------------------------------------
// shell/narrator.rs
// Purpose : Menu narration (#165): every focus change, value change and screen says a short line ("Music volume,
//           slider, 70 percent"), so a blind or low-vision player can use the title, settings and pause screens.
// Usage   : narrator.update(&focus)   // once a frame, after the actions ran; narrator.last_line holds the line
// Notes   : The line is always worked out (the access drive reports it for every row) and spoken only with
//           access.narration on and outside automated runs (Focus.enabled, set by Shell::narrate). Bevy has no
//           speech of its own, so the operating system's is used from a background
//           thread (the game never waits): Windows' speech synthesizer through PowerShell, macOS `say`, Linux
//           `spd-say` (speech-dispatcher). Only Windows was tried (verify on macOS and Linux); a line still being
//           spoken is not cut off. The thread takes one line at a time from a channel, so lines never overlap.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
use std::sync::mpsc::{Sender, channel};

use crate::logic::bindings::narration_line;

/// What the narrator needs to know about the screen on top this frame.
pub struct Focus<'a> {
    /// The screen's title (or name) and the word for "screen".
    pub screen_title: &'a str,
    pub screen_word: &'a str,
    /// The focused row: (label, role word, value text), or None.
    pub row: Option<(&'a str, &'a str, &'a str)>,
    /// A change of screen since last frame.
    pub screen_changed: bool,
    pub enabled: bool,
}

#[derive(Default)]
pub struct Narrator {
    pub last_line: String,
    speaker: Option<Sender<String>>,
}

impl Narrator {
    /// The line one menu row says: its label, its role, its value.
    pub fn describe(label: &str, role: &str, value: &str) -> String {
        narration_line(label, role, value)
    }

    pub fn update(&mut self, focus: &Focus<'_>) {
        if focus.screen_changed {
            self.say(narration_line(focus.screen_title, focus.screen_word, ""), focus.enabled);
            return;
        }
        if let Some((label, role, value)) = focus.row {
            let line = narration_line(label, role, value);
            if line != self.last_line {
                self.say(line, focus.enabled);
            }
        }
    }

    fn say(&mut self, line: String, enabled: bool) {
        self.last_line = line.clone();
        if !enabled {
            return;
        }
        if self.speaker.is_none() {
            self.speaker = Some(spawn_speaker());
        }
        if let Some(tx) = &self.speaker
            && tx.send(line).is_err()
        {
            self.speaker = None; // the thread died (no speech on this system): try again next time
        }
    }
}

/// The speech thread: one line at a time, through the system's speech command.
fn spawn_speaker() -> Sender<String> {
    let (tx, rx) = channel::<String>();
    std::thread::spawn(move || {
        while let Ok(line) = rx.recv() {
            let _ = speech_command(&line).status(); // nothing to do when speech is missing: the line is logged anyway
        }
    });
    tx
}

fn speech_command(text: &str) -> std::process::Command {
    if cfg!(target_os = "windows") {
        let quoted = text.replace('\'', "''").replace('"', "");
        let mut cmd = std::process::Command::new("powershell");
        cmd.args(["-NoProfile", "-Command"]).arg(format!(
            "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{quoted}')"
        ));
        cmd
    } else if cfg!(target_os = "macos") {
        let mut cmd = std::process::Command::new("say");
        cmd.arg(text);
        cmd
    } else {
        let mut cmd = std::process::Command::new("spd-say");
        cmd.arg(text);
        cmd
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_new_screen_says_its_title_and_a_row_says_itself_once() {
        let mut n = Narrator::default();
        n.update(&Focus {
            screen_title: "Settings",
            screen_word: "screen",
            row: Some(("Music", "slider", "80%")),
            screen_changed: true,
            enabled: false,
        });
        assert_eq!(n.last_line, "Settings, screen");
        for _ in 0..2 {
            n.update(&Focus {
                screen_title: "Settings",
                screen_word: "screen",
                row: Some(("Music", "slider", "80%")),
                screen_changed: false,
                enabled: false,
            });
        }
        assert_eq!(n.last_line, "Music, slider, 80%");
    }
}
