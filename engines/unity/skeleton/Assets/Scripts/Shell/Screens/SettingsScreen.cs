// ---------------------------------------------------------------------------
// SettingsScreen.cs
// Purpose : The settings screen: tabs for Display, Audio, Controls, Accessibility, Language and Privacy, one row per
//           settings field (built from GameSettings.Fields, the schema), rebinding with "press a key", conflicts
//           shown as swaps, the one-handed layouts (#166) and Reset to defaults. Back (or cancel) saves settings.json.
//           The Display tab waits for Apply (#308): its rows stage through Core's DisplayStaging, Apply (next to Back,
//           enabled while a change waits) sets the changed fields and saves, and a new window mode or size asks
//           "Keep these display settings? Reverting in N s" (Keep focused, 15 real seconds, then it reverts).
// Usage   : front.OpenSettings()   (from the main menu or the pause menu)
// Notes   : Changes apply at once (Shell.SetValue), Display's on Apply; Back writes the file, and with Display
//           changes waiting it warns once (settings.unapplied), the second Back discards them. The confirm counts on
//           a Stopwatch: real time, whatever Time.timeScale (0 in the pause menu) or the frame rate. Focus: left/right on the tab row picks a
//           tab, down enters it, up from the first row returns to the tabs; sliders and choices use left/right,
//           switches use accept. While a binding waits for input, Escape (or REBIND_TIMEOUT_S) cancels. Slot 0 takes
//           keys and mouse buttons, slot 1 pad input. Field names come from the strings setting.<section>.<field>;
//           choices from value.<field>.<choice>. Rows wrap, so at 200 % text a control drops under its label
//           instead of running off the screen.
//
// Pseudocode:
//   build: heading, tab buttons (one grid row), a scroll area holding the current tab's rows, Back, a status line
//   tab rows: per schema field a label + control (switch / slider + value / choice); Controls adds one row per
//     action: name, keyboard slot, pad slot; then Reset and the one-handed presets on one row
//   display rows: show and stage DisplayStaging values; Apply -> SetValue per call (mode first) -> save -> confirm?
//   confirm: Tick(real dt) counts down; Keep closes; Revert, cancel or running out -> SetValue the old values, save
//   Back: confirm open -> revert; Display changes waiting -> warn once; else save and leave
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the Display tab's Apply, its hint line and the
//           keep-or-revert confirm on a real-time clock; Back warns once about unapplied Display changes (#308)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell.Screens
{
    public sealed class SettingsScreen : ShellScreen
    {
        // ---- Tunables ------------------------------------------------------------
        public static readonly string[] TABS = { "display", "audio", "controls", "access", "language", "privacy" };
        public static readonly Dictionary<string, string> TAB_SECTIONS = new Dictionary<string, string>
        {
            { "display", "display" }, { "audio", "audio" }, { "access", "access" },
        };
        public static readonly string[] CONTROLS_FIELDS = { "deadzone", "invert_y", "glyphs" };
        public static readonly string[] ACTION_ORDER =
        {
            "move_left", "move_right", "move_up", "move_down", "jump", "attack", "interact", "pause",
            "ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel",
        };
        public static readonly string[] PRESET_NAMES = { "one_hand_left", "one_hand_right" };   // #166
        private static readonly Dictionary<string, double> STEPS = new Dictionary<string, double>
        {
            { "display.ui_scale", 0.25 }, { "access.text_scale", 0.25 }, { "access.line_spacing", 0.25 },
            { "access.timing_scale", 0.25 },
        };
        private const double DEFAULT_STEP = 0.05;
        private static readonly string[] TIMES_FIELDS = { "display.ui_scale", "access.text_scale", "access.line_spacing", "access.timing_scale" };
        private static readonly List<object> RESOLUTIONS = new List<object>
        {
            new List<object> { 1280.0, 720.0 }, new List<object> { 1600.0, 900.0 }, new List<object> { 1920.0, 1080.0 },
            new List<object> { 2560.0, 1440.0 }, new List<object> { 3840.0, 2160.0 },
        };
        public const float REBIND_TIMEOUT_S = 6f;
        private const float LABEL_MIN_WIDTH = 160f;
        private const float BIND_MIN_WIDTH = 150f;

        private string _tab = "display";
        private readonly Dictionary<string, Control> _tabButtons = new Dictionary<string, Control>();
        private VisualElement _rows;
        private ScrollView _scroll;
        private Control _back;
        private Label _status;
        private string _statusText = "";
        private (string action, int slot)? _capture;
        private float _captureLeft;
        private readonly List<List<Control>> _tabGrid = new List<List<Control>>();   // the current tab's rows
        // the Display tab's Apply (#308)
        private readonly DisplayStaging _staging;
        private readonly System.Diagnostics.Stopwatch _clock = System.Diagnostics.Stopwatch.StartNew();   // real time
        private double _lastReal;
        private Control _apply;
        private VisualElement _confirm;
        private Label _confirmText;
        private Control _keep, _revert;
        private string _message = "";       // Back's warning about unapplied Display changes

        public SettingsScreen(FrontEnd front) : base(front, "settings")
        {
            _staging = new DisplayStaging((Dictionary<string, object>)Shell.I.Settings["display"]);
        }

        public string CurrentTab => _tab;
        public bool Capturing => _capture.HasValue;
        public DisplayStaging Staging => _staging;
        public bool Confirming => _staging.Confirming;
        public string StatusText => _status != null ? _status.text : "";

        protected override void BuildContent()
        {
            _confirm = null;
            VisualElement col = Column();
            Heading(col, S.T("settings.title"));
            var tabs = new VisualElement { name = "Tabs" };       // wraps: at 200 % text the six tabs take two lines
            tabs.style.flexDirection = FlexDirection.Row;
            tabs.style.flexWrap = Wrap.Wrap;
            tabs.style.flexShrink = 0;
            col.Add(tabs);
            _tabButtons.Clear();
            var tabRow = new List<Control>();
            foreach (string tab in TABS)
            {
                string t = tab;
                Control b = Button(tabs, S.T("settings.tab." + tab), "Tab_" + tab, () => SelectTab(t, true));
                _tabButtons[tab] = b;
                tabRow.Add(b);
            }
            _scroll = Scroll(col);
            _rows = new VisualElement { name = "Rows" };
            _rows.style.flexDirection = FlexDirection.Column;
            _scroll.Add(_rows);
            var bottom = new VisualElement { name = "Bottom" };
            bottom.style.flexDirection = FlexDirection.Row;
            bottom.style.flexWrap = Wrap.Wrap;
            bottom.style.alignItems = Align.Center;
            bottom.style.marginTop = 8f;
            bottom.style.flexShrink = 0;
            col.Add(bottom);
            _apply = Button(bottom, S.T("settings.apply"), "Apply", ApplyDisplay);   // the Display tab only (#308)
            _back = Button(bottom, S.T("settings.back"), "Back", BackPressed);
            _status = Text(bottom, "", "Status");       // rebinding messages: next to Back, always on screen
            _status.style.color = UiTheme.FOCUS;
            _status.style.flexGrow = 1;
            _status.style.flexShrink = 1;
            _status.style.marginBottom = 0;
            FillTab(tabRow);
            if (_staging.Confirming)
            {
                BuildConfirm();                         // a rebuild during the confirm keeps it on screen
            }
        }

        public override void FocusFirst()
        {
            if (_staging.Confirming && _keep != null)
            {
                Focus(_keep);
                return;
            }
            Focus(_tabButtons[_tab]);
        }

        public override void OnCancel()
        {
            if (Capturing)
            {
                EndCapture("");
            }
            else
            {
                BackPressed();
            }
        }

        public override bool HandleAction(string action)
        {
            if (Capturing)
            {
                return true;        // every press is for the binding (or Escape, read in Tick)
            }
            if (_staging.Confirming)
            {
                switch (action)                  // the confirm takes every press: Keep or Revert, cancel reverts
                {
                    case "ui_cancel": RevertDisplay(); break;
                    case "ui_accept": Focused?.Activate?.Invoke(); break;
                    case "ui_up":
                    case "ui_down":
                    case "ui_left":
                    case "ui_right": Focus(Focused == _keep ? _revert : _keep); break;
                }
                return true;
            }
            bool onTabs = Focused != null && Focused.Name.StartsWith("Tab_", StringComparison.Ordinal);
            if (onTabs && (action == "ui_left" || action == "ui_right"))
            {
                int i = Array.IndexOf(TABS, _tab);
                SelectTab(TABS[(i + (action == "ui_left" ? -1 : 1) + TABS.Length) % TABS.Length], true);
                return true;
            }
            bool handled = base.HandleAction(action);
            // up from the first row or down past Back lands on the tab row: on the current tab, not on the tab at
            // that column (a tab takes effect when it is focused, as on the other engines)
            if (handled && Focused != null && Focused.Name.StartsWith("Tab_", StringComparison.Ordinal) && Focused != _tabButtons[_tab])
            {
                Focus(_tabButtons[_tab]);
            }
            return handled;
        }

        public override void Tick(float dt)
        {
            double now = _clock.Elapsed.TotalSeconds;  // real seconds: not Time.deltaTime, not paused by timeScale 0
            double real = now - _lastReal;
            _lastReal = now;
            if (_staging.Confirming)
            {
                List<(string Field, object Value)> calls = _staging.Tick(real);
                if (_staging.Confirming)
                {
                    _confirmText.text = ConfirmText();
                }
                else
                {
                    SetDisplay(calls);                  // ran out: the old values are back
                    CloseConfirm();
                }
            }
            if (!Capturing)
            {
                return;
            }
            string got = ShellInput.CaptureBinding(_capture.Value.slot);
            if (got == "key:escape")
            {
                EndCapture("");
                return;
            }
            if (got != null)
            {
                EndCapture(got);
                return;
            }
            _captureLeft -= dt;
            if (_captureLeft <= 0f)
            {
                EndCapture("");
            }
        }

        private void Close()
        {
            if (Capturing)
            {
                EndCapture("");
            }
            S.SaveSettings();
            Front.Back();
        }

        // ---- the Display tab's Apply (#308) ---------------------------------------------------

        /// <summary>Back (the button or cancel, from any tab): reverts an open confirm, warns once about Display
        /// changes that wait for Apply, else saves and leaves (discarding them).</summary>
        private void BackPressed()
        {
            if (Capturing)
            {
                EndCapture("");
                return;
            }
            if (_staging.Confirming)
            {
                RevertDisplay();
                return;
            }
            string what = _staging.Back().What;      // "leave" or "warn" here: the confirm is closed
            if (what == "warn")
            {
                _message = S.T("settings.unapplied");
                _status.text = _message;
                return;
            }
            _message = "";
            Close();
        }

        private void StageDisplay(string field, object value)
        {
            bool had = _staging.HasPending;
            _staging.Stage(field, value);
            _message = "";
            if (had != _staging.HasPending)
            {
                Refill(Focused?.Name ?? "");             // Apply joins (or leaves) the focus grid
            }
            else
            {
                _status.text = "";
            }
        }

        private void ApplyDisplay()
        {
            if (!_staging.HasPending || _staging.Confirming)
            {
                return;                                  // disabled: nothing waits
            }
            SetDisplay(_staging.Apply());
            if (_staging.Confirming)
            {
                _lastReal = _clock.Elapsed.TotalSeconds;
                Refill("Back");
                BuildConfirm();
                Focus(_keep);                            // Keep is focused: one press keeps what the player sees
            }
            else
            {
                Refill("Back");
            }
        }

        /// <summary>Sets each (field, value) through Shell.SetValue in the order given (mode before resolution), then
        /// saves settings.json.</summary>
        private void SetDisplay(List<(string Field, object Value)> calls)
        {
            if (calls.Count == 0)
            {
                return;
            }
            foreach ((string field, object value) in calls)
            {
                S.SetValue("display", field, value);
            }
            S.SaveSettings();
        }

        private void KeepDisplay()
        {
            _staging.Keep();
            CloseConfirm();
        }

        private void RevertDisplay()
        {
            SetDisplay(_staging.Revert());
            CloseConfirm();
        }

        private string ConfirmText()
        {
            return S.T("settings.confirm", new Dictionary<string, object> { { "secs", _staging.Seconds() ?? 0 } });
        }

        /// <summary>"Keep these display settings? Reverting in N s" with Keep and Revert, over the screen.</summary>
        private void BuildConfirm()
        {
            _confirm = new VisualElement { name = "Confirm" };
            _confirm.style.position = Position.Absolute;
            _confirm.style.left = 0;
            _confirm.style.top = 0;
            _confirm.style.right = 0;
            _confirm.style.bottom = 0;
            _confirm.style.backgroundColor = UiTheme.BACKDROP;
            _confirm.style.justifyContent = Justify.Center;
            _confirm.style.alignItems = Align.Center;
            var panel = new VisualElement { name = "ConfirmPanel" };
            UiTheme.Panel(panel, UiTheme.PANEL, 24f);
            panel.style.maxWidth = Length.Percent(80);
            panel.style.alignItems = Align.Center;
            _confirm.Add(panel);
            _confirmText = Text(panel, ConfirmText(), "ConfirmText");
            var buttons = new VisualElement { name = "ConfirmButtons" };
            buttons.style.flexDirection = FlexDirection.Row;
            buttons.style.flexWrap = Wrap.Wrap;
            buttons.style.justifyContent = Justify.Center;
            panel.Add(buttons);
            _keep = Button(buttons, S.T("settings.keep"), "Keep", KeepDisplay);
            _revert = Button(buttons, S.T("settings.revert"), "Revert", RevertDisplay);
            Root.Add(_confirm);
        }

        private void CloseConfirm()
        {
            _confirm?.RemoveFromHierarchy();
            _confirm = null;
            _keep = null;
            _revert = null;
            Refill("Back");
        }

        private void SelectTab(string tab, bool focusTab)
        {
            if (tab != _tab)
            {
                _tab = tab;
                _statusText = "";
                FillTab(Grid.Count > 0 ? Grid[0] : new List<Control>());
            }
            if (focusTab)
            {
                Focus(_tabButtons[_tab]);
            }
        }

        private void FillTab(List<Control> tabRow)
        {
            _rows.Clear();
            _tabGrid.Clear();
            Grid.Clear();
            Grid.Add(tabRow);
            _status.text = _message != "" ? _message : _tab == "controls" ? _statusText : "";
            foreach (KeyValuePair<string, Control> entry in _tabButtons)
            {
                UiTheme.Border(entry.Value.Element, entry.Key == _tab ? UiTheme.TEXT : UiTheme.BORDER, entry.Key == _tab ? 2 : 1);
            }
            // Apply: on the Display tab only, dimmed and out of the focus grid while nothing waits (#308)
            bool applyOn = _tab == "display" && _staging.HasPending;
            _apply.Element.style.display = _tab == "display" ? DisplayStyle.Flex : DisplayStyle.None;
            _apply.Element.style.opacity = applyOn ? 1f : 0.45f;
            switch (_tab)
            {
                case "display":
                    Note(S.T("settings.display_hint"), "DisplayHint");   // Display waits for Apply, the rest is live
                    foreach (GameSettings.FieldInfo field in GameSettings.Fields(TAB_SECTIONS[_tab]))
                    {
                        AddField(field);
                    }
                    break;
                case "audio":
                case "access":
                    foreach (GameSettings.FieldInfo field in GameSettings.Fields(TAB_SECTIONS[_tab]))
                    {
                        AddField(field);
                    }
                    break;
                case "controls":
                    foreach (GameSettings.FieldInfo field in GameSettings.Fields("input"))
                    {
                        if (Array.IndexOf(CONTROLS_FIELDS, field.Field) >= 0)
                        {
                            AddField(field);
                        }
                    }
                    AddBindings();
                    break;
                case "language":
                    AddLanguage();
                    break;
                case "privacy":
                    foreach (GameSettings.FieldInfo field in GameSettings.Fields("telemetry"))
                    {
                        AddField(field);
                    }
                    Note(S.T("privacy.note"), "PrivacyNote");
                    break;
            }
            foreach (List<Control> row in _tabGrid)
            {
                Grid.Add(row);
            }
            Grid.Add(applyOn ? new List<Control> { _apply, _back } : new List<Control> { _back });
        }

        // ---- rows -----------------------------------------------------------------------

        private VisualElement Row(string fieldId, string title)
        {
            var row = new VisualElement { name = "Row_" + fieldId };
            row.style.flexDirection = FlexDirection.Row;
            row.style.flexWrap = Wrap.Wrap;
            row.style.alignItems = Align.Center;
            row.style.marginBottom = 2f + UiTheme.Gap();
            _rows.Add(row);
            Label name = Text(row, title, "Label");
            name.style.flexGrow = 1;
            name.style.flexBasis = LABEL_MIN_WIDTH;
            name.style.minWidth = LABEL_MIN_WIDTH;
            name.style.marginRight = 12f;
            name.style.marginBottom = 0;
            return row;
        }

        private void Note(string text, string name)
        {
            Label l = Text(_rows, text, name, 1.0f, true);
            l.style.marginTop = 8f;
        }

        private void AddField(GameSettings.FieldInfo field)
        {
            string section = field.Section, name = field.Field;
            bool staged = section == "display";       // Display waits for Apply (#308): show and change the staged value
            object current = staged ? _staging.Value(name) : ((Dictionary<string, object>)S.Settings[section])[name];
            void Set(object v)
            {
                if (staged)
                {
                    StageDisplay(name, v);
                }
                else
                {
                    S.SetValue(section, name, v);
                }
            }
            string title = S.T($"setting.{section}.{name}");
            VisualElement row = Row($"{section}_{name}", title);
            string id = $"Setting_{section}_{name}";
            Control control;
            switch (field.Kind)
            {
                case "bool":
                    control = Toggle(row, title, id, current is bool b && b, on => Set(on));
                    break;
                case "num":
                    double step = STEPS.TryGetValue($"{section}.{name}", out double s) ? s : DEFAULT_STEP;
                    control = Slider(row, title, id, Json.ToNumber(current), field.Lo, field.Hi, step,
                                     v => NumText(section, name, v), v => Set(v));
                    break;
                default:
                    var choices = field.Kind == "res" ? new List<object>(RESOLUTIONS) : new List<object>(field.Choices);
                    if (field.Kind == "res" && current is List<object> res && !HasResolution(choices, res))
                    {
                        choices.Add(res);
                    }
                    var names = new List<string>();
                    foreach (object v in choices)
                    {
                        names.Add(ChoiceText(name, v));
                    }
                    control = Stepper(row, title, id, choices, names, current, v => Set(Json.DeepCopy(v)));
                    break;
            }
            _tabGrid.Add(new List<Control> { control });
        }

        private void AddLanguage()
        {
            VisualElement row = Row("language", S.T("setting.language"));
            List<string> codes = S.Locales();
            var choices = new List<object>();
            var names = new List<string>();
            foreach (string code in codes)
            {
                choices.Add(code);
                names.Add(S.T("lang." + code, null, code));
            }
            Control stepper = Stepper(row, S.T("setting.language"), "Setting_language", choices, names, S.Locale,
                                      code => S.SetLanguage((string)code));
            _tabGrid.Add(new List<Control> { stepper });
            Note(S.T("language.note"), "LanguageNote");
        }

        private void AddBindings()
        {
            string gset = S.GlyphSet();
            string padSet = gset == "keyboard" ? "generic" : gset;
            Dictionary<string, object> bindings = S.BindingsMap();
            HashSet<string> clashes = Duplicates(bindings);
            Note(S.T("controls.bindings"), "BindingsHeading");
            foreach (string action in ACTION_ORDER)
            {
                if (!bindings.ContainsKey(action))
                {
                    continue;
                }
                string title = S.T("action." + action);
                if (clashes.Contains(action))
                {
                    title += " " + S.T("controls.conflict");
                }
                VisualElement row = Row("bind_" + action, title);
                List<string> slots = Bindings.Of(bindings, action);
                var cells = new List<Control>();
                for (int slot = 0; slot < 2; slot++)
                {
                    string binding = slot < slots.Count ? slots[slot] : "";
                    string text = S.BindingText(binding, slot == 0 ? "keyboard" : padSet);
                    string a = action;
                    int sl = slot;
                    Control b = Button(row, text, $"Bind_{action}_{slot}", () => StartCapture(a, sl));
                    b.Kind = "binding";
                    b.Label = title;
                    b.Value = () => ((Label)b.Element.Q<Label>("Text")).text;
                    b.Element.style.minWidth = BIND_MIN_WIDTH;
                    cells.Add(b);
                }
                _tabGrid.Add(cells);
            }
            var resetRow = new VisualElement { name = "ResetRow" };     // wraps at 200 % text
            resetRow.style.flexDirection = FlexDirection.Row;
            resetRow.style.flexWrap = Wrap.Wrap;
            resetRow.style.marginTop = 8f;
            _rows.Add(resetRow);
            var last = new List<Control> { Button(resetRow, S.T("controls.reset"), "ResetBindings", ResetBindings) };
            foreach (string preset in PRESET_NAMES)
            {
                string p = preset;
                last.Add(Button(resetRow, S.T("controls.preset." + preset), "Preset_" + preset, () => ApplyPreset(p)));
            }
            _tabGrid.Add(last);
        }

        // ---- rebinding --------------------------------------------------------------------

        private void StartCapture(string action, int slot)
        {
            _capture = (action, slot);
            _captureLeft = REBIND_TIMEOUT_S;
            Control b = Find($"Bind_{action}_{slot}");
            if (b != null)
            {
                b.Element.Q<Label>("Text").text = S.T(slot == 0 ? "controls.press_key" : "controls.press_button");
            }
            _status.text = S.T("controls.capture_hint");
        }

        private void EndCapture(string binding)
        {
            (string action, int slot) = _capture.Value;
            _capture = null;
            _statusText = "";
            if (binding != "")
            {
                RebindResult result = Bindings.Rebind(S.BindingsMap(), action, slot, binding);
                S.SetBindings(result.Bindings);
                var swapped = new List<string>();
                foreach ((string other, int _) in result.Conflicts)
                {
                    swapped.Add(S.T("action." + other));
                }
                _statusText = swapped.Count > 0
                    ? S.T("controls.swapped", new Dictionary<string, object> { { "actions", string.Join(", ", swapped) } })
                    : S.T("controls.bound", new Dictionary<string, object>
                        { { "action", S.T("action." + action) }, { "binding", S.BindingText(binding) } });
            }
            Refill($"Bind_{action}_{slot}");
        }

        /// <summary>Every action from the preset, the rest from the defaults; the player can rebind anything after.</summary>
        private void ApplyPreset(string preset)
        {
            Dictionary<string, object> chosen = LoadPreset(preset);
            if (chosen == null)
            {
                Debug.LogWarning($"[WARN][settings] {Shell.PRESETS_FILE} has no preset {preset}");
                return;
            }
            Dictionary<string, object> bindings = Bindings.Defaults();
            foreach (KeyValuePair<string, object> entry in chosen)
            {
                bindings[entry.Key] = Json.DeepCopy(entry.Value);
            }
            S.SetBindings(bindings);
            _statusText = S.T("controls.preset_done");
            Refill("Preset_" + preset);
        }

        /// <summary>The bindings of one preset from data/input/presets.json, or null.</summary>
        public static Dictionary<string, object> LoadPreset(string preset)
        {
            string text = ShellFiles.ReadOrNull(Shell.PRESETS_FILE);
            if (text == null || !Json.TryParse(text, out object parsed) || !(parsed is Dictionary<string, object> root)
                || !(root.TryGetValue("presets", out object p) && p is Dictionary<string, object> presets)
                || !(presets.TryGetValue(preset, out object one) && one is Dictionary<string, object> entry)
                || !(entry.TryGetValue("bindings", out object b) && b is Dictionary<string, object> bindings))
            {
                return null;
            }
            return bindings;
        }

        private void ResetBindings()
        {
            S.SetBindings(Bindings.Defaults());
            _statusText = S.T("controls.reset_done");
            Refill("ResetBindings");
        }

        private void Refill(string focusName)
        {
            FillTab(Grid[0]);
            Control c = Find(focusName);
            Focus(c ?? _tabButtons[_tab]);
        }

        // ---- helpers ----------------------------------------------------------------------

        private string NumText(string section, string field, double v)
        {
            if (Array.IndexOf(TIMES_FIELDS, $"{section}.{field}") >= 0)
            {
                return S.T("fmt.times", new Dictionary<string, object> { { "n", Math.Round(v, 2) } });
            }
            return S.T("fmt.percent", new Dictionary<string, object> { { "n", Math.Round(v * 100.0) } });
        }

        private string ChoiceText(string field, object v)
        {
            switch (field)
            {
                case "frame_cap":
                    return Json.ToNumber(v) == 0 ? S.T("value.frame_cap.off")
                                                 : S.T("fmt.fps", new Dictionary<string, object> { { "n", Json.ToNumber(v) } });
                case "resolution":
                    var pair = (List<object>)v;
                    return S.T("fmt.resolution", new Dictionary<string, object>
                        { { "w", Json.ToNumber(pair[0]) }, { "h", Json.ToNumber(pair[1]) } });
            }
            string choice = Json.IsNumber(v) ? Json.FormatNumber(Json.ToNumber(v)) : v as string ?? "";
            return S.T($"value.{field}.{choice}");
        }

        private static bool HasResolution(List<object> choices, List<object> v)
        {
            foreach (object c in choices)
            {
                if (c is List<object> pair && v.Count == 2 && Json.ToNumber(pair[0]) == Json.ToNumber(v[0])
                    && Json.ToNumber(pair[1]) == Json.ToNumber(v[1]))
                {
                    return true;
                }
            }
            return false;
        }

        /// <summary>Actions that share a binding inside their group (ui_* or game): shown as "(conflict)".</summary>
        public static HashSet<string> Duplicates(Dictionary<string, object> bindings)
        {
            var seen = new Dictionary<string, string>();   // group + binding -> first action
            var clashes = new HashSet<string>();
            foreach (string action in bindings.Keys)
            {
                foreach (string b in Bindings.Of(bindings, action))
                {
                    if (b == "")
                    {
                        continue;
                    }
                    string key = Bindings.GroupOf(action) + ":" + b;
                    if (seen.TryGetValue(key, out string first) && first != action)
                    {
                        clashes.Add(first);
                        clashes.Add(action);
                    }
                    else
                    {
                        seen[key] = action;
                    }
                }
            }
            return clashes;
        }
    }
}

// {{FOOTER}}
