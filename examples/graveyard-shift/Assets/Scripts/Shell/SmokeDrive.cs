// ---------------------------------------------------------------------------
// SmokeDrive.cs
// Purpose : Scripted runs of the front end for `dev.py smoke --drive <scenario>`: it presses the same actions a
//           player would (ui_down, ui_accept, ...) and prints markers dev.py, the tests and tools/access/sweep.py read.
// Usage   : python tools/dev.py smoke --drive menus                 # change two settings, Back, check the file
//           python tools/dev.py smoke --drive show:settings --screenshot Logs/settings.png
//           (show: title, settings, pause, subtitle, juice, credits)
//           python tools/dev.py smoke --drive access:res=1280x800,scale=2,pad   # every screen (tools/access/sweep.py)
//           python tools/dev.py smoke --drive pseudo --locale pseudo  # every label on every screen (pseudo-plant: must fail)
//           python tools/dev.py smoke --drive crash                   # a planted exception: CRASH_WRITTEN, exit 1 on purpose
//           python tools/dev.py smoke --drive bug                     # F8 on the main menu: the bug_<time>/ folder
// Notes   : Markers: DRIVE_DONE <scenario>, DRIVE_FAIL <scenario>: <why>, DRIVE_SHOWN <target>, SETTINGS_BEFORE /
//           SETTINGS_WRITTEN <path> ..., ACCESS_* JSON lines, PSEUDO_SCREEN / PSEUDO_FAIL / PSEUDO_PASS / PSEUDO_FAILED
//           (the lines and rules of LÖVE's pseudo drive), CRASH_WRITTEN <path> and BUG_REPORT <dir> (ShellReports),
//           DRIVE_BUG <dir>. Presses go through ShellInput.Inject, the path a key
//           or button takes, so a broken grid fails the run; in a pad run an action without a gamepad binding fails
//           it. Screen waits use real time (WAIT_MS): a PlayMode run's frame rate is whatever the machine gives.
//           Runs under the Smoke_ShellDrive PlayMode test (Assets/Tests/PlayMode/ShellSmokeTests.cs), which waits for
//           Finished and fails on Failed. The crash drive ends without DRIVE_DONE: its logged exception fails the
//           test on purpose (dev.py says so), and the crash file is the proof. The pseudo drive switches the run to
//           the pseudo locale when --locale pseudo was not given (DRIVE_NOTE).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): crash, pseudo, pseudo-plant, bug and show:juice (#275)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): show:credits (#284)
// ---------------------------------------------------------------------------
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using graveyard_shift.Core;
using graveyard_shift.Shell.Screens;

namespace graveyard_shift.Shell
{
    public sealed class SmokeDrive
    {
        // ---- Tunables ------------------------------------------------------------
        public const int MAX_NAV_STEPS = 30;         // bounds every "press until focused" loop
        public const float WAIT_S = 10f;             // real time a screen (or a subtitle line) gets to appear
        public const float HOLD_WAIT_S = 15f;        // real time a held line gets to reach its end
        public const int SETTLE_FRAMES = 20;         // frames a screen gets before it is photographed
        public const double TARGET_MASTER = 0.5;     // menus drives the master volume here from whatever the data folder held
        public const int MAX_SLIDER_STEPS = 40;
        public const int JUICE_SETTLE_FRAMES = 40;   // frames into the juice demo before a drive attacks
        public const float PLANT_WIDTH = 40f;        // pseudo-plant: a label this narrow cannot hold its text
        public static readonly string[] SHOW_TARGETS = { "title", "settings", "pause", "subtitle", "juice", "credits" };
        public static readonly string[] BUG_FILES = { "info.txt", "log_tail.txt", "settings.json" };
        public static readonly string[] ACCESS_ACTIONS = { "ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel", "pause" };
        public static readonly string[] PROMPT_ACTIONS = { "move_left", "move_right", "jump", "attack", "interact", "pause" };

        public bool Finished { get; private set; }
        public bool Failed { get; private set; }
        public string Why { get; private set; } = "";

        private readonly FrontEnd _front;
        private readonly string _scenario;
        private bool _pad;                 // access drive: press with the gamepad bindings instead of the keyboard's
        private float _textScale = 1f;
        private bool _read;                // access drive: readable font and double line spacing
        private Vector2Int _window;        // access drive: the window size to lay the screens out for
        private int _checked, _labels, _problems;   // pseudo drive: screens and labels checked, problems found

        public SmokeDrive(FrontEnd front, string scenario)
        {
            _front = front;
            _scenario = scenario;
        }

        private Shell S => Shell.I;

        public IEnumerator Run()
        {
            yield return null;    // the title has been built by Start()
            Debug.Log($"[INFO][drive] scenario {_scenario}");
            if (_scenario == "menus")
            {
                yield return Menus();
            }
            else if (_scenario.StartsWith("show:", StringComparison.Ordinal) && Array.IndexOf(SHOW_TARGETS, _scenario.Substring(5)) >= 0)
            {
                yield return Show(_scenario.Substring(5));
            }
            else if (_scenario == "access" || _scenario.StartsWith("access:", StringComparison.Ordinal))
            {
                yield return Access(_scenario.Length > 7 ? _scenario.Substring(7) : "");
            }
            else if (_scenario == "crash")
            {
                yield return Crash();
            }
            else if (_scenario == "pseudo" || _scenario == "pseudo-plant")
            {
                yield return Pseudo(_scenario == "pseudo-plant");
            }
            else if (_scenario == "bug")
            {
                yield return Bug();
            }
            else
            {
                Fail($"unknown scenario '{_scenario}' (menus, crash, pseudo, pseudo-plant, bug, "
                     + $"access[:res=WxH][,scale=N][,pad][,read], show:<{string.Join("|", SHOW_TARGETS)}>)");
            }
        }

        // ---- scenarios -----------------------------------------------------------------

        private IEnumerator Menus()
        {
            string file = S.PathOf(Shell.SETTINGS_FILE);
            double beforeMaster = GameSettings.Number(S.Settings, "audio", "master");
            bool beforeMotion = GameSettings.Bool(S.Settings, "access", "reduce_motion");
            Shell.Raw($"SETTINGS_BEFORE {file} master={Json.FormatNumber(beforeMaster)} reduce_motion={beforeMotion.ToString().ToLower()} "
                      + (System.IO.File.Exists(file) ? "(file exists)" : "(no file yet)"));
            yield return ToMainMenu();
            if (Failed) yield break;
            yield return NavTo("Settings", "ui_down");
            if (Failed) yield break;
            yield return Accept("settings");
            if (Failed) yield break;
            yield return NavTo("Tab_audio", "ui_right");
            if (Failed) yield break;
            yield return NavTo("Setting_audio_master", "ui_down");
            if (Failed) yield break;
            yield return SlideTo("audio", "master", TARGET_MASTER);
            if (Failed) yield break;
            yield return NavTo("Tab_audio", "ui_up");
            if (Failed) yield break;
            yield return NavTo("Tab_access", "ui_right");
            if (Failed) yield break;
            yield return NavTo("Setting_access_reduce_motion", "ui_down");
            if (Failed) yield break;
            yield return Press("ui_accept");
            yield return Press("ui_cancel");      // Back saves
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            SettingsLoadResult loaded = GameSettings.LoadFile(file);
            double master = GameSettings.Number(loaded.Settings, "audio", "master");
            bool motion = GameSettings.Bool(loaded.Settings, "access", "reduce_motion");
            Shell.Raw($"SETTINGS_WRITTEN {file} master={Json.FormatNumber(master)} reduce_motion={motion.ToString().ToLower()}");
            if (Math.Abs(master - TARGET_MASTER) > 1e-6 || motion == beforeMotion)
            {
                Fail($"settings file does not hold master={TARGET_MASTER} and reduce_motion={!beforeMotion}");
                yield break;
            }
            yield return NavTo("Quit", "ui_down");
            if (Failed) yield break;
            Shell.Raw("DRIVE_DONE menus");
            Finished = true;
            yield return Press("ui_accept");      // Quit: a player exits here
        }

        private IEnumerator Show(string target)
        {
            switch (target)
            {
                case "title":
                    yield return WaitScreen("title");
                    if (Failed) yield break;
                    yield return DismissConsent();
                    yield return Frames(SETTLE_FRAMES);
                    break;
                case "settings":
                    yield return ToMainMenu();
                    if (Failed) yield break;
                    yield return NavTo("Settings", "ui_down");
                    if (Failed) yield break;
                    yield return Accept("settings");
                    if (Failed) yield break;
                    yield return NavTo("Tab_audio", "ui_right");
                    if (Failed) yield break;
                    yield return NavTo("Setting_audio_master", "ui_down");
                    if (Failed) yield break;
                    yield return Frames(SETTLE_FRAMES);
                    break;
                case "pause":
                    yield return ToPlay();
                    if (Failed) yield break;
                    yield return Frames(SETTLE_FRAMES);
                    yield return Press("pause");
                    yield return WaitScreen("pause");
                    if (Failed) yield break;
                    yield return Frames(SETTLE_FRAMES);
                    break;
                case "subtitle":
                    yield return ToPlay();
                    if (Failed) yield break;
                    yield return WaitSubtitle();
                    if (Failed) yield break;
                    yield return Frames(SETTLE_FRAMES);
                    break;
                case "juice":
                    yield return ToJuice();
                    if (Failed) yield break;
                    yield return Frames(JUICE_SETTLE_FRAMES);
                    yield return Press("attack");          // the hit: shake, squash, flash and the bark in the picture
                    break;
                case "credits":
                    yield return ToMainMenu();
                    if (Failed) yield break;
                    yield return NavTo("Credits", "ui_down");
                    if (Failed) yield break;
                    yield return Accept("credits");
                    if (Failed) yield break;
                    yield return Frames(SETTLE_FRAMES);
                    break;
            }
            Shell.Raw("DRIVE_SHOWN " + target);
            Done();
        }

        // ---- crash files, the bug report, the pseudo-locale check (#275) ---------------------

        /// <summary>An unhandled exception in a frame, as a bug would throw: the crash file must be written.</summary>
        private IEnumerator Crash()
        {
            yield return ToMainMenu();
            if (Failed) yield break;
            yield return Frames(2);
            Debug.Log("[INFO][drive] planting an unhandled exception (expected): the crash file is the proof");
            _front.PlantCrash = true;
            float start = Time.realtimeSinceStartup;
            while (ShellReports.CrashFile == "" && Time.realtimeSinceStartup - start < WAIT_S)
            {
                yield return null;
            }
            yield return Frames(2);                // ShellReports.Tick logs CRASH_WRITTEN
            if (ShellReports.CrashFile == "" || !System.IO.File.Exists(ShellReports.CrashFile))
            {
                Fail("no crash file was written for the planted exception");
                yield break;
            }
            Finished = true;                       // no DRIVE_DONE: a crash run fails on purpose
        }

        /// <summary>F8 on the main menu: bug_<time>/ with the info, log tail and settings (and a screenshot when the
        /// run has a graphics device).</summary>
        private IEnumerator Bug()
        {
            yield return ToMainMenu();
            if (Failed) yield break;
            ShellInput.InjectKey("key:" + ShellReports.BUG_REPORT_KEY);
            float start = Time.realtimeSinceStartup;
            while (ShellReports.LastBugReport == "" && Time.realtimeSinceStartup - start < WAIT_S)
            {
                yield return null;
            }
            yield return Frames(2);
            string dir = ShellReports.LastBugReport;
            if (dir == "")
            {
                Fail("F8 saved no bug report (the key works in the editor and development builds only)");
                yield break;
            }
            var want = new List<string>(BUG_FILES);
            if (SystemInfo.graphicsDeviceType != UnityEngine.Rendering.GraphicsDeviceType.Null)
            {
                want.Add("screenshot.png");
            }
            foreach (string f in want)
            {
                if (!System.IO.File.Exists(System.IO.Path.Combine(dir, f)))
                {
                    Fail($"the bug report lacks {f}: {dir}");
                    yield break;
                }
            }
            Shell.Raw("DRIVE_BUG " + dir);
            Done();
        }

        /// <summary>Every screen in the pseudo locale, every visible label checked (AccessAudit.PseudoProblems).
        /// plant: one label on the main menu too narrow for its text, which the check must name.</summary>
        private IEnumerator Pseudo(bool plant)
        {
            if (S.Locale != Shell.PSEUDO_LOCALE)
            {
                S.OverrideLocale(Shell.PSEUDO_LOCALE);
                Shell.Raw("DRIVE_NOTE the pseudo drive switched the locale to pseudo (pass --locale pseudo next time)");
            }
            yield return WaitScreen("title");
            if (Failed) yield break;
            yield return Frames(3);
            if (_front.Top() is TitleScreen title && title.ConsentOpen)
            {
                Check("consent");
                yield return DismissConsent();
                yield return Frames(3);
            }
            Check("title");
            yield return Press("ui_accept");
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            if (plant)
            {
                var planted = new UnityEngine.UIElements.Label(S.T("menu.settings")) { name = "PlantedLabel" };
                UiTheme.Text(planted, 1.0f, UiTheme.TEXT, false);
                planted.style.position = UnityEngine.UIElements.Position.Absolute;
                planted.style.left = 8;
                planted.style.top = 8;
                planted.style.width = PLANT_WIDTH;
                planted.style.overflow = UnityEngine.UIElements.Overflow.Hidden;
                _front.Top().Root.Add(planted);
            }
            yield return Frames(3);
            Check("main_menu");
            yield return NavTo("Settings", "ui_down");
            if (Failed) yield break;
            yield return Accept("settings");
            if (Failed) yield break;
            foreach (string tab in SettingsScreen.TABS)
            {
                yield return NavTo("Tab_" + tab, "ui_right");
                if (Failed) yield break;
                yield return Frames(3);
                Check("settings." + tab);
                if (tab == "controls")
                {
                    yield return NavTo("Bind_jump_0", "ui_down");
                    if (Failed) yield break;
                    yield return Press("ui_accept");        // the "press a key" prompt
                    yield return Frames(3);
                    Check("settings.capture");
                    ShellInput.InjectKey("key:escape");     // cancels the capture
                    yield return Frames(3);
                    yield return NavTo("Tab_controls", "ui_up");
                    if (Failed) yield break;
                }
            }
            yield return Press("ui_cancel");
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            yield return NavTo("Credits", "ui_down");
            if (Failed) yield break;
            yield return Accept("credits");
            if (Failed) yield break;
            yield return Frames(3);
            Check("credits");
            yield return Press("ui_cancel");
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            if (JuiceWorld.Available)
            {
                yield return NavTo("JuiceDemo", "ui_up");
                if (Failed) yield break;
                yield return Press("ui_accept");
                if (_front.CurrentName() == "loading")
                {
                    Check("loading");
                }
                yield return WaitScreen("juice");
                if (Failed) yield break;
                yield return Frames(JUICE_SETTLE_FRAMES);
                Check("juice");
                yield return Press("attack");
                yield return Frames(3);
                Check("juice.hit");
                yield return Press("pause");
                yield return WaitScreen("pause");
                if (Failed) yield break;
                yield return Frames(3);
                Check("pause.juice");
                yield return NavTo("QuitToTitle", "ui_down");
                if (Failed) yield break;
                yield return Press("ui_accept");
                yield return WaitScreen("title");
                if (Failed) yield break;
                yield return Press("ui_accept");
                yield return WaitScreen("main_menu");
                if (Failed) yield break;
            }
            yield return NavTo("Play", "ui_up");
            if (Failed) yield break;
            yield return Accept("play");
            if (Failed) yield break;
            yield return WaitSubtitle();
            if (Failed) yield break;
            yield return Frames(3);
            Check("play");
            yield return Press("pause");
            yield return WaitScreen("pause");
            if (Failed) yield break;
            yield return Frames(3);
            Check("pause");
            foreach ((string button, string screen) in new[] { ("Help", "help"), ("History", "history") })
            {
                yield return NavTo(button, "ui_down");
                if (Failed) yield break;
                yield return Accept(screen);
                if (Failed) yield break;
                yield return Frames(3);
                Check(screen);
                yield return Press("ui_cancel");
                yield return WaitScreen("pause");
                if (Failed) yield break;
            }
            yield return NavTo("QuitToTitle", "ui_down");
            if (Failed) yield break;
            yield return Press("ui_accept");
            yield return WaitScreen("title");
            if (Failed) yield break;
            if (_problems == 0)
            {
                Shell.Raw($"PSEUDO_PASS {_checked} screens, {_labels} labels, nothing truncated or untranslated");
                Done();
            }
            else
            {
                Shell.Raw($"PSEUDO_FAILED {_problems} problem(s) on {_checked} screens");
                Fail($"{_problems} label problem(s); see the PSEUDO_FAIL lines");
            }
        }

        /// <summary>The pseudo check of what is on screen now: PSEUDO_SCREEN, then a PSEUDO_FAIL line per problem.</summary>
        private void Check(string where)
        {
            List<(string Node, string Text, string Why)> problems = AccessAudit.PseudoProblems(_front, out int labels);
            _checked++;
            _labels += labels;
            Shell.Raw($"PSEUDO_SCREEN {where} labels {labels} problems {problems.Count}");
            foreach ((string node, string text, string why) in problems)
            {
                _problems++;
                Shell.Raw($"PSEUDO_FAIL {where} label {node}: {why} ({Json.Stringify(text)})");
            }
        }

        // ---- the accessibility sweep (#91, #85) ----------------------------------------

        /// <summary>access[:res=WxH][,scale=N][,pad][,read]: every screen reported for tools/access/sweep.py.</summary>
        private IEnumerator Access(string options)
        {
            foreach (string part in options.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (part == "pad")
                {
                    _pad = true;
                }
                else if (part == "read")
                {
                    _read = true;
                }
                else if (part.StartsWith("scale=", StringComparison.Ordinal))
                {
                    float.TryParse(part.Substring(6), System.Globalization.NumberStyles.Float,
                                   System.Globalization.CultureInfo.InvariantCulture, out _textScale);
                }
                else if (part.StartsWith("res=", StringComparison.Ordinal))
                {
                    string[] wh = part.Substring(4).Split('x');
                    if (wh.Length == 2 && int.TryParse(wh[0], out int w) && int.TryParse(wh[1], out int h))
                    {
                        _window = new Vector2Int(w, h);
                    }
                }
            }
            Shell.Raw("ACCESS_INPUT " + Json.Stringify(new Dictionary<string, object>
            {
                { "pad", _pad }, { "text_scale", (double)_textScale }, { "actions", AccessAudit.InputReport(ACCESS_ACTIONS) },
            }));
            yield return WaitScreen("title");
            if (Failed) yield break;
            if (_window != Vector2Int.zero)
            {
                _front.SetWindow(_window.x, _window.y);
                yield return Frames(2);
            }
            if (Math.Abs(_textScale - 1f) > 1e-6)
            {
                S.SetValue("access", "text_scale", (double)_textScale);
            }
            if (_read)
            {
                S.SetValue("access", "readable_font", true);
                S.SetValue("access", "line_spacing", 2.0);
            }
            yield return Frames(SETTLE_FRAMES);
            Report("title");
            yield return DismissConsent();
            yield return Frames(2);
            yield return Press("ui_accept");
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            yield return Frames(3);
            Report("main_menu");
            yield return NavTo("Settings", "ui_down");
            if (Failed) yield break;
            yield return Accept("settings");
            if (Failed) yield break;
            foreach (string tab in SettingsScreen.TABS)
            {
                yield return NavTo("Tab_" + tab, "ui_right");
                if (Failed) yield break;
                yield return Frames(3);
                Report("settings/" + tab);
                if (tab == "controls")
                {
                    yield return CheckPreset();
                    if (Failed) yield break;
                    yield return NavTo("Tab_controls", "ui_up");
                    if (Failed) yield break;
                }
            }
            yield return Press("ui_cancel");
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            yield return NavTo("Credits", "ui_down");
            if (Failed) yield break;
            yield return Accept("credits");
            if (Failed) yield break;
            yield return Frames(3);
            Report("credits");
            yield return Press("ui_cancel");
            yield return WaitScreen("main_menu");
            if (Failed) yield break;
            yield return NavTo("Play", "ui_up");
            if (Failed) yield break;
            yield return Accept("play");
            if (Failed) yield break;
            yield return WaitSubtitle();
            if (Failed) yield break;
            yield return Frames(3);
            Report("play");
            Shell.Raw("ACCESS_SUBTITLE " + Json.Stringify(_front.World.Subtitles.Shown()));
            ReportPrompts();
            yield return CheckHold();
            yield return Press("pause");
            yield return WaitScreen("pause");
            if (Failed) yield break;
            yield return Frames(3);
            Report("pause");
            foreach ((string button, string screen) in new[] { ("Help", "help"), ("History", "history") })   // #167
            {
                yield return NavTo(button, "ui_down");
                if (Failed) yield break;
                yield return Accept(screen);
                if (Failed) yield break;
                yield return Frames(3);
                Report(screen);
                yield return Press("ui_cancel");
                yield return WaitScreen("pause");
                if (Failed) yield break;
            }
            yield return NavTo("QuitToTitle", "ui_down");
            if (Failed) yield break;
            yield return Press("ui_accept");
            yield return WaitScreen("title");
            if (Failed) yield break;
            Done();
        }

        /// <summary>The one-handed layout (#166), live: reached with the run's device, applied, then reset.</summary>
        private IEnumerator CheckPreset()
        {
            yield return NavTo("ResetBindings", "ui_down");
            if (Failed) yield break;
            yield return NavTo("Preset_one_hand_left", "ui_right");
            if (Failed) yield break;
            yield return Press("ui_accept");
            yield return Frames(2);
            bool applied = FirstBinding("attack") == "key:f";
            yield return NavTo("ResetBindings", "ui_left");
            if (Failed) yield break;
            yield return Press("ui_accept");
            yield return Frames(2);
            Shell.Raw("ACCESS_PRESET " + Json.Stringify(new Dictionary<string, object>
            {
                { "applied", applied }, { "reset", FirstBinding("attack") == "key:j" },
            }));
        }

        /// <summary>subtitle_hold (#167), live: a finished line stays until accept, then goes.</summary>
        private IEnumerator CheckHold()
        {
            SubtitleBar bar = _front.World.Subtitles;
            S.SetValue("access", "subtitle_hold", true);
            bar.Play(PlayWorld.INTRO_LINE);
            float start = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - start < HOLD_WAIT_S && !bar.IsHeld && bar.IsPlaying)
            {
                yield return null;
            }
            bool held = bar.IsPlaying && bar.IsHeld;
            ShellInput.Inject("ui_accept", null);    // a real press: the bar reads it on its next Tick
            yield return Frames(3);
            Shell.Raw("ACCESS_HOLD " + Json.Stringify(new Dictionary<string, object>
            {
                { "held", held }, { "dismissed", !bar.IsPlaying },
            }));
            S.SetValue("access", "subtitle_hold", false);
        }

        private void Report(string where)
        {
            Shell.Raw("ACCESS_SCREEN " + Json.Stringify(AccessAudit.Screen(_front, where)));
        }

        /// <summary>The play hints: for each action, the keyboard text and the text shown now, on the device in use.</summary>
        private void ReportPrompts()
        {
            var rows = new Dictionary<string, object>();
            foreach (string action in PROMPT_ACTIONS)
            {
                string key = Bindings.PromptBinding(S.BindingsMap(), action, "keyboard");
                rows[action] = new Dictionary<string, object>
                {
                    { "keyboard", S.BindingText(key, "keyboard") }, { "shown", S.BindingText(S.PromptFor(action)) },
                };
            }
            Shell.Raw("ACCESS_PROMPTS " + Json.Stringify(new Dictionary<string, object>
            {
                { "device", ShellInput.LastDevice }, { "glyphs", S.GlyphSet() }, { "actions", rows },
            }));
        }

        private string FirstBinding(string action)
        {
            List<string> slots = Bindings.Of(S.BindingsMap(), action);
            return slots.Count > 0 ? slots[0] : "";
        }

        // ---- steps -----------------------------------------------------------------------

        private IEnumerator ToMainMenu()
        {
            yield return WaitScreen("title");
            if (Failed) yield break;
            yield return DismissConsent();
            yield return Frames(2);
            yield return Press("ui_accept");      // "press any key"
            yield return WaitScreen("main_menu");
        }

        private IEnumerator ToJuice()
        {
            yield return ToMainMenu();
            if (Failed) yield break;
            if (!JuiceWorld.Available)
            {
                Fail("the juice demo is on the main menu in the editor and development builds only");
                yield break;
            }
            yield return NavTo("JuiceDemo", "ui_down");
            if (Failed) yield break;
            yield return Press("ui_accept");
            yield return WaitScreen("juice");
        }

        private IEnumerator ToPlay()
        {
            yield return ToMainMenu();
            if (Failed) yield break;
            yield return Accept("play");          // Play has focus first
        }

        private IEnumerator DismissConsent()
        {
            if (_front.Top() is TitleScreen title && title.ConsentOpen)
            {
                yield return NavTo("Later", "ui_right");
                if (Failed) yield break;
                yield return Press("ui_accept");
                yield return Frames(2);
            }
        }

        private IEnumerator Accept(string nextScreen)
        {
            yield return Press("ui_accept");
            yield return WaitScreen(nextScreen);
        }

        /// <summary>A press through the real action path; in a pad run, the action must have a gamepad binding.</summary>
        private IEnumerator Press(string action)
        {
            if (_pad)
            {
                if (!ShellInput.HasGamepad(action))
                {
                    Fail($"{action} has no gamepad binding: a gamepad-only player cannot press it");
                    yield break;
                }
                ShellInput.Inject(action, "pad_xbox");
            }
            else
            {
                ShellInput.Inject(action, ShellInput.HasKeyboard(action) ? "keyboard" : null);
            }
            yield return Frames(2);
        }

        /// <summary>Press action until the control named name has focus.</summary>
        private IEnumerator NavTo(string name, string action)
        {
            for (int i = 0; i < MAX_NAV_STEPS; i++)
            {
                if (_front.Top()?.Focused?.Name == name)
                {
                    yield break;
                }
                yield return Press(action);
                if (Failed) yield break;
            }
            Fail($"could not reach '{name}' with {action} (focus is on {_front.Top()?.Focused?.Name ?? "nothing"})");
        }

        /// <summary>Press left or right on the focused slider until the live setting equals target.</summary>
        private IEnumerator SlideTo(string section, string field, double target)
        {
            for (int i = 0; i < MAX_SLIDER_STEPS; i++)
            {
                double now = GameSettings.Number(S.Settings, section, field);
                if (Math.Abs(now - target) <= 1e-6)
                {
                    yield break;
                }
                yield return Press(now > target ? "ui_left" : "ui_right");
            }
            Fail($"{section}.{field} did not reach {target} (is {GameSettings.Number(S.Settings, section, field)})");
        }

        private IEnumerator WaitScreen(string screen)
        {
            float start = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - start < WAIT_S)
            {
                if (_front.CurrentName() == screen)
                {
                    yield return Frames(2);
                    yield break;
                }
                yield return null;
            }
            Fail($"screen '{screen}' did not appear (now: '{_front.CurrentName()}')");
        }

        private IEnumerator WaitSubtitle()
        {
            float start = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - start < WAIT_S)
            {
                if (_front.World != null && _front.World.Subtitles.IsFullyShown)
                {
                    yield break;
                }
                yield return null;
            }
            Fail("the sample line did not show in full (subtitles off, or the dialogue file is missing)");
        }

        private static IEnumerator Frames(int n)
        {
            for (int i = 0; i < n; i++)
            {
                yield return null;
            }
        }

        private void Done()
        {
            Shell.Raw("DRIVE_DONE " + _scenario);
            Finished = true;
        }

        private void Fail(string why)
        {
            if (Failed)
            {
                return;
            }
            Why = why;
            Failed = true;
            Finished = true;
            Shell.Raw($"DRIVE_FAIL {_scenario}: {why}");
        }
    }
}
