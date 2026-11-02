// ---------------------------------------------------------------------------
// AccessVectorTests.cs
// Purpose : Runs every case of data/golden/access.json through the Core audio accessibility rules: the slider gain
//           every bus gets (nested trees, cycles, bad slider values) and the direction and arrow every caption
//           point gets, exactly as the reference.
// Usage   : python tools/dev.py test              (or --filter Access)
// Notes   : The expected values come from the file at test time (tools/audio/wavesmith/access.py vectors --write
//           writes it); never copy them in here. A case type without a runner fails, so a new vector type cannot
//           be skipped. Gains compare within the file's tolerance as {bus: gain} key sets; a direction and its
//           arrow compare exactly. The file's "arrows" table must equal AudioAccess.ARROWS. Each case prints how
//           many values it checked.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using graveyard_shift.Core;
using G = graveyard_shift.Tests.GoldenVectors;

namespace graveyard_shift.Tests
{
    public class AccessVectorTests
    {
        private const string FILE = "access.json";

        private static readonly string[] REQUIRED_TYPES = { "access_gains", "access_arrow" };

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Access");
        }

        [Test]
        public void Access_EveryRequiredTypeHasCases()
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
        public void Access_ArrowTableMatchesTheFile()
        {
            List<object> arrows = G.List(G.Load(FILE), "arrows");
            G.AssertClose(new List<object>(AudioAccess.ARROWS), arrows, 0.0, $"{FILE} arrows");
        }

        [TestCaseSource(nameof(Cases))]
        public void Access(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            double tol = G.Tolerance(FILE);
            string type = G.Str(c, "type");
            int checkedValues;
            switch (type)
            {
                case "access_gains": checkedValues = RunGains(c, tol); break;
                case "access_arrow": checkedValues = RunArrows(c); break;
                default:
                    Assert.Fail($"unknown case type '{type}' in {FILE}: add a runner for it here");
                    return;
            }
            Assert.Greater(checkedValues, 0, $"{G.Str(c, "name")}: nothing was checked");
            TestContext.WriteLine($"{FILE} case {index} ({type}, {G.Str(c, "name")}): {checkedValues} values checked");
        }

        // ---- Runners: each returns how many expected values it compared -------------------

        // {buses, sliders, expect}: expect is {bus: linear gain}
        private static int RunGains(Dictionary<string, object> c, double tol)
        {
            int count = 0;
            List<object> steps = Steps(c);
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                Dictionary<string, double> got = AudioAccess.UserBusGains(G.Obj(st, "buses"), G.Obj(st, "sliders"));
                Dictionary<string, object> expect = G.Obj(st, "expect");
                G.AssertClose(got, expect, tol, $"{G.Str(c, "name")} step {i}");
                count += expect.Count;
            }
            return count;
        }

        // {dx, dy, half_w, half_h, dir, arrow}: dir is -1 on screen, arrow "" then
        private static int RunArrows(Dictionary<string, object> c)
        {
            int count = 0;
            List<object> steps = Steps(c);
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                double dx = G.Num(st, "dx"), dy = G.Num(st, "dy"), w = G.Num(st, "half_w"), h = G.Num(st, "half_h");
                var got = G.Make("dir", AudioAccess.CaptionDirection(dx, dy, w, h),
                                 "arrow", AudioAccess.CaptionArrow(dx, dy, w, h));
                var expect = G.Make("dir", G.Num(st, "dir"), "arrow", G.Str(st, "arrow"));
                G.AssertClose(got, expect, 0.0, $"{G.Str(c, "name")} step {i} ({dx}, {dy})");   // integers and text: exact
                count += 2;
            }
            return count;
        }

        private static List<object> Steps(Dictionary<string, object> c)
        {
            List<object> steps = G.List(c, "steps");
            Assert.IsNotEmpty(steps, $"{G.Str(c, "name")}: no steps");
            return steps;
        }
    }
}
