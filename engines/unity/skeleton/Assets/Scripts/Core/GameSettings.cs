// ---------------------------------------------------------------------------
// GameSettings.cs
// Purpose : The player's settings: built-in defaults, the schema every field is checked against, and a
//           loader that repairs a damaged or old settings.json instead of crashing or resetting it.
//           Checked against data/golden/shell.json ("defaults" and "settings_load").
// Usage   : var r = GameSettings.LoadFile(Path.Combine(Application.persistentDataPath, "settings.json"));
//           var s = r.Settings;                  // r.Problems lists what was fixed (log it, never nag the player)
//           double master = GameSettings.Number(s, "audio", "master");
//           shake.Update(dt, GameSettings.EffectiveShake(s)); if (GameSettings.TelemetryAllowed(s)) ...
//           GameSettings.SaveFile(path, s);      // atomic, keeps settings.json.bak
// Notes   : No UnityEngine types (EditMode tests run it). Settings are a JSON value tree (Json.cs): sections
//           are Dictionary<string, object>, numbers are double. Missing fields take defaults, bad ones are
//           fixed (one problem each: a number is clamped, a wrong type or unknown choice falls back to the
//           default), and unknown keys are kept as they are, so a newer game's file survives an older build.
//           Change a field = change DEFAULTS and FIELDS here, then the reference (tools/golden_vectors.py,
//           SOP-18) so every port agrees.
//
// Pseudocode (Load):
//   parse (unreadable or not an object -> defaults + one problem) ; copy every key of the file
//   version = 1 ; language must be a string of 2..12 characters
//   per schema section: a non-object section counts as one problem ; per field: missing -> default,
//   present -> Fix (bool | number clamp | choice | resolution) ; input.bindings: lists of strings only
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace {{GAME_SLUG}}.Core
{
    public sealed class SettingsLoadResult
    {
        public Dictionary<string, object> Settings;
        public List<string> Problems;
    }

    public static class GameSettings
    {
        // ---- Tunables ------------------------------------------------------------
        public const int VERSION = 1;
        public const string FILE_NAME = "settings.json";
        public const int LANGUAGE_MIN = 2;             // "en" .. "zh-Hant-TW" style codes
        public const int LANGUAGE_MAX = 12;
        public const string PROBLEM_UNREADABLE = "unreadable";
        public const string PROBLEM_NOT_OBJECT = "not an object";

        public static readonly string[] DIFFICULTIES = { "story", "easy", "normal", "hard" };
        public static readonly string[] COLORBLIND = { "none", "protanopia", "deuteranopia", "tritanopia" };
        public static readonly string[] SUB_SIZES = { "small", "medium", "large", "xl" };
        public static readonly string[] DISPLAY_MODES = { "windowed", "fullscreen", "borderless" };
        public static readonly double[] FRAME_CAPS = { 0, 30, 60, 120, 144, 240 };   // 0 = uncapped
        public static readonly string[] CONSENT = { "unset", "yes", "no" };

        private static readonly string[] SECTIONS = { "display", "audio", "access", "input", "telemetry" };

        // The defaults; DefaultValue and Defaults() hand out copies, never this tree
        private static readonly Dictionary<string, object> DEFAULTS = new Dictionary<string, object>
        {
            { "version", (double)VERSION },
            { "display", new Dictionary<string, object>
                {
                    { "mode", "windowed" }, { "vsync", true }, { "frame_cap", 0.0 },
                    { "resolution", new List<object> { 1920.0, 1080.0 } }, { "ui_scale", 1.0 },
                }
            },
            { "audio", new Dictionary<string, object>
                {
                    { "master", 1.0 }, { "music", 0.8 }, { "sfx", 1.0 }, { "ui", 1.0 }, { "voice", 1.0 },
                    { "mono", false },
                }
            },
            { "language", "en" },
            { "access", new Dictionary<string, object>
                {
                    { "text_scale", 1.0 }, { "subtitles", true }, { "subtitle_size", "medium" },
                    { "subtitle_background", 0.6 }, { "speaker_names", true }, { "subtitle_barks", false },
                    { "captions_sfx", false }, { "colorblind", "none" }, { "reduce_motion", false },
                    { "shake_scale", 1.0 }, { "flash_limit", true }, { "hold_to_toggle", false },
                    { "difficulty", "normal" }, { "game_speed", 1.0 }, { "readable_font", false },
                    { "line_spacing", 1.0 }, { "subtitle_hold", false }, { "timing_scale", 1.0 },
                    { "auto_repeat", false }, { "narration", false },
                }
            },
            { "input", new Dictionary<string, object>
                {
                    { "bindings", Bindings.Defaults() }, { "deadzone", 0.2 }, { "invert_y", false },
                    { "glyphs", "auto" },
                }
            },
            { "telemetry", new Dictionary<string, object> { { "consent", "unset" } } },
        };

        // ---- Schema: one rule per field (the default comes from DEFAULTS) -----------

        private enum Kind { Number, Bool, Choice, Resolution }

        private sealed class Rule
        {
            public string Section;
            public string Field;
            public Kind Kind;
            public double Lo;
            public double Hi;
            public object[] Choices;
        }

        private static Rule Num(string section, string field, double lo, double hi)
        {
            return new Rule { Section = section, Field = field, Kind = Kind.Number, Lo = lo, Hi = hi };
        }

        private static Rule Flag(string section, string field)
        {
            return new Rule { Section = section, Field = field, Kind = Kind.Bool };
        }

        private static Rule OneOf<T>(string section, string field, T[] choices)
        {
            var values = new object[choices.Length];
            Array.Copy(choices, values, choices.Length);
            return new Rule { Section = section, Field = field, Kind = Kind.Choice, Choices = values };
        }

        private static readonly Rule[] FIELDS =
        {
            OneOf("display", "mode", DISPLAY_MODES), Flag("display", "vsync"), OneOf("display", "frame_cap", FRAME_CAPS),
            new Rule { Section = "display", Field = "resolution", Kind = Kind.Resolution },
            Num("display", "ui_scale", 0.75, 2.0),
            Num("audio", "master", 0.0, 1.0), Num("audio", "music", 0.0, 1.0), Num("audio", "sfx", 0.0, 1.0),
            Num("audio", "ui", 0.0, 1.0), Num("audio", "voice", 0.0, 1.0), Flag("audio", "mono"),
            Num("access", "text_scale", 0.75, 2.0), Flag("access", "subtitles"),
            OneOf("access", "subtitle_size", SUB_SIZES), Num("access", "subtitle_background", 0.0, 1.0),
            Flag("access", "speaker_names"), Flag("access", "subtitle_barks"), Flag("access", "captions_sfx"),
            OneOf("access", "colorblind", COLORBLIND), Flag("access", "reduce_motion"),
            Num("access", "shake_scale", 0.0, 1.0), Flag("access", "flash_limit"), Flag("access", "hold_to_toggle"),
            OneOf("access", "difficulty", DIFFICULTIES), Num("access", "game_speed", 0.5, 1.0),
            Flag("access", "readable_font"), Num("access", "line_spacing", 1.0, 2.0), Flag("access", "subtitle_hold"),
            Num("access", "timing_scale", 1.0, 3.0), Flag("access", "auto_repeat"), Flag("access", "narration"),
            Num("input", "deadzone", 0.0, 0.9), Flag("input", "invert_y"), OneOf("input", "glyphs", Bindings.GLYPH_SETS),
            OneOf("telemetry", "consent", CONSENT),
        };

        // ---- Defaults ----------------------------------------------------------------

        /// <summary>A fresh copy of the built-in defaults.</summary>
        public static Dictionary<string, object> Defaults()
        {
            return (Dictionary<string, object>)Json.DeepCopy(DEFAULTS);
        }

        /// <summary>A copy of one field's default. Throws KeyNotFoundException for a field the kit does not define.</summary>
        public static object DefaultValue(string section, string field)
        {
            return Json.DeepCopy(((Dictionary<string, object>)DEFAULTS[section])[field]);
        }

        // ---- Loading -------------------------------------------------------------------

        /// <summary>Settings from the file's text (null = no file yet): every field valid, plus what was fixed.</summary>
        public static SettingsLoadResult Load(string text)
        {
            var problems = new List<string>();
            object parsed;
            if (text == null)
            {
                parsed = new Dictionary<string, object>();
            }
            else if (!Json.TryParse(text, out parsed))
            {
                return new SettingsLoadResult { Settings = Defaults(), Problems = new List<string> { PROBLEM_UNREADABLE } };
            }
            if (!(parsed is Dictionary<string, object> raw))
            {
                return new SettingsLoadResult { Settings = Defaults(), Problems = new List<string> { PROBLEM_NOT_OBJECT } };
            }
            var output = (Dictionary<string, object>)Json.DeepCopy(raw);
            output["version"] = (double)VERSION;
            bool hasLanguage = raw.TryGetValue("language", out object language);
            if (language is string code && CodePoints(code) >= LANGUAGE_MIN && CodePoints(code) <= LANGUAGE_MAX)
            {
                output["language"] = code;
            }
            else
            {
                output["language"] = DefaultValue("language");
                if (hasLanguage)
                {
                    problems.Add("language");
                }
            }
            foreach (string section in SECTIONS)
            {
                var src = new Dictionary<string, object>();
                if (raw.TryGetValue(section, out object value))
                {
                    if (value is Dictionary<string, object> obj)
                    {
                        src = obj;
                    }
                    else
                    {
                        problems.Add(section);
                    }
                }
                var sec = (Dictionary<string, object>)Json.DeepCopy(src);
                foreach (Rule rule in FIELDS)
                {
                    if (rule.Section != section)
                    {
                        continue;
                    }
                    object def = DefaultValue(section, rule.Field);
                    if (src.TryGetValue(rule.Field, out object given))
                    {
                        object fixedValue = Fix(rule, given, def, out bool bad);
                        if (bad)
                        {
                            problems.Add(section + "." + rule.Field);
                        }
                        sec[rule.Field] = Json.DeepCopy(fixedValue);
                    }
                    else
                    {
                        sec[rule.Field] = def;
                    }
                }
                if (section == "input")
                {
                    sec["bindings"] = src.TryGetValue("bindings", out object b) ? FixBindings(b, problems) : Bindings.Defaults();
                }
                output[section] = sec;
            }
            return new SettingsLoadResult { Settings = output, Problems = problems };
        }

        /// <summary>Load from a file: no file = defaults without problems; an unreadable file falls back to its .bak.</summary>
        public static SettingsLoadResult LoadFile(string path)
        {
            SettingsLoadResult result = Load(AtomicFile.ReadOrNull(path));
            bool broken = result.Problems.Count == 1
                          && (result.Problems[0] == PROBLEM_UNREADABLE || result.Problems[0] == PROBLEM_NOT_OBJECT);
            if (broken)
            {
                string backup = AtomicFile.ReadOrNull(path + AtomicFile.BAK_SUFFIX);
                if (backup != null && IsObjectText(backup))
                {
                    SettingsLoadResult fromBackup = Load(backup);
                    fromBackup.Problems.Insert(0, $"{FILE_NAME} {result.Problems[0]}, loaded the backup");
                    return fromBackup;
                }
            }
            return result;
        }

        /// <summary>Writes the settings atomically (keeps the previous readable file as .bak).</summary>
        public static void SaveFile(string path, Dictionary<string, object> settings)
        {
            AtomicFile.Write(path, ToText(settings), true, IsObjectText);
        }

        /// <summary>The settings as file text (one-space indent, like the kit's other JSON files).</summary>
        public static string ToText(Dictionary<string, object> settings)
        {
            return Json.Stringify(settings, 1) + "\n";
        }

        // ---- Reading fields ------------------------------------------------------------

        /// <summary>A number field; a missing or wrong-typed one gives the built-in default.</summary>
        public static double Number(Dictionary<string, object> settings, string section, string field)
        {
            object v = Field(settings, section, field);
            return Json.IsNumber(v) ? Json.ToNumber(v) : Json.ToNumber(DefaultValue(section, field));
        }

        /// <summary>A bool field; a missing or wrong-typed one gives the built-in default.</summary>
        public static bool Bool(Dictionary<string, object> settings, string section, string field)
        {
            return Field(settings, section, field) is bool b ? b : (bool)DefaultValue(section, field);
        }

        /// <summary>A string field; a missing or wrong-typed one gives the built-in default.</summary>
        public static string Text(Dictionary<string, object> settings, string section, string field)
        {
            return Field(settings, section, field) as string ?? (string)DefaultValue(section, field);
        }

        /// <summary>The shake intensity the juice should use: 0 with reduce motion, else the player's shake scale.</summary>
        public static double EffectiveShake(Dictionary<string, object> settings)
        {
            return Bool(settings, "access", "reduce_motion") ? 0.0 : Number(settings, "access", "shake_scale");
        }

        /// <summary>Telemetry is recorded only after an explicit yes.</summary>
        public static bool TelemetryAllowed(Dictionary<string, object> settings)
        {
            return Text(settings, "telemetry", "consent") == "yes";
        }

        // ---- Internals -------------------------------------------------------------------

        private static object DefaultValue(string key)
        {
            return Json.DeepCopy(DEFAULTS[key]);
        }

        private static object Field(Dictionary<string, object> settings, string section, string field)
        {
            if (settings != null && settings.TryGetValue(section, out object sec) && sec is Dictionary<string, object> obj
                && obj.TryGetValue(field, out object value))
            {
                return value;
            }
            return null;
        }

        // One field: the fixed value, and bad = true when the file's value had to change
        private static object Fix(Rule rule, object value, object def, out bool bad)
        {
            bad = false;
            switch (rule.Kind)
            {
                case Kind.Bool:
                    if (value is bool)
                    {
                        return value;
                    }
                    break;
                case Kind.Number:
                    if (Json.IsNumber(value) && !double.IsNaN(Json.ToNumber(value)))
                    {
                        double given = Json.ToNumber(value);
                        double clamped = Math.Min(Math.Max(given, rule.Lo), rule.Hi);
                        bad = clamped != given;
                        return clamped;
                    }
                    break;
                case Kind.Choice:
                    foreach (object allowed in rule.Choices)
                    {
                        bool same = allowed is string a ? value is string v && a == v
                                  : Json.IsNumber(value) && Json.ToNumber(allowed) == Json.ToNumber(value);
                        if (same)
                        {
                            return allowed;
                        }
                    }
                    break;
                case Kind.Resolution:
                    if (value is List<object> pair && pair.Count == 2 && IsWholeAtLeastOne(pair[0]) && IsWholeAtLeastOne(pair[1]))
                    {
                        return new List<object> { Json.ToNumber(pair[0]), Json.ToNumber(pair[1]) };
                    }
                    break;
            }
            bad = true;
            return def;
        }

        private static bool IsWholeAtLeastOne(object n)
        {
            if (!Json.IsNumber(n))
            {
                return false;
            }
            double d = Json.ToNumber(n);
            return !double.IsInfinity(d) && d >= 1.0 && d == Math.Floor(d);
        }

        private static Dictionary<string, object> FixBindings(object value, List<string> problems)
        {
            Dictionary<string, object> output = Bindings.Defaults();
            if (!(value is Dictionary<string, object> given))
            {
                problems.Add("input.bindings");
                return output;
            }
            foreach (KeyValuePair<string, object> entry in given)
            {
                if (!(entry.Value is List<object> list))
                {
                    problems.Add("input.bindings." + entry.Key);   // that action keeps its default
                    continue;
                }
                var clean = new List<object>();
                foreach (object b in list)
                {
                    if (b is string)
                    {
                        clean.Add(b);
                    }
                }
                if (clean.Count != list.Count)
                {
                    problems.Add("input.bindings." + entry.Key);
                }
                output[entry.Key] = clean;
            }
            return output;
        }

        private static bool IsObjectText(string text)
        {
            return Json.TryParse(text, out object v) && v is Dictionary<string, object>;
        }

        // Characters as Python and the other ports count them: a surrogate pair is one
        private static int CodePoints(string s)
        {
            int n = 0;
            for (int i = 0; i < s.Length; i++)
            {
                if (!(char.IsLowSurrogate(s[i]) && i > 0 && char.IsHighSurrogate(s[i - 1])))
                {
                    n++;
                }
            }
            return n;
        }
    }
}

// {{FOOTER}}
