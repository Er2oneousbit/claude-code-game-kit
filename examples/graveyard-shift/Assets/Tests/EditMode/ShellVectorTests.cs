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
            "plural", "pseudo", "narration",
        };

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Shell");
        }

        [Test]
        public void Shell_EveryRequiredTypeHasCases()
        {
            var seen = new HashSet<string>();
            foreach (object c in G.Cases(FILE))
            {
                seen.Add(G.Str((Dictionary<string, object>)c, "type"));
            }
            foreach (string type in REQUIRED_TYPES)
            {
                Assert.IsTrue(seen.Contains(type), $"{FILE} has no '{type}' case");
            }
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

        private static void RunPlural(Dictionary<string, object> c, double tol, string where)
        {
            var tables = I18n.TablesFromJson(G.Get(c, "tables"));
            foreach (object p in G.List(c, "points"))
            {
                var pt = (List<object>)p;                  // [locale, n, plural form, tr_plural text]
                string locale = (string)pt[0];
                double n = Json.ToNumber(pt[1]);
                var actual = new List<object> { I18n.Plural(locale, n), I18n.TrPlural(tables, locale, "apples", n) };
                G.AssertClose(actual, pt.GetRange(2, 2), tol, $"{where} {Json.Stringify(pt)}");
            }
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
