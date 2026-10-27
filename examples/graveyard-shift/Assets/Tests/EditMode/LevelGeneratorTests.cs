// ---------------------------------------------------------------------------
// LevelGeneratorTests.cs
// Purpose : EditMode tests for the generated nights (SOP-17): every invariant over hundreds of seeds, one
//           seed one yard, seed 0 the hand-made yard, pinned yards that only change on purpose, and the
//           measured footprints compared with the real meshes.
// Usage   : python tools/dev.py test   (the property test logs "[INFO][test] property: ..." to Logs/dev_unity.log)
// Notes   : The property seeds are the nights players get (LevelGenerator.SeedForNight), not 1..N, so the
//           yards tested are the yards played. A seed that ever fails goes into RegressionSeeds for good.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): the property test checks the raw attempts (its "0 problems"
//           could not fail: Generate only returns yards that pass); pins re-made for chest-high cover and half-open
//           areas and open ghost corners, and they now hold the Normal ghost plan too; measured heights checked
//           against the meshes.
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using graveyard_shift.Core;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace graveyard_shift.Tests
{
    public static class YardPrint
    {
        // FNV-1a over everything the yard is made of: equal prints, equal yards (exact float bits). Models, the
        // outline, the gate and the start too (Kimi audit: a model swap at the same spot kept the old print).
        // plan (optional): the ghosts' starts and directions (GhostPlan), mixed in after the yard
        public static string Of(Level l, IEnumerable<GhostSpawn> plan = null)
        {
            uint h = 2166136261;
            void Mix(uint v)
            {
                unchecked { h = (h ^ v) * 16777619; }
            }
            void Add(float f) => Mix((uint)BitConverter.SingleToInt32Bits(f));
            foreach (var a in l.Areas) { Add(a.MinX); Add(a.MaxX); Add(a.MinZ); Add(a.MaxZ); }
            Add(l.Gate.X); Add(l.Gate.Z); Add(l.KeeperStart.X); Add(l.KeeperStart.Z);
            foreach (var p in l.Props)
            {
                foreach (char c in p.Model) Mix(c);
                Add(p.Position.X); Add(p.Position.Z); Add(p.Yaw);
            }
            foreach (var s in l.Souls) { Add(s.X); Add(s.Z); }
            foreach (var r in l.GhostRoutes) foreach (var w in r) { Add(w.X); Add(w.Z); }
            if (plan != null)
                foreach (var s in plan) { Mix((uint)s.Loop); Mix(s.Reversed ? 1u : 0u); Mix((uint)s.Start); Mix(s.Extra ? 1u : 0u); }
            return h.ToString("x8");
        }
    }

    public class LevelGeneratorTests
    {
        private const int PropertyNights = 250;

        // Seeds that once broke a rule. Empty so far: no generated yard has failed a check (HOW_IT_WAS_MADE).
        private static readonly int[] RegressionSeeds = { };

        // What a rejected attempt may give as its reason: "room" (a piece found no place) or an invariant's name
        private static readonly HashSet<string> Invariants = new HashSet<string>
            { "room", "models", "souls", "reach", "inside", "clear", "spread", "cover", "routes", "overlap" };

        [Test, Timeout(900000)]   // about a second a yard in the editor: the yards are big
        public void Property_EveryInvariantHolds_OnEveryNight()
        {
            var t = TestTuning.Load();
            // Generate only returns a yard that passed LevelCheck, so "the yard has no problems" alone cannot fail (review,
            // 2026-10-26). What can: every attempt is either the yard returned or a reject with a real reason, and the
            // bookkeeping adds up (attempts = rejects + 1).
            var problems = new List<string>();
            var rejects = new List<string>();
            int fallbacks = 0, maxAttempts = 0;
            var seen = new HashSet<string>();
            var clock = Stopwatch.StartNew();
            var seeds = Enumerable.Range(1, PropertyNights).Select(LevelGenerator.SeedForNight).Concat(RegressionSeeds).ToList();
            foreach (int seed in seeds)
            {
                int before = rejects.Count;
                var l = LevelGenerator.Generate(seed, t, rejects);
                if (l.Fallback) fallbacks++;
                maxAttempts = Math.Max(maxAttempts, l.Attempts);
                seen.Add(YardPrint.Of(l));
                if (!l.Fallback && rejects.Count - before != l.Attempts - 1)
                    problems.Add($"seed {seed}: {l.Attempts} attempts but {rejects.Count - before} rejects");
                foreach (string r in rejects.Skip(before))
                    if (!Invariants.Contains(r.Split(':')[0])) problems.Add($"seed {seed}: a reject names no invariant: {r}");
                problems.AddRange(LevelCheck.Problems(l, t).Select(p => $"seed {seed}: {p}"));
            }
            double ms = clock.Elapsed.TotalMilliseconds / seeds.Count;
            string tally = string.Join(", ", rejects.GroupBy(r => r.Split(':')[0]).OrderByDescending(g => g.Count()).Select(g => $"{g.Key} {g.Count()}"));
            UnityEngine.Debug.Log($"[INFO][test] property: {seeds.Count} generated yards checked, {seen.Count} different, " +
                                  $"{problems.Count} problems, {fallbacks} fallbacks, {rejects.Count} rejected attempts ({tally}), " +
                                  $"max attempts {maxAttempts}, {ms:0.0} ms per yard");
            Assert.IsEmpty(problems, string.Join("\n", problems.Take(20)));
            Assert.AreEqual(0, fallbacks, "a night fell back to the hand-made yard");
            Assert.AreEqual(seeds.Count, seen.Count, "two nights made the same yard");
        }

        // Kimi audit: an extra ghost started exactly on a base ghost's corner (the hand-made yard, Normal and up)
        [Test]
        public void Ghosts_NeverShareAStart_AtAnyDifficulty()
        {
            var t = TestTuning.Load();
            var yards = new List<(string, Level, int)> { ("hand-made", Level.Graveyard(), 0) };
            foreach (int night in Enumerable.Range(1, 8))
            {
                int seed = LevelGenerator.SeedForNight(night);
                yards.Add(($"night {night}", LevelGenerator.Generate(seed, t), seed));
            }
            foreach (var (name, l, seed) in yards)
            {
                foreach (Difficulty d in Enum.GetValues(typeof(Difficulty)))
                {
                    int extras = DifficultySettings.For(d).ExtraGhosts;
                    var plan = GhostPlan.For(l, seed, extras);
                    Assert.AreEqual(l.GhostRoutes.Count + extras, plan.Count, $"{name} {d}: ghost count");
                    var starts = plan.Select(s => s.StartPoint(l)).ToList();
                    for (int i = 0; i < starts.Count; i++)
                        for (int j = i + 1; j < starts.Count; j++)
                            Assert.Greater(V2.Distance(starts[i], starts[j]), 1f, $"{name} {d}: ghosts {i} and {j} start at {starts[i]}");
                    // The base ghosts start where they always did (the tuned balance depends on it)
                    for (int i = 0; i < l.GhostRoutes.Count; i++)
                        Assert.AreEqual((i + seed) % l.GhostRoutes[i].Count, plan[i].Start, $"{name}: base ghost {i}");
                }
            }
        }

        [Test]
        public void SameSeed_SameYard()
        {
            foreach (int seed in new[] { 1, 7, 6258, 99999 })
                Assert.AreEqual(YardPrint.Of(LevelGenerator.Generate(seed)), YardPrint.Of(LevelGenerator.Generate(seed)), $"seed {seed}");
        }

        // Changing the generator changes every saved and shared seed. These prints were made outside Unity
        // (.NET 8) and must match here (Mono): a change is fine when it is on purpose, so update them then.
        // The first prints did not match: float rounding differed between the runtimes (HOW_IT_WAS_MADE).
        // Re-made 2026-10-26 (review fixes), on purpose: cover must reach the keeper's chest (five low models stopped
        // counting, so soul spots moved: all four seeds), areas are half-open (seams count as inside: seeds 1 to 3), and
        // ghost loop corners snap only to open ground (LevelGenerator.CornerOpen: every loop moved a little). The print
        // also holds the Normal ghost plan now, so a change in which loops get the extra ghosts shows here too.
        // Before: 26eedc5c, 143b3ed6, 9376859e, 65c962a2 (yard only).
        [TestCase(1, "5e3bc1a0")]
        [TestCase(2, "8460fb45")]
        [TestCase(3, "55396cb4")]
        [TestCase(42, "1767dce6")]
        public void PinnedYards_OnlyChangeOnPurpose(int seed, string print)
        {
            var l = LevelGenerator.Generate(seed);
            Assert.AreEqual(print, YardPrint.Of(l, GhostPlan.For(l, seed, DifficultySettings.For(Difficulty.Normal).ExtraGhosts)));
        }

        [Test]
        public void SeedZero_IsTheHandMadeYard()
        {
            var made = LevelGenerator.Generate(0);
            Assert.AreEqual(YardPrint.Of(Level.Graveyard()), YardPrint.Of(made));
            Assert.IsTrue(made.HandMade);
            Assert.AreEqual(0, LevelGenerator.SeedForNight(0), "the first night is the hand-made yard");
        }

        [Test]
        public void EveryLaterNight_GetsItsOwnSeed()
        {
            var seeds = Enumerable.Range(1, 100).Select(LevelGenerator.SeedForNight).ToList();
            Assert.IsTrue(seeds.All(s => s >= 1 && s <= LevelGenerator.MaxSeed));
            Assert.AreEqual(seeds.Count, seeds.Distinct().Count());
        }

        // The hand-made yard came before the checks. These are what they found in it, kept as built: trees planted
        // in a gravestone row and against the wall, a soul close to a turned pine (which the walk grid also calls out of
        // reach, though the NavMesh and the bots reach it), a ghost corner inside a pine's box.
        [Test]
        public void HandMadeYard_PassesEveryCheck()
        {
            // The first, small hand-made yard came before the checks and had 8 known problems; this one was laid
            // out with them (2026-10-23) and has none
            CollectionAssert.IsEmpty(LevelCheck.Problems(Level.Graveyard(), TestTuning.Load()));
        }

        // Every check must be able to fail: feed each one a broken yard and expect its own message. (A check whose
        // line had been swallowed by a comment passed every other test, because good yards never trip it; and a
        // Kimi audit found eight checks no case reached, hidden by matching only the "routes:" or "reach:" prefix.)
        [TestCase("souls", "souls:")]
        [TestCase("inside", "is outside the walls")]
        [TestCase("clear", "clear: soul 0")]
        [TestCase("reach", "soul 0")]
        [TestCase("reach-start", "start")]
        [TestCase("reach-gate", "the gate cannot be reached")]
        [TestCase("spread", "from the start")]
        [TestCase("spacing", "souls 0 and 1 are")]
        [TestCase("cover", "has no cover")]
        [TestCase("routes", "is next to the start")]
        [TestCase("routes-count", "not 6 to 12")]
        [TestCase("routes-short", "points, not a loop")]
        [TestCase("routes-unreachable", "cannot be reached")]
        [TestCase("routes-loop", "loop is")]
        [TestCase("overlap", "overlap:")]
        [TestCase("models", "no measured footprint")]
        public void EveryInvariant_CatchesABrokenYard(string invariant, string message)
        {
            var t = TestTuning.Load();
            var l = LevelGenerator.Generate(1, t);
            Assert.IsEmpty(LevelCheck.Problems(l, t), "the unbroken yard must pass");
            int crypt = l.Props.FindIndex(p => p.Model == "crypt-large");
            switch (invariant)
            {
                case "souls": l.Souls.RemoveAt(5); break;
                case "inside": l.Souls[0] = new V2(l.Bounds.MaxX + 5f, l.Areas[0].MinZ + 5f); break;
                case "clear":
                case "reach": l.Souls[0] = l.Props[crypt].Position; break;   // inside the big crypt
                case "reach-start": l.KeeperStart = l.Props[crypt].Position; break;
                case "reach-gate": l.Gate = l.Props[crypt].Position; break;
                case "spread": l.Souls[0] = l.KeeperStart + new V2(0f, 2f); break;
                case "spacing": l.Souls[0] = l.Souls[1] + new V2(0f, 1f); break;
                case "cover": l.Props.RemoveRange(l.FixedProps, l.Props.Count - l.FixedProps); break;   // nothing to hide behind
                case "routes": l.GhostRoutes[1][0] = l.KeeperStart + new V2(0f, 1f); break;
                case "routes-count": l.GhostRoutes.RemoveRange(0, l.GhostRoutes.Count - (LevelCheck.MinRoutes - 1)); break;
                case "routes-short": l.GhostRoutes[1].RemoveRange(2, l.GhostRoutes[1].Count - 2); break;
                case "routes-unreachable": l.GhostRoutes[1][0] = l.Props[crypt].Position; break;
                case "routes-loop":
                    var p0 = l.GhostRoutes[1][0];
                    l.GhostRoutes[1] = new List<V2> { p0, p0 + new V2(1f, 0f), p0 + new V2(0f, 1f) };
                    break;
                case "overlap": l.Props.Add(l.Props[crypt]); break;
                case "models": l.Props.Add(new Prop { Model = "no-such-model", Position = new V2(0f, 0f) }); break;
            }
            var found = LevelCheck.Problems(l, t);
            string prefix = invariant.Split('-')[0] == "spacing" ? "spread" : invariant.Split('-')[0];
            Assert.That(found.Any(p => p.StartsWith(prefix + ":") && p.Contains(message)),
                $"{invariant} not caught (wanted \"{prefix}: ...{message}...\"); found: {string.Join("; ", found)}");
        }

        // Footprint.cs holds sizes measured once; the meshes are the truth. Turned props included, because a
        // turned mesh's bounds are the box around its turned box (what LevelBuilder's blocker uses). A footprint
        // must hold the mesh and be at most one lattice step (1/16 m) bigger on each side.
        [Test]
        public void Footprints_MatchTheMeshes()
        {
            var setup = AssetDatabase.LoadAssetAtPath<graveyard_shift.Game.GraveyardSetup>(TestTuning.SetupPath);
            Assert.IsNotNull(setup);
            int checkedCount = 0;
            foreach (string model in Footprint.Models)
            {
                var prefab = setup.Find(model);
                Assert.IsNotNull(prefab, $"{model} is not in the setup asset");
                // Crypts with a roof and door only ever stand square to the wall (0, 90, 180, 270): the box around a
                // turned building is bigger than its pieces' boxes put together
                var yaws = Footprint.Parts(model).Length > 0 ? new[] { 0f, 90f, 180f, 270f } : new[] { 0f, 15f, 30f, 45f, 60f, 75f, 90f };
                foreach (float yaw in yaws)
                {
                    // As the game builds it (crypts with their roof and door)
                    var go = graveyard_shift.Game.LevelBuilder.SpawnProp(setup, new Prop { Model = model, Yaw = yaw }, null);
                    var rs = go.GetComponentsInChildren<Renderer>();
                    Bounds b = rs[0].bounds;
                    foreach (var r in rs) b.Encapsulate(r.bounds);
                    UnityEngine.Object.DestroyImmediate(go);
                    var f = Footprint.Of(new Prop { Model = model, Position = new V2(0f, 0f), Yaw = yaw });
                    string at = $"{model} at {yaw} degrees: mesh {b.min.x:0.00}..{b.max.x:0.00}, {b.min.z:0.00}..{b.max.z:0.00}, footprint {f}";
                    const float slack = 1f / Footprint.Lattice + 0.01f, inside = 0.01f;
                    Assert.That(f.MinX <= b.min.x + inside && f.MinX >= b.min.x - slack, at);
                    Assert.That(f.MaxX >= b.max.x - inside && f.MaxX <= b.max.x + slack, at);
                    Assert.That(f.MinZ <= b.min.z + inside && f.MinZ >= b.min.z - slack, at);
                    Assert.That(f.MaxZ >= b.max.z - inside && f.MaxZ <= b.max.z + slack, at);
                    checkedCount++;
                }
            }
            UnityEngine.Debug.Log($"[INFO][test] footprints: {checkedCount} model and yaw pairs match the meshes");
        }

        // Footprint.Height decides what is cover (it must reach the keeper's chest): the meshes are the truth here too
        [Test]
        public void Heights_MatchTheMeshes()
        {
            var setup = AssetDatabase.LoadAssetAtPath<graveyard_shift.Game.GraveyardSetup>(TestTuning.SetupPath);
            Assert.IsNotNull(setup);
            var lines = new List<string>();
            foreach (string model in Footprint.Models)
            {
                var go = graveyard_shift.Game.LevelBuilder.SpawnProp(setup, new Prop { Model = model }, null);
                var rs = go.GetComponentsInChildren<Renderer>();
                Bounds b = rs[0].bounds;
                foreach (var r in rs) b.Encapsulate(r.bounds);
                UnityEngine.Object.DestroyImmediate(go);
                lines.Add($"{model} {b.max.y:0.00}");
                Assert.AreEqual(Footprint.Height(model), b.max.y, 0.01f, $"{model}: the mesh's top");
            }
            UnityEngine.Debug.Log("[INFO][test] heights: " + string.Join(", ", lines));
        }
    }
}
