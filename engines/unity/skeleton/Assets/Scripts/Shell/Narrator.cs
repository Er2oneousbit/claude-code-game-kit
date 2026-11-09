// ---------------------------------------------------------------------------
// Narrator.cs
// Purpose : Menu narration (#165): every focus change, value change and screen says a short line ("Music volume,
//           slider, 70 percent"), so a blind or low-vision player can use the title, settings and pause screens.
// Usage   : FrontEnd owns one: narrator.OnScreen(screen); narrator.OnFocus(control); narrator.Tick()
//           Narrator.Describe(control) is the line for any control (the access drive reports it for every control,
//           and tools/access/sweep.py fails a control that says "unlabelled").
// Notes   : The line is always worked out (Shell.LastNarration); it is spoken only with access.narration on. Unity
//           has no speech of its own, so the operating system's is used from a child process the game never waits
//           for: Windows' speech synthesizer through PowerShell, macOS `say`, Linux `spd-say` (speech-dispatcher).
//           A new line ends the one still speaking. Only Windows was tried (verify on macOS and Linux). Nothing is
//           spoken in batchmode (a headless run), as on the other engines. Role and on/off words come from the
//           string tables (narrate.*).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System;
using System.Diagnostics;
using UnityEngine;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public sealed class Narrator
    {
        private static readonly string[] ROLES = { "button", "toggle", "slider", "choice", "binding" };

        private Control _focused;
        private string _line = "";
        private Process _speech;

        /// <summary>The line a control says: its label, its role, its value.</summary>
        public static string Describe(Control c)
        {
            Shell s = Shell.I;
            if (c == null || s == null)
            {
                return "";
            }
            string role = Array.IndexOf(ROLES, c.Kind) >= 0 ? s.T("narrate." + (c.Kind == "binding" ? "button" : c.Kind)) : "";
            string value = c.Value != null ? c.Value() : "";
            if (c.Kind == "toggle")
            {
                // the value is On/Off text already; say the narrate.* word for it, as the other engines do
                value = value == s.T("value.on") ? s.T("narrate.on") : value == s.T("value.off") ? s.T("narrate.off") : value;
            }
            return Bindings.NarrationLine(c.Label, role, value);
        }

        public void OnScreen(ShellScreen screen)
        {
            if (screen == null || Shell.I == null)
            {
                return;
            }
            var heading = screen.Root?.Q<UnityEngine.UIElements.Label>("Heading") ?? screen.Root?.Q<UnityEngine.UIElements.Label>("Title");
            Say(Bindings.NarrationLine(heading != null ? heading.text : screen.Name, Shell.I.T("narrate.screen")));
        }

        public void OnFocus(Control c)
        {
            _focused = c;
            Say(Describe(c));
        }

        /// <summary>A value that changes under focus (a slider moved, a toggle flipped) is said again.</summary>
        public void Tick()
        {
            if (_focused == null)
            {
                return;
            }
            string now = Describe(_focused);
            if (now != _line)
            {
                Say(now);
            }
        }

        private void Say(string line)
        {
            _line = line;
            Shell.I.LastNarration = line;
            if (!Shell.I.AccessOn("narration") || Application.isBatchMode || string.IsNullOrEmpty(line))
            {
                return;
            }
            Speak(line);
        }

        private void Speak(string text)
        {
            try
            {
                if (_speech != null && !_speech.HasExited)
                {
                    _speech.Kill();      // the new line interrupts the old one
                }
            }
            catch (InvalidOperationException)
            {
            }
            string file, args;
            if (Application.platform == RuntimePlatform.WindowsPlayer || Application.platform == RuntimePlatform.WindowsEditor)
            {
                string quoted = text.Replace("'", "''").Replace("\"", "");
                file = "powershell";
                args = "-NoProfile -Command \"Add-Type -AssemblyName System.Speech; "
                       + "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('" + quoted + "')\"";
            }
            else
            {
                string quoted = "'" + text.Replace("'", "'\\''") + "'";
                bool mac = Application.platform == RuntimePlatform.OSXPlayer || Application.platform == RuntimePlatform.OSXEditor;
                file = mac ? "say" : "spd-say";
                args = quoted;
            }
            try
            {
                _speech = Process.Start(new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true });
            }
            catch (Exception e) when (e is InvalidOperationException || e is System.ComponentModel.Win32Exception)
            {
                UnityEngine.Debug.LogWarning($"[WARN][narrator] no system speech ({file}): {e.Message}");
                _speech = null;
            }
        }
    }
}

// {{FOOTER}}
