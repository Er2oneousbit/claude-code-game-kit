// ---------------------------------------------------------------------------
// I18n.cs
// Purpose : Localized strings: a fallback chain (fr-CA -> fr -> en), {name} placeholders, one/other plurals,
//           and the pseudo-locale that finds untranslated, truncated and missing-glyph text before a
//           translator does. Checked against data/golden/shell.json ("tr", "plural", "pseudo").
// Usage   : var tables = I18n.TablesFromJson(Json.Parse(File.ReadAllText(path)));   // {"en": {"key": "text"}}
//           I18n.Tr(tables, "fr-CA", "greet", new Dictionary<string, object> { { "name", "Ana" } })
//           I18n.TrPlural(tables, locale, "apples", count)     // keys apples.one / apples.other, {n} filled
//           I18n.Pseudo("Play") == "[Pláý~~]"                  // run the whole UI with this to test layout
// Notes   : No UnityEngine types (EditMode tests run it). A missing key returns the key itself, so it shows
//           on screen instead of an empty label. Plurals cover one/other (English, French 0 and 1 are one,
//           Japanese, Chinese and Korean have no plural); add a language's rule in Plural before shipping
//           it. Placeholders {name}, %s, %d, %i, %f and %% pass through the pseudo-locale unchanged.
//
// Pseudocode:
//   chain(locale) = [locale, its base language, "en"] without repeats
//   tr: the first table in the chain with the key, placeholders filled ; none -> the key
//   pseudo: accented look-alikes, placeholders kept, + ceil(visible * PSEUDO_GROWTH) tildes, all in [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace {{GAME_SLUG}}.Core
{
    public static class I18n
    {
        // ---- Tunables ------------------------------------------------------------
        public const string FALLBACK_LOCALE = "en";
        public const double PSEUDO_GROWTH = 0.40;      // translated English runs about 40 % longer (SOP-19)
        public const string PSEUDO_PLACEHOLDERS = "sdif%";  // the letters after % that mark a printf placeholder

        private static readonly string[] NO_PLURAL = { "ja", "zh", "ko" };
        private static readonly string[] ZERO_IS_ONE = { "fr" };

        private static readonly Dictionary<char, char> PSEUDO = new Dictionary<char, char>
        {
            { 'a', 'á' }, { 'e', 'é' }, { 'i', 'í' }, { 'o', 'ó' }, { 'u', 'ú' }, { 'c', 'ç' }, { 'n', 'ñ' }, { 'y', 'ý' },
            { 'A', 'Á' }, { 'E', 'É' }, { 'I', 'Í' }, { 'O', 'Ó' }, { 'U', 'Ú' }, { 'C', 'Ç' }, { 'N', 'Ñ' }, { 'Y', 'Ý' },
        };

        /// <summary>"fr-CA" and "fr_CA" -> "fr".</summary>
        public static string BaseLanguage(string locale)
        {
            return locale.Split('-')[0].Split('_')[0];
        }

        /// <summary>The locales to look in, in order: fr-CA, fr, en.</summary>
        public static List<string> LocaleChain(string locale, string fallback = FALLBACK_LOCALE)
        {
            var chain = new List<string>();
            foreach (string loc in new[] { locale, BaseLanguage(locale), fallback })
            {
                if (!string.IsNullOrEmpty(loc) && !chain.Contains(loc))
                {
                    chain.Add(loc);
                }
            }
            return chain;
        }

        /// <summary>A string through the fallback chain with placeholders filled; a missing key returns the key.</summary>
        public static string Tr(Dictionary<string, Dictionary<string, string>> tables, string locale, string key,
                                IDictionary<string, object> args = null)
        {
            foreach (string loc in LocaleChain(locale))
            {
                if (tables.TryGetValue(loc, out Dictionary<string, string> table) && table.TryGetValue(key, out string text))
                {
                    return Fill(text, args);
                }
            }
            return key;
        }

        /// <summary>"one" or "other" for n in the locale's language.</summary>
        public static string Plural(string locale, double n)
        {
            string lang = BaseLanguage(locale);
            if (Array.IndexOf(NO_PLURAL, lang) >= 0)
            {
                return "other";
            }
            if (Array.IndexOf(ZERO_IS_ONE, lang) >= 0)
            {
                return n == 0 || n == 1 ? "one" : "other";
            }
            return n == 1 ? "one" : "other";
        }

        /// <summary>key.one or key.other for n, with {n} (and any other args) filled.</summary>
        public static string TrPlural(Dictionary<string, Dictionary<string, string>> tables, string locale, string key,
                                      double n, IDictionary<string, object> args = null)
        {
            var all = args != null ? new Dictionary<string, object>(args) : new Dictionary<string, object>();
            all["n"] = n;
            return Tr(tables, locale, key + "." + Plural(locale, n), all);
        }

        /// <summary>Replaces {name} with args[name]; unknown names stay as they are, so they show up.</summary>
        public static string Fill(string text, IDictionary<string, object> args)
        {
            if (args == null || args.Count == 0 || text.IndexOf('{') < 0)
            {
                return text;
            }
            var sb = new StringBuilder();
            int i = 0;
            while (i < text.Length)
            {
                if (text[i] == '{')
                {
                    int j = text.IndexOf('}', i);
                    if (j > i && args.TryGetValue(text.Substring(i + 1, j - i - 1), out object value))
                    {
                        sb.Append(FormatArg(value));
                        i = j + 1;
                        continue;
                    }
                }
                sb.Append(text[i]);
                i++;
            }
            return sb.ToString();
        }

        /// <summary>The pseudo-locale version of text: "Play" -> "[Pláý~~]".</summary>
        public static string Pseudo(string text)
        {
            var sb = new StringBuilder("[");
            int visible = 0;
            int i = 0;
            while (i < text.Length)
            {
                char c = text[i];
                if (c == '{')
                {
                    int j = text.IndexOf('}', i);
                    if (j > i)
                    {
                        sb.Append(text, i, j - i + 1);
                        i = j + 1;
                        continue;
                    }
                }
                if (c == '%' && i + 1 < text.Length && PSEUDO_PLACEHOLDERS.IndexOf(text[i + 1]) >= 0)
                {
                    sb.Append(text, i, 2);
                    i += 2;
                    continue;
                }
                if (char.IsHighSurrogate(c) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
                {
                    sb.Append(text, i, 2);             // one character outside the BMP (an emoji) counts once
                    visible++;
                    i += 2;
                    continue;
                }
                sb.Append(PSEUDO.TryGetValue(c, out char accented) ? accented : c);
                visible++;
                i++;
            }
            sb.Append('~', (int)Math.Ceiling(visible * PSEUDO_GROWTH));
            return sb.Append(']').ToString();
        }

        /// <summary>String tables from a parsed JSON object {"en": {"key": "text"}, ...}; non-string values are skipped.</summary>
        public static Dictionary<string, Dictionary<string, string>> TablesFromJson(object json)
        {
            var tables = new Dictionary<string, Dictionary<string, string>>();
            if (!(json is Dictionary<string, object> root))
            {
                return tables;
            }
            foreach (KeyValuePair<string, object> locale in root)
            {
                var table = new Dictionary<string, string>();
                if (locale.Value is Dictionary<string, object> entries)
                {
                    foreach (KeyValuePair<string, object> entry in entries)
                    {
                        if (entry.Value is string text)
                        {
                            table[entry.Key] = text;
                        }
                    }
                }
                tables[locale.Key] = table;
            }
            return tables;
        }

        // A placeholder value as text: whole numbers without ".0" (3 apples, not 3.0), invariant culture
        private static string FormatArg(object value)
        {
            if (value == null)
            {
                return "";
            }
            if (value is string s)
            {
                return s;
            }
            if (value is bool b)
            {
                return b ? "true" : "false";
            }
            if (Json.IsNumber(value))
            {
                return Json.FormatNumber(Json.ToNumber(value));
            }
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }
    }
}

// {{FOOTER}}
