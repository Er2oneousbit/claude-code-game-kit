// ---------------------------------------------------------------------------
// I18n.cs
// Purpose : Localized strings: a fallback chain (fr-CA -> fr -> en), {name} placeholders, CLDR plurals,
//           clean-language variants with a word mask, and the pseudo-locale that finds untranslated, truncated and
//           missing-glyph text before a translator does. Checked against data/golden/shell.json ("tr", "plural",
//           "plural_rules", "tr_clean", "mask_words", "mature_words", "pseudo").
// Usage   : var tables = I18n.TablesFromJson(Json.Parse(File.ReadAllText(path)));   // {"en": {"key": "text"}}
//           I18n.Tr(tables, "fr-CA", "greet", new Dictionary<string, object> { { "name", "Ana" } })
//           I18n.TrPlural(tables, locale, "apples", count)     // keys apples.one / apples.other, {n} filled
//           I18n.Pseudo("Play") == "[Pláý~~]"                  // run the whole UI with this to test layout
//           I18n.Tr(tables, "en", "guard.insult", null, true, words) // the @clean line, listed words masked
// Notes   : No UnityEngine types (EditMode tests run it). A missing key returns the key itself, so it shows
//           on screen instead of an empty label. Plurals are CLDR 46's rules for whole numbers
//           (tools/golden_vectors.py PLURAL_FAMILIES); each locale of the chain uses its own rule and falls back to
//           its .other. With clean on (content.clean_language) each locale gives key@clean, then key, and the filled
//           text goes through MaskWords, which walks code points (a surrogate pair is one) with the reference's
//           pinned ranges and case fold. Placeholders {name}, %s, %d, %i, %f and %% pass through the pseudo-locale
//           unchanged.
//
// Pseudocode:
//   chain(locale) = [locale, its base language, "en"] without repeats
//   tr: the first table in the chain with the key, placeholders filled ; none -> the key
//   pseudo: accented look-alikes, placeholders kept, + ceil(visible * PSEUDO_GROWTH) tildes, all in [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plurals with the .other fallback per
//           locale, @clean variants, MaskWords and MatureWords (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): CompileWords, MaskWordSet and WordCache, so the shell
//           folds its word list once per locale and list, not on every T() (#207)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace graveyard_shift.Core
{
    public static class I18n
    {
        // ---- Tunables ------------------------------------------------------------
        public const string FALLBACK_LOCALE = "en";
        public const double PSEUDO_GROWTH = 0.40;      // translated English runs about 40 % longer (SOP-19)
        public const string PSEUDO_PLACEHOLDERS = "sdif%";  // the letters after % that mark a printf placeholder

        public const string CLEAN_SUFFIX = "@clean";   // "guard.insult@clean": the line with clean language on (#207)
        public const string GRAWLIX = "#@$%";          // the mask: one character per code point, again for each word
        // CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES)
        private static readonly string[][] PLURAL_LANGUAGES =
        {
            new[] { "other", "ja zh ko vi th id ms lo my km yo ig jv su" },
            new[] { "one", "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr" },
            new[] { "zero_one", "hi bn fa gu kn hy" }, new[] { "one_many", "es it ca" },
            new[] { "zero_one_many", "fr pt" }, new[] { "one_21", "is mk" }, new[] { "fil", "fil tl" },
            new[] { "east_slavic", "ru uk be" }, new[] { "pl", "pl" }, new[] { "cs", "cs sk" }, new[] { "lt", "lt" },
            new[] { "balkan", "hr sr bs" }, new[] { "ro", "ro mo" }, new[] { "lv", "lv" }, new[] { "he", "he" },
            new[] { "sl", "sl" }, new[] { "ga", "ga" }, new[] { "ar", "ar" }, new[] { "cy", "cy" },
        };
        // code point ranges that are never part of a word (the reference's MASK_BOUNDARY_RANGES)
        private static readonly int[,] MASK_BOUNDARY_RANGES =
        {
            { 0x0080, 0x00BF }, { 0x00D7, 0x00D7 }, { 0x00F7, 0x00F7 }, { 0x2000, 0x2BFF }, { 0x2E00, 0x2E7F },
            { 0x3000, 0x303F }, { 0xFE00, 0xFE0F }, { 0xFE10, 0xFE1F }, { 0xFE30, 0xFE6F }, { 0xFEFF, 0xFEFF },
            { 0xFF00, 0xFF0F }, { 0xFF1A, 0xFF20 }, { 0xFF3B, 0xFF40 }, { 0xFF5B, 0xFF65 }, { 0x1F000, 0x1FAFF },
        };

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

        /// <summary>One table's text for key: key@clean first when clean is on, else key; null when neither.</summary>
        public static string Pick(Dictionary<string, Dictionary<string, string>> tables, string loc, string key, bool clean)
        {
            if (!tables.TryGetValue(loc, out Dictionary<string, string> table))
            {
                return null;
            }
            if (clean && table.TryGetValue(key + CLEAN_SUFFIX, out string cleanText))
            {
                return cleanText;
            }
            return table.TryGetValue(key, out string text) ? text : null;
        }

        /// <summary>The raw text through the chain (per locale @clean first when clean is on), or null.</summary>
        public static string Lookup(Dictionary<string, Dictionary<string, string>> tables, string locale, string key,
                                    bool clean = false)
        {
            foreach (string loc in LocaleChain(locale))
            {
                string text = Pick(tables, loc, key, clean);
                if (text != null)
                {
                    return text;
                }
            }
            return null;
        }

        /// <summary>Placeholders filled, then (clean on) the listed words masked.</summary>
        public static string Finish(string text, IDictionary<string, object> args, bool clean, IList<string> words)
        {
            string output = Fill(text, args);
            return clean && words != null && words.Count > 0 ? MaskWords(output, words) : output;
        }

        /// <summary>Finish with the words compiled already (CompileWords, the shell's cache).</summary>
        public static string Finish(string text, IDictionary<string, object> args, bool clean, HashSet<string> wordSet)
        {
            string output = Fill(text, args);
            return clean && wordSet != null && wordSet.Count > 0 ? MaskWordSet(output, wordSet) : output;
        }

        /// <summary>The word lists per locale and the chain's folded set: Get folds once per locale; setting Lists
        /// drops the fold.</summary>
        public sealed class WordCache
        {
            private Dictionary<string, List<string>> _lists = new Dictionary<string, List<string>>();
            private string _locale;
            private HashSet<string> _set;

            /// <summary>How many times Get folded (tests).</summary>
            public int Folds { get; private set; }

            public Dictionary<string, List<string>> Lists
            {
                get => _lists;
                set { _lists = value ?? new Dictionary<string, List<string>>(); _set = null; }
            }

            /// <summary>The words of every locale in locale's chain, folded (a fallback line can come from any).</summary>
            public HashSet<string> Get(string locale)
            {
                if (_set == null || _locale != locale)
                {
                    var words = new List<string>();
                    foreach (string loc in LocaleChain(locale))
                    {
                        if (_lists.TryGetValue(loc, out List<string> list))
                        {
                            words.AddRange(list);
                        }
                    }
                    _set = CompileWords(words);
                    _locale = locale;
                    Folds++;
                }
                return _set;
            }
        }

        /// <summary>A string through the fallback chain with placeholders filled; a missing key returns the key.
        /// clean: each locale gives key@clean, then key, and the text is masked with words.</summary>
        public static string Tr(Dictionary<string, Dictionary<string, string>> tables, string locale, string key,
                                IDictionary<string, object> args = null, bool clean = false, IList<string> words = null)
        {
            string text = Lookup(tables, locale, key, clean);
            return text == null ? key : Finish(text, args, clean, words);
        }

        /// <summary>The plural rule family: the full locale (pt-PT) first, then its language, then English's rule.</summary>
        public static string PluralFamily(string locale)
        {
            string norm = locale.Replace('_', '-').ToLowerInvariant();
            if (norm == "pt-pt" || norm.StartsWith("pt-pt-", StringComparison.Ordinal))
            {
                return "one_many";
            }
            string lang = norm.Split('-')[0];
            foreach (string[] fam in PLURAL_LANGUAGES)
            {
                if (Array.IndexOf(fam[1].Split(' '), lang) >= 0)
                {
                    return fam[0];
                }
            }
            return "one";
        }

        /// <summary>The CLDR plural category of a whole number (a negative one counts as its absolute value).</summary>
        public static string Plural(string locale, double count)
        {
            string fam = PluralFamily(locale);
            long n = Math.Abs((long)Math.Truncate(count));
            long m10 = n % 10, m100 = n % 100;
            bool In(long v, long lo, long hi) => v >= lo && v <= hi;
            switch (fam)
            {
                case "other": return "other";
                case "one": return n == 1 ? "one" : "other";
                case "zero_one": return n <= 1 ? "one" : "other";
                case "one_many":
                case "zero_one_many":
                    if (n == 1 || (n == 0 && fam == "zero_one_many")) return "one";
                    return n != 0 && n % 1000000 == 0 ? "many" : "other";
                case "one_21": return m10 == 1 && m100 != 11 ? "one" : "other";
                case "fil": return m10 == 4 || m10 == 6 || m10 == 9 ? "other" : "one";
                case "east_slavic":
                case "balkan":
                    if (m10 == 1 && m100 != 11) return "one";
                    if (In(m10, 2, 4) && !In(m100, 12, 14)) return "few";
                    return fam == "east_slavic" ? "many" : "other";
                case "pl":
                    if (n == 1) return "one";
                    return In(m10, 2, 4) && !In(m100, 12, 14) ? "few" : "many";
                case "cs": return n == 1 ? "one" : In(n, 2, 4) ? "few" : "other";
                case "lt":
                    if (In(m100, 11, 19)) return "other";
                    return m10 == 1 ? "one" : m10 >= 2 ? "few" : "other";
                case "ro":
                    if (n == 1) return "one";
                    return n == 0 || In(m100, 1, 19) ? "few" : "other";
                case "lv":
                    if (m10 == 0 || In(m100, 11, 19)) return "zero";
                    return m10 == 1 ? "one" : "other";
                case "he": return n == 1 ? "one" : n == 2 ? "two" : "other";
                case "sl": return m100 == 1 ? "one" : m100 == 2 ? "two" : In(m100, 3, 4) ? "few" : "other";
                case "ga": return n == 1 ? "one" : n == 2 ? "two" : In(n, 3, 6) ? "few" : In(n, 7, 10) ? "many" : "other";
                case "ar":
                    if (n == 0) return "zero";
                    if (n == 1) return "one";
                    if (n == 2) return "two";
                    return In(m100, 3, 10) ? "few" : m100 >= 11 ? "many" : "other";
                case "cy":
                    return n == 0 ? "zero" : n == 1 ? "one" : n == 2 ? "two" : n == 3 ? "few" : n == 6 ? "many" : "other";
                default: return "other";
            }
        }

        /// <summary>key.&lt;category&gt; through the chain, each locale with its own category, then its key.other.</summary>
        public static string LookupPlural(Dictionary<string, Dictionary<string, string>> tables, string locale, string key,
                                          double n, bool clean = false)
        {
            foreach (string loc in LocaleChain(locale))
            {
                string cat = Plural(loc, n);
                string text = Pick(tables, loc, key + "." + cat, clean);
                if (text == null && cat != "other")
                {
                    text = Pick(tables, loc, key + ".other", clean);
                }
                if (text != null)
                {
                    return text;
                }
            }
            return null;
        }

        /// <summary>The plural line for n, with {n} (and any other args) filled; nothing anywhere: key.&lt;category&gt;.</summary>
        public static string TrPlural(Dictionary<string, Dictionary<string, string>> tables, string locale, string key,
                                      double n, IDictionary<string, object> args = null, bool clean = false,
                                      IList<string> words = null)
        {
            var all = args != null ? new Dictionary<string, object>(args) : new Dictionary<string, object>();
            all["n"] = n;
            string text = LookupPlural(tables, locale, key, n, clean);
            return text == null ? key + "." + Plural(locale, n) : Finish(text, all, clean, words);
        }

        // ---- the word mask (#207) ------------------------------------------------------------------------------

        public static bool IsWordChar(int cp)
        {
            if (cp < 0x80)
            {
                return (cp >= 0x30 && cp <= 0x39) || (cp >= 0x41 && cp <= 0x5A) || (cp >= 0x61 && cp <= 0x7A);
            }
            for (int r = 0; r < MASK_BOUNDARY_RANGES.GetLength(0); r++)
            {
                if (cp >= MASK_BOUNDARY_RANGES[r, 0] && cp <= MASK_BOUNDARY_RANGES[r, 1])
                {
                    return false;
                }
            }
            return true;
        }

        /// <summary>The pinned case fold (the reference's fold_char): one code point to one code point.</summary>
        public static int FoldChar(int cp)
        {
            if ((cp >= 0x41 && cp <= 0x5A) || (cp >= 0xC0 && cp <= 0xDE && cp != 0xD7)) return cp + 0x20;
            if (cp == 0x130) return 0x69;
            if (cp == 0x178) return 0xFF;
            if (((cp >= 0x100 && cp <= 0x12F) || (cp >= 0x132 && cp <= 0x137) || (cp >= 0x14A && cp <= 0x177)) && cp % 2 == 0) return cp + 1;
            if (((cp >= 0x139 && cp <= 0x148) || (cp >= 0x179 && cp <= 0x17E)) && cp % 2 == 1) return cp + 1;
            if (cp >= 0x391 && cp <= 0x3AB && cp != 0x3A2) return cp + 0x20;
            if (cp == 0x386) return 0x3AC;
            if (cp >= 0x388 && cp <= 0x38A) return cp + 0x25;
            if (cp == 0x38C) return 0x3CC;
            if (cp == 0x38E || cp == 0x38F) return cp + 0x3F;
            if (cp == 0x3C2) return 0x3C3;
            if (cp >= 0x400 && cp <= 0x40F) return cp + 0x50;
            if (cp >= 0x410 && cp <= 0x42F) return cp + 0x20;
            return cp;
        }

        // The code point at i (a surrogate pair is one) and how many UTF-16 units it takes
        private static int CodePointAt(string s, int i, out int units)
        {
            if (char.IsHighSurrogate(s[i]) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]))
            {
                units = 2;
                return char.ConvertToUtf32(s[i], s[i + 1]);
            }
            units = 1;
            return s[i];
        }

        // Splits text into (start, length in units, folded key or null for a gap, code points)
        private static List<(int start, int len, string key, int count)> Scan(string text)
        {
            var parts = new List<(int, int, string, int)>();
            int i = 0;
            while (i < text.Length)
            {
                int cp = CodePointAt(text, i, out int units);
                if (!IsWordChar(cp))
                {
                    parts.Add((i, units, null, 0));
                    i += units;
                    continue;
                }
                int start = i, count = 0;
                var key = new StringBuilder();
                while (i < text.Length)
                {
                    cp = CodePointAt(text, i, out units);
                    if (!IsWordChar(cp))
                    {
                        break;
                    }
                    key.Append(FoldChar(cp)).Append(',');
                    count++;
                    i += units;
                }
                parts.Add((start, i - start, key.ToString(), count));
            }
            return parts;
        }

        /// <summary>The folded set the mask matches against: build it once per word list (T runs for every label
        /// every frame).</summary>
        public static HashSet<string> CompileWords(IList<string> words)
        {
            var wanted = new HashSet<string>();
            foreach (string w in words ?? (IList<string>)Array.Empty<string>())
            {
                var parts = Scan(w ?? "");
                if (parts.Count == 1 && parts[0].key != null)
                {
                    wanted.Add(parts[0].key);
                }
            }
            return wanted;
        }

        /// <summary>text with every whole word that is in words (case folded) replaced by a same-length grawlix.</summary>
        public static string MaskWords(string text, IList<string> words)
        {
            return MaskWordSet(text, CompileWords(words));
        }

        /// <summary>MaskWords with the list compiled already (CompileWords).</summary>
        public static string MaskWordSet(string text, HashSet<string> wanted)
        {
            if (wanted.Count == 0)
            {
                return text;
            }
            var sb = new StringBuilder();
            foreach (var p in Scan(text))
            {
                if (p.key != null && wanted.Contains(p.key))
                {
                    for (int k = 0; k < p.count; k++)
                    {
                        sb.Append(GRAWLIX[k % GRAWLIX.Length]);
                    }
                }
                else
                {
                    sb.Append(text, p.start, p.len);
                }
            }
            return sb.ToString();
        }

        /// <summary>A word list file's words (data/i18n/mature/&lt;locale&gt;.json: {"words": [...]}); anything else
        /// (or null, no file) is no words.</summary>
        public static List<string> MatureWords(object json)
        {
            var output = new List<string>();
            if (json is Dictionary<string, object> root && root.TryGetValue("words", out object words)
                && words is List<object> list)
            {
                foreach (object w in list)
                {
                    if (w is string s)
                    {
                        output.Add(s);
                    }
                }
            }
            return output;
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
