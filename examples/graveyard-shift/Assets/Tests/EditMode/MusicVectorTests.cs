// ---------------------------------------------------------------------------
// MusicVectorTests.cs
// Purpose : Runs every case of data/golden/music.json through the Core music director: the beat grid in samples
//           and every scripted transition plan (quantize, loop wrap, fades, stingers, synced entries), exactly.
// Usage   : python tools/dev.py test              (or --filter Music)
// Notes   : The expected values come from the file at test time (tools/audio/wavesmith/music.py vectors --write
//           writes it); never copy them in here. A case type without a runner fails, so a new vector type cannot
//           be skipped. The file's tolerance is 0 and every value is a whole number of samples: inputs are read
//           as long (a sample count can pass 2^31), and a plan is compared field by field with "stinger" and
//           "stinger_at" null when the rule has no stinger. Each case prints how many values it checked.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections;
using System.Collections.Generic;
using NUnit.Framework;
using graveyard_shift.Core;
using G = graveyard_shift.Tests.GoldenVectors;

namespace graveyard_shift.Tests
{
    public class MusicVectorTests
    {
        private const string FILE = "music.json";

        private static readonly string[] REQUIRED_TYPES = { "music_grid", "music_plan" };

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Music");
        }

        [Test]
        public void Music_EveryRequiredTypeHasCases()
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

        [TestCaseSource(nameof(Cases))]
        public void Music(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            double tol = G.Tolerance(FILE);
            string type = G.Str(c, "type");
            int checkedValues;
            switch (type)
            {
                case "music_grid": checkedValues = RunGrid(c, tol); break;
                case "music_plan": checkedValues = RunPlan(c, tol); break;
                default:
                    Assert.Fail($"unknown case type '{type}' in {FILE}: add a runner for it here");
                    return;
            }
            Assert.Greater(checkedValues, 0, $"{G.Str(c, "name")}: nothing was checked");
            TestContext.WriteLine($"{FILE} case {index} ({type}, {G.Str(c, "name")}): {checkedValues} values checked");
        }

        // ---- Runners: each returns how many expected values it compared -------------------

        // {bpm, rate, k, sample}: one beat start per step
        private static int RunGrid(Dictionary<string, object> c, double tol)
        {
            int count = 0;
            List<object> steps = Steps(c);
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                long sample = MusicDirector.BeatSample(G.Num(st, "k"), G.Num(st, "bpm"), Whole(st, "rate"));
                G.AssertClose(sample, Whole(st, "sample"), tol, $"{G.Str(c, "name")} step {i}");
                count++;
            }
            return count;
        }

        // params = a music.json; {from, since, entry, to, now, expect}: one plan per step
        private static int RunPlan(Dictionary<string, object> c, double tol)
        {
            var director = new MusicDirector(G.Obj(c, "params"));
            int count = 0;
            List<object> steps = Steps(c);
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                string where = $"{G.Str(c, "name")} step {i} ({G.Str(st, "from")} -> {G.Str(st, "to")} at {Whole(st, "now")})";
                MusicPlan p = director.Plan(G.Str(st, "from"), Whole(st, "since"), Whole(st, "entry"),
                                            G.Str(st, "to"), Whole(st, "now"));
                Dictionary<string, object> expect = G.Obj(st, "expect");
                AssertWholeNumbers(expect, where);
                G.AssertClose(PlanObject(p), expect, tol, where);
                count += Leaves(expect);
            }
            return count;
        }

        // The plan in the vectors' shape (null stinger fields when the rule has none)
        private static Dictionary<string, object> PlanObject(MusicPlan p)
        {
            return G.Make("switch_at", p.SwitchAt, "from_stop_at", p.FromStopAt, "fade", p.Fade,
                          "to_offset", p.ToOffset, "to_start_at", p.ToStartAt, "stinger", p.Stinger,
                          "stinger_at", p.StingerAt.HasValue ? (object)p.StingerAt.Value : null);
        }

        // ---- Helpers ----------------------------------------------------------------------

        private static List<object> Steps(Dictionary<string, object> c)
        {
            List<object> steps = G.List(c, "steps");
            Assert.IsNotEmpty(steps, $"{G.Str(c, "name")}: no steps");
            return steps;
        }

        // A whole-number field as long (JSON numbers arrive as double, exact below 2^53)
        private static long Whole(Dictionary<string, object> obj, string key)
        {
            double v = G.Num(obj, key);
            Assert.AreEqual(System.Math.Floor(v), v, $"vector field '{key}' is not a whole number: {v}");
            return (long)v;
        }

        // Every number in an expected plan is a sample count: a fraction would mean the vectors changed shape
        private static void AssertWholeNumbers(Dictionary<string, object> expect, string where)
        {
            foreach (KeyValuePair<string, object> kv in expect)
            {
                if (Json.IsNumber(kv.Value))
                {
                    double v = Json.ToNumber(kv.Value);
                    Assert.AreEqual(System.Math.Floor(v), v, $"{where}: expected {kv.Key} is not a whole number");
                }
            }
        }

        // How many values a comparison covers (numbers, text, null, bools)
        private static int Leaves(object value)
        {
            if (value is IDictionary obj)
            {
                int n = 0;
                foreach (object v in obj.Values)
                {
                    n += Leaves(v);
                }
                return n;
            }
            if (value is IList list && !(value is string))
            {
                int n = 0;
                foreach (object v in list)
                {
                    n += Leaves(v);
                }
                return n;
            }
            return 1;
        }
    }
}
