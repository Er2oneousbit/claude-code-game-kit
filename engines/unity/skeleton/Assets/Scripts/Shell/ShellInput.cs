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
//           ShellInput.Backend                            // "input_system", "input_manager" or "ui_events"
// Notes   : Three backends, picked at compile time (#266):
//           - "input_system": the Input System package is installed (Game.Shell.asmdef's versionDefines set
//             GAMEKIT_INPUT_SYSTEM) and active (Player Settings > Active Input Handling "Input System Package (New)"
//             or "Both": ENABLE_INPUT_SYSTEM). Reads Keyboard.current, Mouse.current and Gamepad.current by control
//             (buttonSouth, leftTrigger, dpad...), so every binding name and pad capture work on any pad the Input
//             System knows. Preferred when both handlers are on.
//           - "input_manager": the old Input Manager (a -createProject default). Gamepad buttons follow the Windows
//             XInput order (PAD_BUTTONS: 0 south ... 9 r3); the left stick and the keyboard arrows read the default
//             "Horizontal"/"Vertical" axes; the d-pad and the triggers read the axes GameKitScenes.AddInputAxes adds
//             (GameKit DPad X/Y = joystick axes 6 and 7, GameKit L2/R2 = axes 9 and 10, the Windows XInput layout,
//             verify on other platforms). A missing axis reads as released.
//           - "ui_events": the Input System is active but its package is missing (nothing to poll): FrontEnd feeds
//             the keyboard from UI Toolkit's KeyDownEvent and the pad from its navigation events (fixed: d-pad or
//             stick moves, south submits, east cancels); custom pad bindings are not read. Install the package.
//           The package is never a hard dependency: the asmdef references Unity.InputSystem by name (ignored when the
//           package is absent) and the code that names its types compiles only under GAMEKIT_INPUT_SYSTEM.
//           Triggers (pad:l2, pad:r2) are axes on both polling backends: pressed past AXIS_PRESS.
//
// Pseudocode (Begin):
//   held = the backend's snapshot of every binding held now (key:*, mouse:*, pad:*, pad_axis:*) ; down = held - last
//   pressed = injected ; for each action: held = any binding held ; new hold or a binding down -> pressed, else
//   repeat timer (ui_* always repeats while held, game actions only with auto_repeat) ; device = key > mouse > pad
//   of what went down
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the Input System backend, triggers and the d-pad as
//           axes, held-set snapshots with edges, capture skips the press that started it (#266)
// ---------------------------------------------------------------------------
#if GAMEKIT_INPUT_SYSTEM && ENABLE_INPUT_SYSTEM
#define SHELL_INPUT_SYSTEM
#elif ENABLE_LEGACY_INPUT_MANAGER
#define SHELL_INPUT_MANAGER
#endif
using System;
using System.Collections.Generic;
using UnityEngine;
#if SHELL_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;
#endif
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class ShellInput
    {
        // ---- Tunables ------------------------------------------------------------
        public const float AXIS_PRESS = 0.5f;        // a stick, d-pad or trigger axis past this counts as pressed
        public const float REPEAT_DELAY_S = 0.4f;    // a held action repeats after this
        public const float REPEAT_RATE_S = 0.1f;     // and then this often
        public const int PAD_BUTTON_COUNT = 20;      // KeyCode.JoystickButton0 .. 19 (Input Manager)
        // Input Manager axes GameKitScenes.AddInputAxes adds (joystick axis numbers of the Windows XInput layout)
        public const string AXIS_DPAD_X = "GameKit DPad X";
        public const string AXIS_DPAD_Y = "GameKit DPad Y";
        public const string AXIS_L2 = "GameKit L2";
        public const string AXIS_R2 = "GameKit R2";
        public static readonly string[] PAD_PLAYSTATION = { "playstation", "dualshock", "dualsense", "sony", "ps3", "ps4", "ps5" };
        public static readonly string[] PAD_XBOX = { "xbox", "xinput" };
        // Windows XInput button order (Unity's Input Manager numbers them this way on Windows; other platforms differ)
        public static readonly string[] PAD_BUTTONS = { "south", "east", "west", "north", "l1", "r1", "select", "start", "l3", "r3" };
        // What a pad capture can return, in the order it looks (buttons first, then triggers, then the d-pad)
        private static readonly string[] PAD_CAPTURE = {
            "south", "east", "west", "north", "l1", "r1", "select", "start", "l3", "r3", "l2", "r2",
            "dpad_left", "dpad_right", "dpad_up", "dpad_down",
        };
        private static readonly string[] STICK_NAMES = { "leftx-", "leftx+", "lefty-", "lefty+", "rightx-", "rightx+", "righty-", "righty+" };
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

#if SHELL_INPUT_SYSTEM
        public const string Backend = "input_system";
#elif SHELL_INPUT_MANAGER
        public const string Backend = "input_manager";
#else
        public const string Backend = "ui_events";
#endif
        /// <summary>True when ShellInput reads the devices itself; false when FrontEnd feeds it UI Toolkit events.</summary>
        public static bool Polls => Backend != "ui_events";

        public static string LastDevice { get; private set; } = "keyboard";
        public static event Action<string> DeviceChanged;

        private static Dictionary<string, List<string>> _bindings = new Dictionary<string, List<string>>();
        private static bool _autoRepeat;
        private static readonly HashSet<string> _pressed = new HashSet<string>();
        private static readonly HashSet<string> _held = new HashSet<string>();
        private static readonly Dictionary<string, float> _heldFor = new Dictionary<string, float>();
        private static readonly Dictionary<string, float> _nextRepeat = new Dictionary<string, float>();
        private static readonly List<(string action, string device)> _injected = new List<(string, string)>();
        private static HashSet<string> _heldNow = new HashSet<string>();       // bindings held at this Begin
        private static HashSet<string> _heldLast = new HashSet<string>();      // and at the one before
        private static readonly HashSet<string> _downNow = new HashSet<string>();   // held now, not last time
        private static int _begins;                  // Begin() calls so far
        private static int _captureSeen = -2;        // the Begin count of the last CaptureBinding call
        private static KeyCode[] _keyboardKeys;
        private static Dictionary<string, KeyCode> _keyByName;
#if SHELL_INPUT_MANAGER
        private static readonly HashSet<string> _missingAxes = new HashSet<string>();
#endif

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
            _begins++;
            _pressed.Clear();
            (_heldLast, _heldNow) = (_heldNow, _heldLast);
            _heldNow.Clear();
            Snapshot(_heldNow);
            _downNow.Clear();
            bool keyDown = false, padDown = false, mouseDown = false;
            foreach (string b in _heldNow)
            {
                if (!_heldLast.Contains(b))
                {
                    _downNow.Add(b);
                    string kind = KindOf(b);
                    keyDown |= kind == "key";
                    mouseDown |= kind == "mouse";
                    padDown |= kind == "pad" || kind == "pad_axis";
                }
            }
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
                    string b = Canonical(binding);
                    held |= _heldNow.Contains(b);
                    down |= _downNow.Contains(b);
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
            string device = keyDown ? "keyboard" : mouseDown ? "mouse" : padDown ? PadDevice() : null;
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

        /// <summary>Whether this backend can read a binding at all (a name it knows; on the Input Manager, its axis
        /// exists). The same binding can still be unpressable when no such device is connected.</summary>
        public static bool CanRead(string binding)
        {
            if (string.IsNullOrEmpty(binding))
            {
                return false;
            }
            string kind = KindOf(binding), name = NameOf(binding);
            switch (Canonical(binding) == binding ? kind : "pad_axis")
            {
                case "key":
                    return ParseKey(name) != KeyCode.None;
                case "mouse":
                    return name == "left" || name == "right" || name == "middle";
                case "pad_axis":
#if SHELL_INPUT_MANAGER
                    return name.StartsWith("left", StringComparison.Ordinal) && Array.IndexOf(STICK_NAMES, name) >= 0;
#else
                    return Polls && Array.IndexOf(STICK_NAMES, name) >= 0;
#endif
                case "pad":
#if SHELL_INPUT_MANAGER
                    if (name == "l2") return AxisExists(AXIS_L2);
                    if (name == "r2") return AxisExists(AXIS_R2);
                    return Array.IndexOf(PAD_CAPTURE, name) >= 0
                           || (name.StartsWith("button", StringComparison.Ordinal) && int.TryParse(name.Substring(6), out int n) && n < PAD_BUTTON_COUNT);
#else
                    return Polls && Array.IndexOf(PAD_CAPTURE, name) >= 0;
#endif
            }
            return false;
        }

        /// <summary>Rebinding: the key or mouse button (slot 0) or pad button, trigger or d-pad direction (slot 1)
        /// that went down at this frame's Begin, else null. The first call of a capture returns null, so the press
        /// that opened the capture (ui_accept on the binding row) is never taken as the new binding.</summary>
        public static string CaptureBinding(int slot)
        {
            bool continuing = _captureSeen == _begins || _captureSeen == _begins - 1;
            _captureSeen = _begins;
            if (!continuing)
            {
                return null;
            }
            if (slot == Bindings.KEYBOARD_SLOT)
            {
                string mouse = null;
                foreach (string b in _downNow)
                {
                    string kind = KindOf(b);
                    if (kind == "key")
                    {
                        return b;
                    }
                    if (kind == "mouse" && mouse == null)
                    {
                        mouse = b;
                    }
                }
                return mouse;
            }
            foreach (string name in PAD_CAPTURE)
            {
                if (_downNow.Contains("pad:" + name))
                {
                    return "pad:" + name;
                }
            }
            foreach (string b in _downNow)
            {
                if (b.StartsWith("pad:button", StringComparison.Ordinal))
                {
                    return b;
                }
            }
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

        // The form a snapshot holds a binding in: pad:leftx- (a stick named as a pad binding) is pad_axis:leftx-
        private static string Canonical(string binding)
        {
            if (binding.StartsWith("pad:", StringComparison.Ordinal) && Array.IndexOf(STICK_NAMES, NameOf(binding)) >= 0)
            {
                return "pad_axis:" + NameOf(binding);
            }
            return binding;
        }

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

        // Adds the directions an x/y pair (stick or d-pad) points past AXIS_PRESS; y is up-positive
        private static void AddDirections(HashSet<string> held, string prefix, string stick, float x, float y)
        {
            if (x <= -AXIS_PRESS) held.Add(prefix + (stick != null ? stick + "x-" : "dpad_left"));
            if (x >= AXIS_PRESS) held.Add(prefix + (stick != null ? stick + "x+" : "dpad_right"));
            if (y >= AXIS_PRESS) held.Add(prefix + (stick != null ? stick + "y-" : "dpad_up"));
            if (y <= -AXIS_PRESS) held.Add(prefix + (stick != null ? stick + "y+" : "dpad_down"));
        }

#if SHELL_INPUT_SYSTEM
        // ---- backend: the Input System package ----------------------------------------------

        private static void Snapshot(HashSet<string> held)
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard != null && keyboard.anyKey.isPressed)
            {
                foreach (KeyControl k in keyboard.allKeys)
                {
                    if (k != null && k.isPressed)
                    {
                        string name = InputSystemKeyName(k.keyCode);
                        if (name != null)
                        {
                            held.Add("key:" + name);
                        }
                    }
                }
            }
            Mouse mouse = Mouse.current;
            if (mouse != null)
            {
                if (mouse.leftButton.isPressed) held.Add("mouse:left");
                if (mouse.rightButton.isPressed) held.Add("mouse:right");
                if (mouse.middleButton.isPressed) held.Add("mouse:middle");
            }
            Gamepad pad = Gamepad.current;
            if (pad == null)
            {
                return;
            }
            if (pad.buttonSouth.isPressed) held.Add("pad:south");
            if (pad.buttonEast.isPressed) held.Add("pad:east");
            if (pad.buttonWest.isPressed) held.Add("pad:west");
            if (pad.buttonNorth.isPressed) held.Add("pad:north");
            if (pad.leftShoulder.isPressed) held.Add("pad:l1");
            if (pad.rightShoulder.isPressed) held.Add("pad:r1");
            if (pad.selectButton.isPressed) held.Add("pad:select");
            if (pad.startButton.isPressed) held.Add("pad:start");
            if (pad.leftStickButton.isPressed) held.Add("pad:l3");
            if (pad.rightStickButton.isPressed) held.Add("pad:r3");
            if (pad.leftTrigger.ReadValue() >= AXIS_PRESS) held.Add("pad:l2");      // triggers are axes
            if (pad.rightTrigger.ReadValue() >= AXIS_PRESS) held.Add("pad:r2");
            Vector2 dpad = pad.dpad.ReadValue();
            Vector2 left = pad.leftStick.ReadValue();
            Vector2 right = pad.rightStick.ReadValue();
            AddDirections(held, "pad:", null, dpad.x, dpad.y);
            AddDirections(held, "pad:", null, left.x, left.y);       // the left stick moves the menus too
            AddDirections(held, "pad_axis:", "left", left.x, left.y);
            AddDirections(held, "pad_axis:", "right", right.x, right.y);
        }

        // The binding name of an Input System key, the same name KeyName gives the Input Manager's KeyCode
        private static string InputSystemKeyName(Key key)
        {
            switch (key)
            {
                case Key.None: return null;
                case Key.Enter: case Key.NumpadEnter: return "enter";
                case Key.Escape: return "escape";
                case Key.Space: return "space";
                case Key.UpArrow: return "up";
                case Key.DownArrow: return "down";
                case Key.LeftArrow: return "left";
                case Key.RightArrow: return "right";
                case Key.LeftShift: case Key.RightShift: return "shift";
                case Key.LeftCtrl: case Key.RightCtrl: return "ctrl";
                case Key.LeftAlt: case Key.RightAlt: return "alt";
            }
            if (key >= Key.Digit1 && key <= Key.Digit9)
            {
                return ((char)('1' + (key - Key.Digit1))).ToString();
            }
            if (key == Key.Digit0)
            {
                return "0";
            }
            string name = key.ToString().ToLowerInvariant();
            return name.StartsWith("numpad", StringComparison.Ordinal) ? "keypad" + name.Substring(6) : name;
        }

        private static string PadDevice()
        {
            Gamepad pad = Gamepad.current;
            string words = pad == null ? "" : $"{pad.layout} {pad.description.manufacturer} {pad.description.product} {pad.displayName}".ToLowerInvariant();
            return PadBrand(words);
        }
#elif SHELL_INPUT_MANAGER
        // ---- backend: the Input Manager --------------------------------------------------------

        private static void Snapshot(HashSet<string> held)
        {
            if (Input.anyKey)          // the keyboard scan (about 150 keys) only when something is down
            {
                foreach (KeyCode key in KeyboardKeys())
                {
                    if (Input.GetKey(key))
                    {
                        held.Add("key:" + KeyName(key));
                    }
                }
            }
            if (Input.GetMouseButton(0)) held.Add("mouse:left");
            if (Input.GetMouseButton(1)) held.Add("mouse:right");
            if (Input.GetMouseButton(2)) held.Add("mouse:middle");
            for (int i = 0; i < PAD_BUTTON_COUNT; i++)
            {
                if (Input.GetKey(KeyCode.JoystickButton0 + i))
                {
                    held.Add("pad:" + (i < PAD_BUTTONS.Length ? PAD_BUTTONS[i] : "button" + i));
                }
            }
            if (Axis(AXIS_L2) >= AXIS_PRESS) held.Add("pad:l2");                    // triggers are axes
            if (Axis(AXIS_R2) >= AXIS_PRESS) held.Add("pad:r2");
            float h = Axis("Horizontal"), v = Axis("Vertical");
            AddDirections(held, "pad:", null, Axis(AXIS_DPAD_X), Axis(AXIS_DPAD_Y));
            AddDirections(held, "pad:", null, h, v);           // the stick (and the arrow keys) move the menus too
            AddDirections(held, "pad_axis:", "left", h, v);
        }

        // An Input Manager axis, 0 when the project does not have it (looked up once, then remembered as missing)
        private static float Axis(string name)
        {
            if (_missingAxes.Contains(name))
            {
                return 0f;
            }
            try
            {
                return Input.GetAxisRaw(name);
            }
            catch (ArgumentException)
            {
                _missingAxes.Add(name);
                return 0f;
            }
        }

        private static bool AxisExists(string name)
        {
            Axis(name);
            return !_missingAxes.Contains(name);
        }

        private static string PadDevice()
        {
            string[] names = Input.GetJoystickNames();
            return PadBrand(names.Length > 0 ? (names[0] ?? "").ToLowerInvariant() : "");
        }
#else
        // ---- backend: none (FrontEnd injects UI Toolkit events) -----------------------------------

        private static void Snapshot(HashSet<string> held)
        {
        }

        private static string PadDevice()
        {
            return "pad_other";
        }
#endif

        private static string PadBrand(string words)
        {
            foreach (string word in PAD_PLAYSTATION)
            {
                if (words.Contains(word)) return "pad_playstation";
            }
            foreach (string word in PAD_XBOX)
            {
                if (words.Contains(word)) return "pad_xbox";
            }
            return "pad_other";
        }
    }
}

// {{FOOTER}}
