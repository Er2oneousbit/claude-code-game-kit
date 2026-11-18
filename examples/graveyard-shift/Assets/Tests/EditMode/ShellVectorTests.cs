// ---------------------------------------------------------------------------
// ShellVectorTests.cs
// Purpose : Runs every case of data/golden/shell.json through the Core shell logic (default settings,
//           settings load and repair, rebinding, glyphs, save load and migration, tr, plural, pseudo-locale):
//           one test per case.
// Usage   : python tools/dev.py test              (or --filter Shell)
// Notes   : The expected values come from the file at test time (tools/golden_vectors.py writes it); never
//           copy them in here. A case type without a runner fails, so a new vector type cannot be skipped.
//           Problems are compared as a count: the wording may differ between ports, the number may not.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the display_staging cases (DisplayStaging, the
//           Display tab's Apply and its keep-or-revert confirm, #308)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the content switches, plural_rules (CLDR), tr_clean,
//           mask_words and mature_words; plural cases read their key from the case (#171, #207)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): I18n.WordCache folds once and follows new lists and
//           locales, and its cost against folding per call (#207)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using graveyard_shift.Core;
using G = graveyard_shift.Tests.GoldenVectors;

namespace graveyard_shift.Tests
{
    public class ShellVectorTests
    {
        private const string FILE = "shell.json";

        private static readonly string[] REQUIRED_TYPES =
        {
            "defaults", "settings_load", "rebind", "glyph_set", "glyph_name", "prompt_binding", "save_load", "tr",
            "plural", "pseudo", "narration", "display_staging", "plural_rules", "tr_clean", "mask_words", "mature_words",
        };
        private const int MIN_STAGING_CASES = 5;    // #308: the Display tab's Apply scripts

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Shell");
        }

        [Test]
        public void Shell_EveryRequiredTypeHasCases()
        {
            var seen = new HashSet<string>();
            int staging = 0;
            foreach (object c in G.Cases(FILE))
            {
                string type = G.Str((Dictionary<string, object>)c, "type");
                seen.Add(type);
                staging += type == "display_staging" ? 1 : 0;
            }
            Assert.GreaterOrEqual(staging, MIN_STAGING_CASES, $"{FILE}: too few display_staging cases");
            foreach (string type in REQUIRED_TYPES)
            {
                Assert.IsTrue(seen.Contains(type), $"{FILE} has no '{type}' case");
            }
        }

        [Test]
        public void WordCache_FoldsOnceAndFollowsNewListsAndLocales()
        {
            var cache = new I18n.WordCache { Lists = new Dictionary<string, List<string>> { { "en", new List<string> { "damn" } } } };
            Assert.AreEqual("#@$%, bob", I18n.MaskWordSet("Damn, bob", cache.Get("en")));
            Assert.AreEqual("#@$%, bob", I18n.MaskWordSet("Damn, bob", cache.Get("en")));
            Assert.AreEqual(1, cache.Folds, "the second Get reused the fold");
            cache.Lists = new Dictionary<string, List<string>>
            {
                { "en", new List<string> { "bob" } }, { "fr", new List<string> { "merde" } },
            };
            Assert.AreEqual("Damn, #@$", I18n.MaskWordSet("Damn, bob", cache.Get("en")), "a new list drops the old fold");
            Assert.AreEqual("#@$%#, #@$", I18n.MaskWordSet("Merde, bob", cache.Get("fr")), "a new chain: fr's words join");
        }

        [Test]
        public void WordCache_IsATenthOfFoldingPerCallOrLess()
        {
            var words = new List<string>();
            for (int k = 0; k < 3000; k++)
            {
                words.Add("word" + k);
            }
            var tables = new Dictionary<string, Dictionary<string, string>>
            {
                { "en", new Dictionary<string, string> { { "label", "A settings label with {name} in it" } } },
            };
            var args = new Dictionary<string, object> { { "name", "x" } };
            var cache = new I18n.WordCache { Lists = new Dictionary<string, List<string>> { { "en", words } } };
            var watch = System.Diagnostics.Stopwatch.StartNew();
            for (int k = 0; k < 100; k++)
            {
                I18n.Tr(tables, "en", "label", args, true, words);
            }
            double uncached = watch.Elapsed.TotalMilliseconds;
            watch.Restart();
            for (int k = 0; k < 100; k++)
            {
                I18n.Finish(I18n.Lookup(tables, "en", "label", true), args, true, cache.Get("en"));
            }
            double cached = watch.Elapsed.TotalMilliseconds;
            TestContext.WriteLine($"T_COST 100 labels, 3000 words: uncached {uncached:F1} ms, cached {cached:F1} ms");
            Assert.Less(cached, uncached / 10, "the folded set is built once, not per label");
        }

        [Test]
        public void Shell_SaveVersionMatchesTheVectors()
        {
            Assert.AreEqual((int)G.Num(G.Load(FILE), "save_version"), SaveStore.SAVE_VERSION,
                            "SaveStore.SAVE_VERSION differs from the vectors: add the migration, then regenerate the reference");
        }

        [TestCaseSource(nameof(Cases))]
        public void Shell(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            double tol = G.Tolerance(FILE);
            string type = G.Str(c, "type");
            string where = $"{type} '{G.Str(c, "name")}'";
            switch (type)
            {
                case "defaults":
                    G.AssertClose(GameSettings.Defaults(), G.Get(c, "expect"), tol, where);
                    break;
                case "settings_load": RunSettingsLoad(c, tol, where); break;
                case "rebind": RunRebind(c, tol, where); break;
                case "glyph_set":
                    Points(c, tol, where, pt => Bindings.GlyphSet((string)pt[0], (string)pt[1]), 2);
                    break;
                case "glyph_name":
                    Points(c, tol, where, pt => Bindings.GlyphName((string)pt[0], (string)pt[1]), 2);
                    break;
                case "prompt_binding":
                    var bindings = G.Obj(c, "bindings");
                    Points(c, tol, where, pt => Bindings.PromptBinding(bindings, (string)pt[0], (string)pt[1]), 2);
                    break;
                case "save_load": RunSaveLoad(c, tol, where); break;
                case "tr":
                    var tables = I18n.TablesFromJson(G.Get(c, "tables"));
                    Points(c, tol, where, pt => I18n.Tr(tables, (string)pt[0], (string)pt[1], (Dictionary<string, object>)pt[2]), 3);
                    break;
                case "plural": RunPlural(c, tol, where); break;
                case "pseudo":
                    Points(c, tol, where, pt => I18n.Pseudo((string)pt[0]), 1);
                    break;
                case "narration":
                    Points(c, tol, where, pt => Bindings.NarrationLine((string)pt[0], (string)pt[1], (string)pt[2]), 3);
                    break;
                case "display_staging": RunDisplayStaging(c, tol, where); break;
                case "plural_rules": RunPluralRules(c, tol, where); break;
                case "tr_clean":
                    var cleanTables = I18n.TablesFromJson(G.Get(c, "tables"));
                    Points(c, tol, where, pt => pt[2] == null
                        ? I18n.Tr(cleanTables, (string)pt[0], (string)pt[1], (Dictionary<string, object>)pt[3], (bool)pt[4], Words(pt[5]))
                        : I18n.TrPlural(cleanTables, (string)pt[0], (string)pt[1], Json.ToNumber(pt[2]),
                                        (Dictionary<string, object>)pt[3], (bool)pt[4], Words(pt[5])), 6);
                    break;
                case "mask_words":
                    Assert.AreEqual(G.Str(c, "grawlix"), I18n.GRAWLIX, where + " grawlix");
                    Points(c, tol, where, pt => I18n.MaskWords((string)pt[0], Words(pt[1])), 2);
                    break;
                case "mature_words":
                    Points(c, tol, where, pt =>
                    {
                        object parsed = null;
                        if (pt[0] is string text)
                        {
                            Json.TryParse(text, out parsed);
                        }
                        return I18n.MatureWords(parsed).ConvertAll(w => (object)w);
                    }, 1);
                    break;
                default:
                    Assert.Fail($"unknown case type '{type}' in {FILE}: add a runner for it here");
                    break;
            }
        }

        private static void RunSettingsLoad(Dictionary<string, object> c, double tol, string where)
        {
            SettingsLoadResult r = GameSettings.Load(G.Str(c, "input"));
            G.AssertClose(r.Settings, G.Get(c, "expect"), tol, where + " settings");
            Assert.AreEqual((int)G.Num(c, "problems"), r.Problems.Count,
                            $"{where}: problem count (got: {string.Join(" | ", r.Problems)})");
            G.AssertClose(GameSettings.EffectiveShake(r.Settings), G.Get(c, "effective_shake"), tol, where + " effective_shake");
            G.AssertClose(GameSettings.TelemetryAllowed(r.Settings), G.Get(c, "telemetry_allowed"), tol, where + " telemetry_allowed");
            G.AssertClose(GameSettings.BloodEnabled(r.Settings), G.Get(c, "blood_enabled"), tol, where + " blood_enabled");
            G.AssertClose(GameSettings.CleanLanguage(r.Settings), G.Get(c, "clean_language"), tol, where + " clean_language");
        }

        private static void RunRebind(Dictionary<string, object> c, double tol, string where)
        {
            RebindResult r = Bindings.Rebind(G.Obj(c, "bindings"), G.Str(c, "action"), (int)G.Num(c, "slot"), G.Str(c, "binding"));
            var conflicts = new List<object>();
            foreach ((string action, int slot) in r.Conflicts)
            {
                conflicts.Add(new List<object> { action, slot });
            }
            G.AssertClose(G.Make("bindings", r.Bindings, "conflicts", conflicts), G.Get(c, "expect"), tol, where);
        }

        private static void RunSaveLoad(Dictionary<string, object> c, double tol, string where)
        {
            G.AssertClose(SaveStore.SAVE_VERSION, G.Get(c, "current_version"), tol, where + " current_version");
            SaveLoadResult r = SaveStore.LoadFromText(G.Str(c, "primary"), G.Str(c, "backup"));
            var actual = G.Make("envelope", r.Envelope, "source", r.Source, "problems", r.Problems.Count);
            G.AssertClose(actual, G.Get(c, "expect"), tol, where + $" (problems: {string.Join(" | ", r.Problems)})");
        }

        // #308: a script of [op, args...] steps; after each, what it returned and the staging's whole state
        private static void RunDisplayStaging(Dictionary<string, object> c, double tol, string where)
        {
            Assert.AreEqual(G.Num(c, "confirm_s"), DisplayStaging.CONFIRM_S, $"{where}: confirm seconds");
            var st = new DisplayStaging(G.Obj(c, "applied"));
            foreach (object s in G.List(c, "steps"))
            {
                var step = (Dictionary<string, object>)s;
                var op = (List<object>)step["op"];
                string kind = (string)op[0];
                object outValue = null;
                List<(string Field, object Value)> calls = new List<(string, object)>();
                switch (kind)
                {
                    case "stage": outValue = st.Stage((string)op[1], op[2]); break;
                    case "apply": calls = st.Apply(); break;
                    case "tick": calls = st.Tick(Json.ToNumber(op[1])); break;
                    case "keep": st.Keep(); break;
                    case "revert": calls = st.Revert(); break;
                    case "back":
                        (string what, List<(string Field, object Value)> backCalls) = st.Back();
                        outValue = what;
                        calls = backCalls;
                        break;
                    default:
                        Assert.Fail($"{where}: unknown op {Json.Stringify(op)}");
                        break;
                }
                var called = new List<object>();
                foreach ((string field, object value) in calls)
                {
                    called.Add(new List<object> { field, value });
                }
                var shown = new Dictionary<string, object>();
                foreach (string f in DisplayStaging.APPLY_ORDER)
                {
                    shown[f] = st.Value(f);
                }
                int? secs = st.Seconds();
                var actual = G.Make("out", outValue, "calls", called, "pending", st.Pending, "shown", shown,
                                    "applied", st.Applied, "seconds", secs.HasValue ? (object)(double)secs.Value : null);
                var expected = G.Make("out", step["out"], "calls", step["calls"], "pending", step["pending"],
                                      "shown", step["shown"], "applied", step["applied"], "seconds", step["seconds"]);
                G.AssertClose(actual, expected, tol, $"{where} step {Json.Stringify(op)}");
            }
        }

        private static void RunPlural(Dictionary<string, object> c, double tol, string where)
        {
            var tables = I18n.TablesFromJson(G.Get(c, "tables"));
            foreach (object p in G.List(c, "points"))
            {
                var pt = (List<object>)p;                  // [locale, n, plural form, tr_plural text]
                string locale = (string)pt[0];
                double n = Json.ToNumber(pt[1]);
                string key = G.Get(c, "key") as string ?? "apples";
                var actual = new List<object> { I18n.Plural(locale, n), I18n.TrPlural(tables, locale, key, n) };
                G.AssertClose(actual, pt.GetRange(2, 2), tol, $"{where} {Json.Stringify(pt)}");
            }
        }

        private static void RunPluralRules(Dictionary<string, object> c, double tol, string where)
        {
            foreach (object s in G.List(c, "sweep"))
            {
                var sw = (List<object>)s;                  // [locale, first n, "cat cat ..."]
                string locale = (string)sw[0];
                double start = Json.ToNumber(sw[1]);
                string[] cats = ((string)sw[2]).Split(' ');
                for (int k = 0; k < cats.Length; k++)
                {
                    Assert.AreEqual(cats[k], I18n.Plural(locale, start + k), $"{where} {locale} n={start + k}");
                }
            }
            Points(c, tol, where, pt => I18n.Plural((string)pt[0], Json.ToNumber(pt[1])), 2);
        }

        private static List<string> Words(object list)
        {
            var words = new List<string>();
            foreach (object w in (List<object>)list)
            {
                words.Add((string)w);
            }
            return words;
        }

        // points = [inputs..., expected]: inputs are the first `inputs` items, the expected value is the next one
        private static void Points(Dictionary<string, object> c, double tol, string where,
                                   System.Func<List<object>, object> run, int inputs)
        {
            List<object> points = G.List(c, "points");
            Assert.IsNotEmpty(points, $"{where}: no points");
            foreach (object p in points)
            {
                var pt = (List<object>)p;
                Assert.AreEqual(inputs + 1, pt.Count, $"{where}: point {Json.Stringify(pt)} has an unexpected shape");
                G.AssertClose(run(pt), pt[inputs], tol, $"{where} {Json.Stringify(pt)}");
            }
        }
    }
}
