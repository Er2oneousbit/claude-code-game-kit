// ---------------------------------------------------------------------------
// AudioVectorTests.cs
// Purpose : Runs every case of data/golden/audio.json through the Core audio director (variant picks, pitch and
//           volume ranges, voice caps, cooldowns, ducking envelopes): one test per case.
// Usage   : python tools/dev.py test              (or --filter Audio)
// Notes   : The expected values come from the file at test time (tools/audio/audio_events.py vectors --write
//           writes it); never copy them in here. A case type without a runner fails, so a new vector type cannot
//           be skipped. A rejected play is compared as {result} alone, a played one with all eight fields
//           ("stolen" is null when nothing was stolen); a duck result as {target bus: dB}.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;
using G = {{GAME_SLUG}}.Tests.GoldenVectors;

namespace {{GAME_SLUG}}.Tests
{
    public class AudioVectorTests
    {
        private const string FILE = "audio.json";

        private static readonly string[] REQUIRED_TYPES = { "audio_director" };

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Audio");
        }

        [Test]
        public void Audio_EveryRequiredTypeHasCases()
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
        public void Audio(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            double tol = G.Tolerance(FILE);
            string type = G.Str(c, "type");
            switch (type)
            {
                case "audio_director": RunDirector(c, tol); break;
                default:
                    Assert.Fail($"unknown case type '{type}' in {FILE}: add a runner for it here");
                    break;
            }
        }

        // ---- Runners: scripted steps (call, inputs, expect) -----------------------------

        private static void RunDirector(Dictionary<string, object> c, double tol)
        {
            var director = new AudioDirector(G.Obj(c, "params"));
            Steps(c, (st, call, where) =>
            {
                if (call == "play")
                {
                    AudioPlayResult r = director.Play(G.Str(st, "event"), G.Num(st, "t_ms"));
                    G.AssertClose(PlayObject(r), G.Obj(st, "expect"), tol, where);
                }
                else if (call == "duck")
                {
                    G.AssertClose(director.Duck(G.Num(st, "t_ms")), G.Obj(st, "expect"), tol, where);
                }
                else
                {
                    return false;
                }
                return true;
            });
        }

        // The result in the vectors' shape: {result} for a rejected play, every field for a played one
        private static Dictionary<string, object> PlayObject(AudioPlayResult r)
        {
            if (!r.Played)
            {
                return G.Make("result", r.Result);
            }
            return G.Make("result", r.Result, "variant", r.Variant, "pitch_semitones", r.PitchSemitones,
                          "pitch_ratio", r.PitchRatio, "gain_db", r.GainDb, "voice", r.Voice,
                          "stolen", r.Stolen.HasValue ? (object)r.Stolen.Value : null, "ends_ms", r.EndsMs);
        }

        // Runs each step through run(step, call, where); run returns false for a call it does not know
        private static void Steps(Dictionary<string, object> c, System.Func<Dictionary<string, object>, string, string, bool> run)
        {
            List<object> steps = G.List(c, "steps");
            Assert.IsNotEmpty(steps, $"{G.Str(c, "name")}: no steps");
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                string call = G.Str(st, "call");
                string where = $"{G.Str(c, "name")} step {i} ({call})";
                if (!run(st, call, where))
                {
                    Assert.Fail($"{where}: unknown call '{call}' for a {G.Str(c, "type")} case");
                }
            }
        }
    }
}

// {{FOOTER}}
