// ---------------------------------------------------------------------------
// DialogueVectorTests.cs
// Purpose : Runs every case of data/golden/dialogue.json through Core/DialogueData: the typewriter reveal count at
//           each time, exactly as the reference (Wavesmith's dialogue.py).
// Usage   : python tools/dev.py test              (or --filter Dialogue)
// Notes   : The expected values come from the file at test time; never copy them in here. A case type without a
//           runner fails, so a new vector type cannot be skipped. Counts are integers: compared exactly.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using graveyard_shift.Core;
using G = graveyard_shift.Tests.GoldenVectors;

namespace graveyard_shift.Tests
{
    public class DialogueVectorTests
    {
        private const string FILE = "dialogue.json";

        private static readonly string[] REQUIRED_TYPES = { "reveal_count" };

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Dialogue");
        }

        [Test]
        public void Dialogue_EveryRequiredTypeHasCases()
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
        public void Dialogue(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            string type = G.Str(c, "type");
            int checkedValues;
            switch (type)
            {
                case "reveal_count": checkedValues = RunReveal(c); break;
                default:
                    Assert.Fail($"unknown case type '{type}' in {FILE}: add a runner for it here");
                    return;
            }
            Assert.Greater(checkedValues, 0, $"{G.Str(c, "name")}: nothing was checked");
            TestContext.WriteLine($"{FILE} case {index} ({type}, {G.Str(c, "name")}): {checkedValues} values checked");
        }

        // {line, t, expect, [length]}: how many characters are revealed at t
        private static int RunReveal(Dictionary<string, object> c)
        {
            List<object> steps = G.List(c, "steps");
            Assert.IsNotEmpty(steps, $"{G.Str(c, "name")}: no steps");
            int count = 0;
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                int length = st.ContainsKey("length") ? (int)G.Num(st, "length") : -1;
                int got = DialogueData.Revealed(G.Obj(st, "line"), G.Num(st, "t"), length);
                Assert.AreEqual((int)G.Num(st, "expect"), got, $"{G.Str(c, "name")} step {i} (t={G.Num(st, "t")}): "
                                + (st.TryGetValue("about", out object about) ? about as string : ""));
                count++;
            }
            return count;
        }
    }
}
