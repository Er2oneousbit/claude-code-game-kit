// ---------------------------------------------------------------------------
// Shell.cs
// Purpose : The game's runtime services, shared by every screen: the data folder, settings (load, apply, save),
//           strings in the player's language, input bindings and prompt text, the goal and dialogue history for
//           "What now?", and the marker lines dev.py reads. One per scene (FrontEnd adds it when missing).
// Usage   : Shell.I.T("menu.play")                        // a UI string in the current language
//           Shell.I.Tn("demo.hits", 3)                    // with plural forms
//           GameSettings.Bool(Shell.I.Settings, "access", "reduce_motion")
//           Shell.I.SetValue("audio", "master", 0.5);     // applied at once; SaveSettings() writes the file
//           Shell.I.SetObjective(Shell.I.T("demo.objective"));  Shell.I.RecordLine("Guide", "Hello")
// Notes   : FrontEnd boots it through Shell.Ensure (Awake order between sibling components is not fixed; a kit
//           drive once talked to one Shell while the screens listened to another). Run options come from environment variables (dev.py smoke sets them for the PlayMode run) or the
//           player's command line: GAMEKIT_DATA_DIR / --data-dir <dir> (default Application.persistentDataPath),
//           GAMEKIT_LOCALE / --locale <code> (this run only; "pseudo" is the test locale), GAMEKIT_DRIVE / --drive
//           <scenario> (SmokeDrive), GAMEKIT_SMOKE=1 / --smoke. Files in the data folder: settings.json (+ .bak).
//           Audio: the master slider sets AudioListener.volume; the other sliders are for your AudioMixer (the Core
//           AudioAccess.UserBusGains gives the gain per bus). Display settings apply only in a player (not in the
//           editor or batchmode). Crash files (crashes/crash_<time>.txt) and the F8 bug report (bug_<time>/) are
//           ShellReports' (#275); no telemetry file yet on this engine (Godot, LÖVE and web have one).
//
// Pseudocode:
//   boot: options -> data folder -> settings.json (GameSettings fixes it, .bak recovers it) -> string tables
//         (data/i18n/*.json) -> colours -> apply look, input, audio, display, language
//   SetValue: change the tree -> apply that section -> SettingsChanged (FrontEnd rebuilds what the look touches)
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): crash files and the bug report (ShellReports, #275),
//           the stick's deadzone and invert_y for ShellInput's analog values (#274)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using graveyard_shift.Core;

namespace graveyard_shift.Shell
{
    public sealed class Shell : MonoBehaviour
    {
        // ---- Tunables ------------------------------------------------------------
        public const string GAME_NAME = "Graveyard Shift";   // the game's name (the scaffolder fills it); game.title shows it
        public const string SETTINGS_FILE = "settings.json";
        public const string I18N_DIR = "data/i18n";
        public const string DIALOGUE_FILE = "data/dialogue/sample.built.json";
        public const string PRESETS_FILE = "data/input/presets.json";
        public const string CREDITS_FILE = "CREDITS.md";
        public const string PSEUDO_LOCALE = "pseudo";
        public const int MAX_HISTORY = 50;      // dialogue lines kept for "Dialogue history" (#167)

        public static Shell I { get; private set; }

        public string DataDir = "";
        public Dictionary<string, object> Settings = GameSettings.Defaults();
        public List<string> SettingsProblems = new List<string>();
        public Dictionary<string, Dictionary<string, string>> Tables = new Dictionary<string, Dictionary<string, string>>();
        public string Locale = "en";
        public string LocaleOverride = "";
        public bool Smoke;
        public string Drive = "";
        public string Version = "";
        public string Objective = "";                  // the goal "What now?" shows (#167)
        public string LastNarration = "";              // the line the narrator last worked out (#165), spoken or not
        public readonly List<(string Name, string Text)> History = new List<(string, string)>();
        public Dictionary<string, object> Colours;      // data/access/colours.json (AccessColours)

        public event Action<string, string> SettingsChanged;   // (section, key)
        public event Action LocaleChanged;

        private readonly HashSet<string> _missingKeys = new HashSet<string>();
        private bool _booted;

        private void Awake()
        {
            Boot();
        }

        /// <summary>The scene's Shell, booted: the one on this GameObject, else the first in the scene, else a new
        /// one. Awake order between components is not fixed, so FrontEnd calls this instead of trusting Shell.I.</summary>
        public static Shell Ensure(GameObject host)
        {
            Shell shell = host.GetComponent<Shell>();
            if (shell == null)
            {
                shell = I != null ? I : FindFirstObjectByType<Shell>();
            }
            if (shell == null)
            {
                shell = host.AddComponent<Shell>();      // Awake boots it
            }
            shell.Boot();
            return shell;
        }

        /// <summary>Loads everything once (a second call does nothing); a second Shell in the scene stays passive.</summary>
        public void Boot()
        {
            if (_booted)
            {
                return;
            }
            _booted = true;
            if (I != null && I != this)
            {
                Debug.LogWarning("[WARN][shell] a second Shell component is in the scene: it is ignored");
                enabled = false;
                return;
            }
            I = this;
            Version = Application.version;
            ParseOptions();
            ShellReports.Install(DataDir);       // crash files from here on (an error while loading settings included)
            try
            {
                Directory.CreateDirectory(DataDir);
            }
            catch (IOException e)
            {
                Debug.LogWarning($"[WARN][shell] cannot create the data folder {DataDir}: {e.Message}");
            }
            LoadSettings();
            Tables = LoadTables();
            Colours = AccessColours.LoadData();
            ApplyAll();
            Debug.Log($"[INFO][shell] data folder: {DataDir}");
        }

        private void Update()
        {
            ShellReports.Tick();
        }

        private void OnDestroy()
        {
            if (I == this)
            {
                I = null;
            }
        }

        // ---- files -----------------------------------------------------------------

        public string PathOf(string relative)
        {
            return Path.Combine(DataDir, relative);
        }

        public void LoadSettings()
        {
            SettingsLoadResult loaded = GameSettings.LoadFile(PathOf(SETTINGS_FILE));
            Settings = loaded.Settings;
            SettingsProblems = loaded.Problems;
            if (SettingsProblems.Count > 0)
            {
                Debug.LogWarning($"[WARN][settings] fixed {SettingsProblems.Count} value(s) in {SETTINGS_FILE}: "
                                 + string.Join(", ", SettingsProblems));
            }
        }

        /// <summary>Writes settings.json (atomic, keeps .bak). Returns the path, or "" when it could not be written.</summary>
        public string SaveSettings()
        {
            string file = PathOf(SETTINGS_FILE);
            try
            {
                GameSettings.SaveFile(file, Settings);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                Debug.LogError($"[ERROR][settings] could not save {file}: {e.Message}");
                return "";
            }
            Debug.Log($"[INFO][settings] saved {file}");
            return file;
        }

        /// <summary>{locale: table} from every data/i18n/<locale>.json (each file is one flat table).</summary>
        public static Dictionary<string, Dictionary<string, string>> LoadTables()
        {
            var root = new Dictionary<string, object>();
            foreach (string path in ShellFiles.List(I18N_DIR, "*.json"))
            {
                string text;
                try
                {
                    text = File.ReadAllText(path, System.Text.Encoding.UTF8);
                }
                catch (IOException e)
                {
                    Debug.LogWarning($"[WARN][i18n] cannot read {path}: {e.Message}");
                    continue;
                }
                if (Json.TryParse(text, out object parsed) && parsed is Dictionary<string, object> table)
                {
                    root[Path.GetFileNameWithoutExtension(path)] = table;
                }
                else
                {
                    Debug.LogWarning($"[WARN][i18n] {path} is not a JSON object of strings");
                }
            }
            if (root.Count == 0)
            {
                Debug.LogWarning($"[WARN][i18n] no string tables under {I18N_DIR}: keys show instead of text");
            }
            return I18n.TablesFromJson(root);
        }

        // ---- settings --------------------------------------------------------------

        public void SetValue(string section, string key, object value)
        {
            ((Dictionary<string, object>)Settings[section])[key] = value;
            switch (section)
            {
                case "display": ApplyDisplay(); break;
                case "audio": ApplyAudio(); break;
                case "input": ApplyInput(); break;
                case "access": ApplyAccess(); break;
            }
            SettingsChanged?.Invoke(section, key);
        }

        public void SetLanguage(string code)
        {
            Settings["language"] = code;
            LocaleOverride = "";
            UpdateLocale();
            SettingsChanged?.Invoke("language", "language");
        }

        /// <summary>This run's language without touching the saved setting (--locale; the pseudo drive switches to pseudo).</summary>
        public void OverrideLocale(string code)
        {
            LocaleOverride = code ?? "";
            UpdateLocale();
        }

        public void SetBindings(Dictionary<string, object> bindings)
        {
            ((Dictionary<string, object>)Settings["input"])["bindings"] = bindings;
            ApplyInput();
            SettingsChanged?.Invoke("input", "bindings");
        }

        public void ApplyAll()
        {
            ApplyAccess();
            ApplyInput();
            ApplyAudio();
            ApplyDisplay();
            UpdateLocale();
        }

        public object Access(string key)
        {
            return Settings.TryGetValue("access", out object a) && a is Dictionary<string, object> acc
                   && acc.TryGetValue(key, out object v) ? v : null;
        }

        public bool AccessOn(string key)
        {
            return GameSettings.Bool(Settings, "access", key);
        }

        /// <summary>The goal "What now?" shows on the pause menu (#167); "" clears it. Pass translated text.</summary>
        public void SetObjective(string text)
        {
            Objective = text ?? "";
        }

        /// <summary>Records a line the player saw, for "Dialogue history" and "What now?" (the subtitle bar calls it).</summary>
        public void RecordLine(string speaker, string text)
        {
            History.Add((speaker ?? "", text ?? ""));
            if (History.Count > MAX_HISTORY)
            {
                History.RemoveAt(0);
            }
        }

        /// <summary>The game's important colours for the current colour-blind setting (data/access/colours.json).</summary>
        public Dictionary<string, Color> Palette()
        {
            return AccessColours.Palette(Colours, GameSettings.Text(Settings, "access", "colorblind"));
        }

        public double EffectiveShake()
        {
            return GameSettings.EffectiveShake(Settings);
        }

        public float GameSpeed()
        {
            return (float)GameSettings.Number(Settings, "access", "game_speed");
        }

        // ---- strings -----------------------------------------------------------------

        /// <summary>A UI string in the current language; fallback (untranslated) when no table has the key.</summary>
        public string T(string key, IDictionary<string, object> args = null, string fallback = null)
        {
            if (Locale == PSEUDO_LOCALE)
            {
                string raw = Lookup(I18n.FALLBACK_LOCALE, key);
                if (raw == null)
                {
                    if (fallback == null)
                    {
                        Missing(key);
                        return key;       // left without brackets on purpose: a pseudo check flags it
                    }
                    raw = fallback;
                }
                return I18n.Fill(I18n.Pseudo(raw), args);
            }
            string found = Lookup(Locale, key);
            if (found == null)
            {
                if (fallback != null)
                {
                    return I18n.Fill(fallback, args);
                }
                Missing(key);
                return key;
            }
            return I18n.Fill(found, args);
        }

        /// <summary>The game's name on the title and the main menu: game.title is "{name}" in every table, so a
        /// translation can frame it but the name is never a string to translate (check_i18n.py).</summary>
        public string GameTitle()
        {
            return T("game.title", new Dictionary<string, object> { { "name", GAME_NAME } });
        }

        public string Tn(string key, double n, IDictionary<string, object> args = null)
        {
            var all = args != null ? new Dictionary<string, object>(args) : new Dictionary<string, object>();
            all["n"] = n;
            string rules = Locale == PSEUDO_LOCALE ? I18n.FALLBACK_LOCALE : Locale;
            return T(key + "." + I18n.Plural(rules, n), all);
        }

        /// <summary>Text from data files (dialogue, credits): as written, pseudo-localized in the "pseudo" locale.</summary>
        public string Content(string text)
        {
            return Locale == PSEUDO_LOCALE ? I18n.Pseudo(text ?? "") : text ?? "";
        }

        /// <summary>The languages on offer: English first, the rest sorted, plus pseudo in the editor and debug builds.</summary>
        public List<string> Locales()
        {
            var output = new List<string>();
            var names = new List<string>(Tables.Keys);
            names.Sort(StringComparer.Ordinal);
            if (names.Contains(I18n.FALLBACK_LOCALE))
            {
                output.Add(I18n.FALLBACK_LOCALE);
            }
            foreach (string name in names)
            {
                if (!output.Contains(name))
                {
                    output.Add(name);
                }
            }
            if (Debug.isDebugBuild || Application.isEditor)
            {
                output.Add(PSEUDO_LOCALE);
            }
            return output;
        }

        // ---- bindings and prompts -------------------------------------------------

        public string GlyphSet()
        {
            return Bindings.GlyphSet(GameSettings.Text(Settings, "input", "glyphs"), ShellInput.LastDevice);
        }

        public Dictionary<string, object> BindingsMap()
        {
            return ((Dictionary<string, object>)Settings["input"])["bindings"] as Dictionary<string, object>
                   ?? Bindings.Defaults();
        }

        /// <summary>The binding to show for an action on the device in use ("" when it has none).</summary>
        public string PromptFor(string action)
        {
            return Bindings.PromptBinding(BindingsMap(), action, GlyphSet());
        }

        /// <summary>The text for a binding ("Space", "A", "(none)"), through the string tables (binding.key.space).</summary>
        public string BindingText(string binding, string glyphSet = null)
        {
            if (string.IsNullOrEmpty(binding))
            {
                return T("controls.unbound");
            }
            string set = glyphSet ?? GlyphSet();
            return T("binding." + binding.Replace(':', '.'), null, ShellInput.Label(set, binding));
        }

        /// <summary>A marker line for dev.py and the tests (DRIVE_DONE, ACCESS_SCREEN ...), on its own log line.</summary>
        public static void Raw(string line)
        {
            Debug.Log(line);
        }

        // ---- internals -------------------------------------------------------------

        private string Lookup(string locale, string key)
        {
            foreach (string loc in I18n.LocaleChain(locale))
            {
                if (Tables.TryGetValue(loc, out Dictionary<string, string> table) && table.TryGetValue(key, out string text))
                {
                    return text;
                }
            }
            return null;
        }

        private void Missing(string key)
        {
            if (_missingKeys.Add(key))
            {
                Debug.LogWarning($"[WARN][i18n] no string for '{key}' in {Locale}");
            }
        }

        private void ApplyAccess()
        {
            UiTheme.Apply(Settings);
            ApplyInput();        // auto_repeat lives in access
        }

        private void ApplyInput()
        {
            ShellInput.Configure(BindingsMap(), AccessOn("auto_repeat"));
            ShellInput.ConfigureAnalog(GameSettings.Number(Settings, "input", "deadzone"), GameSettings.Bool(Settings, "input", "invert_y"));
        }

        private void ApplyAudio()
        {
            AudioListener.volume = (float)GameSettings.Number(Settings, "audio", "master");
        }

        private void ApplyDisplay()
        {
            Application.targetFrameRate = (int)GameSettings.Number(Settings, "display", "frame_cap");   // 0 = uncapped
            if (Application.isBatchMode || Application.isEditor)
            {
                return;        // the editor's game view and a headless run keep their own window
            }
            QualitySettings.vSyncCount = GameSettings.Bool(Settings, "display", "vsync") ? 1 : 0;
            string mode = GameSettings.Text(Settings, "display", "mode");
            FullScreenMode fs = mode == "fullscreen" ? FullScreenMode.ExclusiveFullScreen
                              : mode == "borderless" ? FullScreenMode.FullScreenWindow : FullScreenMode.Windowed;
            var res = ((Dictionary<string, object>)Settings["display"])["resolution"] as List<object>;
            int w = res != null && res.Count == 2 ? (int)Json.ToNumber(res[0]) : Screen.width;
            int h = res != null && res.Count == 2 ? (int)Json.ToNumber(res[1]) : Screen.height;
            if (fs != FullScreenMode.Windowed)
            {
                w = Screen.currentResolution.width;
                h = Screen.currentResolution.height;
            }
            if (Screen.fullScreenMode != fs || Screen.width != w || Screen.height != h)
            {
                Screen.SetResolution(w, h, fs);
            }
        }

        private void UpdateLocale()
        {
            string wanted = LocaleOverride;
            if (wanted == "")
            {
                wanted = Settings.TryGetValue("language", out object l) && l is string s ? s : I18n.FALLBACK_LOCALE;
            }
            if (wanted != Locale)
            {
                Locale = wanted;
                LocaleChanged?.Invoke();
            }
        }

        private void ParseOptions()
        {
            DataDir = Environment.GetEnvironmentVariable("GAMEKIT_DATA_DIR") ?? "";
            LocaleOverride = Environment.GetEnvironmentVariable("GAMEKIT_LOCALE") ?? "";
            Drive = Environment.GetEnvironmentVariable("GAMEKIT_DRIVE") ?? "";
            Smoke = Environment.GetEnvironmentVariable("GAMEKIT_SMOKE") == "1";
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length; i++)
            {
                string value = i + 1 < args.Length ? args[i + 1] : "";
                switch (args[i])
                {
                    case "--data-dir": DataDir = value; i++; break;
                    case "--locale": LocaleOverride = value; i++; break;
                    case "--drive": Drive = value; i++; break;
                    case "--smoke": Smoke = true; break;
                }
            }
            if (DataDir == "")
            {
                DataDir = Application.persistentDataPath;
            }
            else if (!Path.IsPathRooted(DataDir))
            {
                // Relative to the project in the editor, to the player's folder in a build
                DataDir = Path.GetFullPath(Path.Combine(ShellFiles.ProjectRoot, DataDir));
            }
        }
    }
}
