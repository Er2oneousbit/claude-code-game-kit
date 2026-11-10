// ---------------------------------------------------------------------------
// ShellInput.cs
// Purpose : The shell's input: the player's bindings (Core/Bindings strings like key:space, pad:south) read from the
//           keyboard, the mouse and a gamepad once a frame, with "just pressed", held and auto-repeat per action,
//           the device last used (for prompt glyphs), and "press a key or button" capture for rebinding. The smoke
//           drive injects presses through the same path, so a drive run exercises the real action logic.
// Usage   : ShellInput.Configure(bindings, autoRepeat);   // after a settings change
//           ShellInput.Begin(Time.unscaledDeltaTime);     // once a frame, first (FrontEnd does it)
//           if (ShellInput.JustPressed("ui_accept")) ...
//           string b = ShellInput.CaptureBinding(slot);   // "key:k", "mouse:left", "pad:south"; null = nothing yet
// Notes   : Polling uses Unity's Input Manager (the default of a project made with -createProject, Active Input
//           Handling "Input Manager (Old)" or "Both"). With only the Input System package active (ENABLE_INPUT_SYSTEM
//           alone) nothing polls: FrontEnd then feeds the keyboard from UI Toolkit's KeyDownEvent and the gamepad from
//           its navigation events (fixed: d-pad or stick moves, south submits, east cancels), so custom pad bindings
//           and pad capture need the Input Manager (verify: only the Input Manager path was run). Gamepad buttons
//           follow the Windows XInput order (PAD_BUTTONS: 0 south ... 9 r3); the d-pad and sticks read the Input
//           Manager's default "Horizontal" and "Vertical" axes, so a stick also moves the menus and pad:dpad_* fires
//           from it; l2 and r2 (triggers) are axes without default entries and never fire (add axes 9 and 10 in
//           Project Settings > Input Manager to use them, verify). The arrow keys share the default axes with the
//           stick, so the device is "keyboard" whenever a key was down this frame.
//
// Pseudocode (Begin):
//   pressed = injected ; for each action: held = any binding held ; new hold -> pressed, else repeat timer
//   (ui_* always repeats while held, game actions only with auto_repeat) ; device = key > mouse > pad of what fired
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class ShellInput
    {
        // ---- Tunables ------------------------------------------------------------
        public const float AXIS_PRESS = 0.5f;        // a stick or d-pad axis past this counts as pressed
        public const float REPEAT_DELAY_S = 0.4f;    // a held action repeats after this
        public const float REPEAT_RATE_S = 0.1f;     // and then this often
        public const int PAD_BUTTON_COUNT = 20;      // KeyCode.JoystickButton0 .. 19
        public static readonly string[] PAD_PLAYSTATION = { "playstation", "dualshock", "dualsense", "sony", "ps3", "ps4", "ps5" };
        public static readonly string[] PAD_XBOX = { "xbox", "xinput" };
        // Windows XInput button order (Unity's Input Manager numbers them this way on Windows; other platforms differ)
        public static readonly string[] PAD_BUTTONS = { "south", "east", "west", "north", "l1", "r1", "select", "start", "l3", "r3" };
        private static readonly Dictionary<string, (string axis, float sign)> PAD_AXES = new Dictionary<string, (string, float)>
        {
            { "dpad_left", ("Horizontal", -1f) }, { "dpad_right", ("Horizontal", 1f) },
            { "dpad_up", ("Vertical", 1f) }, { "dpad_down", ("Vertical", -1f) },
            { "leftx-", ("Horizontal", -1f) }, { "leftx+", ("Horizontal", 1f) },
            { "lefty-", ("Vertical", 1f) }, { "lefty+", ("Vertical", -1f) },
        };
        private static readonly Dictionary<KeyCode, string> KEY_NAMES = new Dictionary<KeyCode, string>
        {
            { KeyCode.Space, "space" }, { KeyCode.Return, "enter" }, { KeyCode.KeypadEnter, "enter" }, { KeyCode.Escape, "escape" },
            { KeyCode.UpArrow, "up" }, { KeyCode.DownArrow, "down" }, { KeyCode.LeftArrow, "left" }, { KeyCode.RightArrow, "right" },
            { KeyCode.Tab, "tab" }, { KeyCode.LeftShift, "shift" }, { KeyCode.RightShift, "shift" },
            { KeyCode.LeftControl, "ctrl" }, { KeyCode.RightControl, "ctrl" }, { KeyCode.LeftAlt, "alt" }, { KeyCode.RightAlt, "alt" },
            { KeyCode.Backspace, "backspace" }, { KeyCode.Delete, "delete" }, { KeyCode.Home, "home" }, { KeyCode.End, "end" },
            { KeyCode.PageUp, "pageup" }, { KeyCode.PageDown, "pagedown" }, { KeyCode.Insert, "insert" },
        };
        private static readonly Dictionary<string, string> KEY_LABELS = new Dictionary<string, string>
        {
            { "escape", "Esc" }, { "enter", "Enter" }, { "space", "Space" }, { "up", "Up" }, { "down", "Down" },
            { "left", "Left" }, { "right", "Right" }, { "ctrl", "Ctrl" }, { "alt", "Alt" }, { "shift", "Shift" },
            { "pageup", "Page Up" }, { "pagedown", "Page Down" },
        };

        public static string LastDevice { get; private set; } = "keyboard";
        public static event Action<string> DeviceChanged;

        private static Dictionary<string, List<string>> _bindings = new Dictionary<string, List<string>>();
        private static bool _autoRepeat;
        private static readonly HashSet<string> _pressed = new HashSet<string>();
        private static readonly HashSet<string> _held = new HashSet<string>();
        private static readonly Dictionary<string, float> _heldFor = new Dictionary<string, float>();
        private static readonly Dictionary<string, float> _nextRepeat = new Dictionary<string, float>();
        private static readonly List<(string action, string device)> _injected = new List<(string, string)>();
        private static readonly Dictionary<string, bool> _axisWas = new Dictionary<string, bool>();
        private static KeyCode[] _keyboardKeys;
        private static Dictionary<string, KeyCode> _keyByName;

        /// <summary>The bindings to read (the settings' "input.bindings" tree) and whether held game actions repeat.</summary>
        public static void Configure(Dictionary<string, object> bindings, bool autoRepeat)
        {
            _bindings = new Dictionary<string, List<string>>();
            if (bindings != null)
            {
                foreach (string action in bindings.Keys)
                {
                    _bindings[action] = Bindings.Of(bindings, action);
                }
            }
            _autoRepeat = autoRepeat;
        }

        /// <summary>Once a frame, before any read: polls the devices and works out presses and repeats.</summary>
        public static void Begin(float dt)
        {
            _pressed.Clear();
            string device = null;
            bool keyDown = false, padDown = false, mouseDown = false;
#if ENABLE_LEGACY_INPUT_MANAGER
            keyDown = AnyKeyboardKeyDown();
#endif
            foreach (KeyValuePair<string, List<string>> entry in _bindings)
            {
                string action = entry.Key;
                bool held = false, down = false;
                foreach (string binding in entry.Value)
                {
                    if (string.IsNullOrEmpty(binding))
                    {
                        continue;
                    }
                    bool h = BindingHeld(binding);
                    held |= h;
                    if (h && BindingDown(binding))
                    {
                        down = true;
                        string kind = KindOf(binding);
                        mouseDown |= kind == "mouse";
                        padDown |= kind == "pad" || kind == "pad_axis";
                    }
                }
                bool wasHeld = _held.Contains(action);
                if (held && (!wasHeld || down))
                {
                    _pressed.Add(action);
                    _heldFor[action] = 0f;
                    _nextRepeat[action] = REPEAT_DELAY_S;
                }
                else if (held)
                {
                    _heldFor[action] = _heldFor.TryGetValue(action, out float t) ? t + dt : dt;
                    bool repeats = action.StartsWith("ui_", StringComparison.Ordinal) || _autoRepeat;
                    if (repeats && _heldFor[action] >= _nextRepeat[action])
                    {
                        _pressed.Add(action);
                        _nextRepeat[action] += REPEAT_RATE_S;
                    }
                }
                if (held)
                {
                    _held.Add(action);
                }
                else
                {
                    _held.Remove(action);
                }
            }
            if (keyDown)
            {
                device = "keyboard";
            }
            else if (mouseDown)
            {
                device = "mouse";
            }
            else if (padDown)
            {
                device = PadDevice();
            }
            foreach ((string action, string dev) in _injected)
            {
                _pressed.Add(action);
                if (dev != null)
                {
                    device = dev;
                }
            }
            _injected.Clear();
            if (device != null && device != LastDevice)
            {
                LastDevice = device;
                DeviceChanged?.Invoke(device);
            }
        }

        public static bool JustPressed(string action)
        {
            return _pressed.Contains(action);
        }

        public static bool IsHeld(string action)
        {
            return _held.Contains(action);
        }

        /// <summary>A press that counts on the next Begin(), as a player's would; device switches the prompts.</summary>
        public static void Inject(string action, string device = null)
        {
            _injected.Add((action, device));
        }

        /// <summary>Which devices the action can be pressed from, from its bindings (the access sweep's ACCESS_INPUT).</summary>
        public static bool HasKeyboard(string action)
        {
            return _bindings.TryGetValue(action, out List<string> b) && b.Exists(s => KindOf(s) == "key" || KindOf(s) == "mouse");
        }

        public static bool HasGamepad(string action)
        {
            return _bindings.TryGetValue(action, out List<string> b) && b.Exists(s => KindOf(s) == "pad" || KindOf(s) == "pad_axis");
        }

        /// <summary>Rebinding: the key or mouse button (slot 0) or pad button (slot 1) pressed this frame, else null.</summary>
        public static string CaptureBinding(int slot)
        {
#if ENABLE_LEGACY_INPUT_MANAGER
            if (slot == Bindings.KEYBOARD_SLOT)
            {
                foreach (KeyCode key in KeyboardKeys())
                {
                    if (Input.GetKeyDown(key))
                    {
                        return "key:" + KeyName(key);
                    }
                }
                if (Input.GetMouseButtonDown(0)) return "mouse:left";
                if (Input.GetMouseButtonDown(1)) return "mouse:right";
                if (Input.GetMouseButtonDown(2)) return "mouse:middle";
                return null;
            }
            for (int i = 0; i < PAD_BUTTON_COUNT; i++)
            {
                if (Input.GetKeyDown(KeyCode.JoystickButton0 + i))
                {
                    return "pad:" + (i < PAD_BUTTONS.Length ? PAD_BUTTONS[i] : "button" + i);
                }
            }
            foreach (string name in new[] { "dpad_left", "dpad_right", "dpad_up", "dpad_down" })
            {
                if (AxisDown(name))
                {
                    return "pad:" + name;
                }
            }
#endif
            return null;
        }

        // ---- names and labels ------------------------------------------------------------

        /// <summary>The binding name of a key: a, 1, space, enter, escape, up, f3 (lower case).</summary>
        public static string KeyName(KeyCode key)
        {
            if (KEY_NAMES.TryGetValue(key, out string name))
            {
                return name;
            }
            if (key >= KeyCode.A && key <= KeyCode.Z)
            {
                return ((char)('a' + (key - KeyCode.A))).ToString();
            }
            if (key >= KeyCode.Alpha0 && key <= KeyCode.Alpha9)
            {
                return ((char)('0' + (key - KeyCode.Alpha0))).ToString();
            }
            return key.ToString().ToLowerInvariant();
        }

        /// <summary>The KeyCode for a binding name, or KeyCode.None.</summary>
        public static KeyCode ParseKey(string name)
        {
            if (_keyByName == null)
            {
                _keyByName = new Dictionary<string, KeyCode>();
                foreach (KeyCode key in KeyboardKeys())
                {
                    string n = KeyName(key);
                    if (!_keyByName.ContainsKey(n))
                    {
                        _keyByName[n] = key;
                    }
                }
            }
            return _keyByName.TryGetValue(name, out KeyCode code) ? code : KeyCode.None;
        }

        /// <summary>English text for a binding, in the glyph set's words: "Space", "Mouse Left", "A", "Cross", "LB",
        /// "Dpad Up", "Left Stick X-" ("" when unbound). Shell.BindingText runs it through the string tables.</summary>
        public static string Label(string glyphSet, string binding)
        {
            if (string.IsNullOrEmpty(binding))
            {
                return "";
            }
            string kind = KindOf(binding);
            string name = NameOf(binding);
            if (kind == "key")
            {
                return KEY_LABELS.TryGetValue(name, out string l) ? l : Capitalize(name);
            }
            if (kind == "mouse")
            {
                return "Mouse " + Capitalize(name);
            }
            if (kind == "pad_axis")
            {
                string stick = name.StartsWith("left", StringComparison.Ordinal) ? "Left Stick " : "Right Stick ";
                return stick + (name.Length >= 2 ? name.Substring(name.Length - 2).ToUpperInvariant() : name);
            }
            string art = Bindings.GlyphName(glyphSet, binding);        // xbox_a, ps_cross, pad_dpad_up
            string shortName = art.Substring(art.IndexOf('_') + 1);
            return shortName.Length <= 2 ? shortName.ToUpperInvariant() : Capitalize(shortName.Replace('_', ' '));
        }

        public static string KindOf(string binding)
        {
            int colon = binding.IndexOf(':');
            return colon < 0 ? binding : binding.Substring(0, colon);
        }

        public static string NameOf(string binding)
        {
            int colon = binding.IndexOf(':');
            return colon < 0 ? "" : binding.Substring(colon + 1);
        }

        // ---- internals -------------------------------------------------------------------

        private static string Capitalize(string s)
        {
            if (s.Length == 0)
            {
                return s;
            }
            var words = s.Split(' ');
            for (int i = 0; i < words.Length; i++)
            {
                if (words[i].Length > 0)
                {
                    words[i] = char.ToUpperInvariant(words[i][0]) + words[i].Substring(1);
                }
            }
            return string.Join(" ", words);
        }

        private static bool BindingHeld(string binding)
        {
#if ENABLE_LEGACY_INPUT_MANAGER
            string kind = KindOf(binding), name = NameOf(binding);
            switch (kind)
            {
                case "key":
                    KeyCode key = ParseKey(name);
                    return key != KeyCode.None && Input.GetKey(key);
                case "mouse":
                    int button = name == "left" ? 0 : name == "right" ? 1 : name == "middle" ? 2 : -1;
                    return button >= 0 && Input.GetMouseButton(button);
                case "pad":
                    int idx = Array.IndexOf(PAD_BUTTONS, name);
                    if (idx >= 0)
                    {
                        return Input.GetKey(KeyCode.JoystickButton0 + idx);
                    }
                    return PAD_AXES.ContainsKey(name) && AxisHeld(name);
                case "pad_axis":
                    return PAD_AXES.ContainsKey(name) && AxisHeld(name);
            }
#endif
            return false;
        }

        private static bool BindingDown(string binding)
        {
#if ENABLE_LEGACY_INPUT_MANAGER
            string kind = KindOf(binding), name = NameOf(binding);
            switch (kind)
            {
                case "key":
                    KeyCode key = ParseKey(name);
                    return key != KeyCode.None && Input.GetKeyDown(key);
                case "mouse":
                    int button = name == "left" ? 0 : name == "right" ? 1 : name == "middle" ? 2 : -1;
                    return button >= 0 && Input.GetMouseButtonDown(button);
                case "pad":
                    int idx = Array.IndexOf(PAD_BUTTONS, name);
                    if (idx >= 0)
                    {
                        return Input.GetKeyDown(KeyCode.JoystickButton0 + idx);
                    }
                    return PAD_AXES.ContainsKey(name) && AxisDown(name);
                case "pad_axis":
                    return PAD_AXES.ContainsKey(name) && AxisDown(name);
            }
#endif
            return false;
        }

#if ENABLE_LEGACY_INPUT_MANAGER
        private static bool AxisHeld(string name)
        {
            (string axis, float sign) = PAD_AXES[name];
            try
            {
                return Input.GetAxisRaw(axis) * sign >= AXIS_PRESS;
            }
            catch (ArgumentException)
            {
                return false;                  // the project removed the default axis
            }
        }

        // An axis edge: held now and not at the last Begin (per direction name)
        private static bool AxisDown(string name)
        {
            bool now = AxisHeld(name);
            bool was = _axisWas.TryGetValue(name, out bool w) && w;
            _axisWas[name] = now;
            return now && !was;
        }

        private static bool AnyKeyboardKeyDown()
        {
            if (!Input.anyKeyDown)
            {
                return false;
            }
            foreach (KeyCode key in KeyboardKeys())
            {
                if (Input.GetKeyDown(key))
                {
                    return true;
                }
            }
            return false;
        }
#endif

        private static KeyCode[] KeyboardKeys()
        {
            if (_keyboardKeys == null)
            {
                var keys = new List<KeyCode>();
                foreach (KeyCode key in Enum.GetValues(typeof(KeyCode)))
                {
                    if (key != KeyCode.None && key < KeyCode.Mouse0)
                    {
                        keys.Add(key);        // keyboard keys only: mouse and joystick codes come after Mouse0
                    }
                }
                _keyboardKeys = keys.ToArray();
            }
            return _keyboardKeys;
        }

        private static string PadDevice()
        {
#if ENABLE_LEGACY_INPUT_MANAGER
            string[] names = Input.GetJoystickNames();
            string pad = names.Length > 0 ? (names[0] ?? "").ToLowerInvariant() : "";
            foreach (string word in PAD_PLAYSTATION)
            {
                if (pad.Contains(word)) return "pad_playstation";
            }
            foreach (string word in PAD_XBOX)
            {
                if (pad.Contains(word)) return "pad_xbox";
            }
#endif
            return "pad_other";
        }
    }
}

// {{FOOTER}}
