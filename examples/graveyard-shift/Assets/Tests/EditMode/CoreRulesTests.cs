// ---------------------------------------------------------------------------
// CoreRulesTests.cs
// Purpose : EditMode tests for the engine-free rules: perception (the lantern decides how far ghosts
//           see), the ghost state machine (one test per transition), the night (souls, gate, caught,
//           dawn), the save migration, and the level data (hand-made and generated yards).
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): regression tests for a review's proven bugs (each named
//           after what it guards): no catch by a tired ghost, a catch grace, a search that ends, a broken .tmp save,
//           seams between areas, chest-high cover, ghost plans ranked by an exact key, ghost corners in open ground.
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using System.Linq;
using graveyard_shift.Core;
using NUnit.Framework;

namespace graveyard_shift.Tests
{
    // The tunables the game really uses: the setup asset, not `new GameTuning()`. Field defaults only seed a new
    // asset, so tests built on the code defaults can pass while the game plays different numbers.
    public static class TestTuning
    {
        public const string SetupPath = "Assets/Config/SO_GraveyardSetup.asset";

        public static GameTuning Load()
        {
            var setup = UnityEditor.AssetDatabase.LoadAssetAtPath<graveyard_shift.Game.GraveyardSetup>(SetupPath);
            Assert.IsNotNull(setup, $"{SetupPath} missing: run python tools/dev.py exec SceneBuilder.Build");
            return setup.tuning;
        }
    }

    public class PerceptionTests
    {
        private readonly GameTuning _t = TestTuning.Load();
        private static readonly V2 Ghost = new V2(0, 0);
        private static readonly V2 North = new V2(0, 1);

        [Test]
        public void Lantern_LitKeeperIsSeenFarAway_DarkOneIsNot()
        {
            var keeper = new V2(0, _t.SightLit - 1f);   // relative to the tuning, so a retune cannot make it stale
            Assert.Greater(keeper.Z, _t.SightDark);
            Assert.IsTrue(Perception.Sees(_t, Ghost, North, keeper, lit: true, lineOfSight: true));
            Assert.IsFalse(Perception.Sees(_t, Ghost, North, keeper, lit: false, lineOfSight: true));
        }

        [Test]
        public void Cone_BehindTheGhostOnlyTheShortSenseRadiusCounts()
        {
            Assert.IsFalse(Perception.Sees(_t, Ghost, North, new V2(0, -(_t.SenseLit + 1f)), true, true));
            Assert.IsTrue(Perception.Sees(_t, Ghost, North, new V2(0, -(_t.SenseLit - 0.5f)), true, true));
            Assert.IsFalse(Perception.Sees(_t, Ghost, North, new V2(0, -(_t.SenseLit - 0.5f)), false, true));
        }

        [Test]
        public void Cover_BlocksEverything()
        {
            Assert.IsFalse(Perception.Sees(_t, Ghost, North, new V2(0, 1), true, lineOfSight: false));
        }
    }

    public class GhostBrainTests
    {
        private readonly GameTuning _t = TestTuning.Load();
        private static readonly List<V2> Route = new List<V2> { new V2(0, 0), new V2(10, 0) };

        private static GhostOrder Run(GhostBrain b, float seconds, bool sees, V2 keeper, V2 ghost)
        {
            GhostOrder o = default;
            for (float t = 0; t < seconds; t += 0.02f) o = b.Tick(0.02f, sees, keeper, ghost, out _);
            return o;
        }

        [Test]
        public void Patrol_AdvancesToTheNextWaypointOnArrival()
        {
            var b = new GhostBrain(_t, Route);
            var o = b.Tick(0.02f, false, default, new V2(0, 0), out _);
            Assert.AreEqual(GhostState.Patrol, b.State);
            Assert.AreEqual(10f, o.Destination.X, 1e-4);
            Assert.AreEqual(_t.PatrolSpeed, o.Speed);
        }

        [Test]
        public void Patrol_SeeingTheKeeper_StopsSuspiciousFirst()
        {
            var b = new GhostBrain(_t, Route);
            var o = b.Tick(0.02f, true, new V2(3, 3), new V2(5, 0), out bool changed);
            Assert.IsTrue(changed);
            Assert.AreEqual(GhostState.Suspicious, b.State);
            Assert.AreEqual(0f, o.Speed);
            Assert.IsTrue(o.FaceKeeper);
        }

        [Test]
        public void Suspicious_StillSeen_Hunts_FastAtTheKeeper()
        {
            var b = new GhostBrain(_t, Route);
            var o = Run(b, _t.SuspiciousSeconds + 0.1f, true, new V2(3, 3), new V2(5, 0));
            Assert.AreEqual(GhostState.Hunt, b.State);
            Assert.AreEqual(_t.HuntSpeed, o.Speed);
            Assert.AreEqual(3f, o.Destination.X, 1e-4);
        }

        [Test]
        public void Suspicious_KeeperVanished_Searches()
        {
            var b = new GhostBrain(_t, Route);
            b.Tick(0.02f, true, new V2(3, 3), new V2(5, 0), out _);
            Run(b, _t.SuspiciousSeconds + 0.1f, false, new V2(3, 3), new V2(5, 0));
            Assert.AreEqual(GhostState.Search, b.State);
            Assert.AreEqual(3f, b.LastSeen.X, 1e-4);
        }

        [Test]
        public void Hunt_LosingSightLongEnough_Searches()
        {
            var b = new GhostBrain(_t, Route);
            Run(b, _t.SuspiciousSeconds + 0.1f, true, new V2(3, 3), new V2(5, 0));
            Run(b, _t.LoseSightSeconds * 0.5f, false, new V2(3, 3), new V2(5, 0));
            Assert.AreEqual(GhostState.Hunt, b.State, "a short break is not enough");
            Run(b, _t.LoseSightSeconds, false, new V2(3, 3), new V2(5, 0));
            Assert.AreEqual(GhostState.Search, b.State);
        }

        [Test]
        public void Hunt_GhostsTire_EvenWhileTheyStillSeeTheKeeper()
        {
            var b = new GhostBrain(_t, Route);
            Run(b, _t.SuspiciousSeconds + 0.1f, true, new V2(3, 3), new V2(5, 0));
            Assert.AreEqual(GhostState.Hunt, b.State);
            Run(b, _t.HuntMaxSeconds + 0.1f, true, new V2(3, 3), new V2(5, 0));
            Assert.AreEqual(GhostState.Return, b.State, "tired: back to the route");
            Assert.IsTrue(b.Tired);
            Run(b, _t.TiredSeconds * 0.5f, true, new V2(3, 3), new V2(5, 0));
            Assert.AreNotEqual(GhostState.Suspicious, b.State, "a tired ghost ignores the keeper");
            Run(b, _t.TiredSeconds, false, new V2(3, 3), new V2(5, 0));
            Assert.IsFalse(b.Tired);
        }

        [Test]
        public void Search_AtTheLastSeenSpot_GivesUpAndReturns_ThenPatrols()
        {
            var b = new GhostBrain(_t, Route);
            Run(b, _t.SuspiciousSeconds + 0.1f, true, new V2(3, 3), new V2(5, 0));
            Run(b, _t.LoseSightSeconds + 0.1f, false, new V2(3, 3), new V2(5, 0));
            Run(b, 5f, false, default, new V2(30, 30));            // far from the spot: the clock waits
            Assert.AreEqual(GhostState.Search, b.State);
            Run(b, _t.SearchSeconds + 0.1f, false, default, new V2(3, 3));
            Assert.AreEqual(GhostState.Return, b.State);
            b.Tick(0.02f, false, default, b.CurrentWaypoint, out _);
            Assert.AreEqual(GhostState.Patrol, b.State);
        }

        [Test]
        public void Search_SeeingTheKeeperAgain_IsSuspiciousAgain()
        {
            var b = new GhostBrain(_t, Route);
            b.Tick(0.02f, true, new V2(3, 3), new V2(5, 0), out _);
            Run(b, _t.SuspiciousSeconds + 0.1f, false, new V2(3, 3), new V2(5, 0));
            b.Tick(0.02f, true, new V2(4, 4), new V2(5, 0), out _);
            Assert.AreEqual(GhostState.Suspicious, b.State);
        }
    }

    // Review fixes (2026-10-26): a tired ghost caught like any other, and a search for a spot nobody can reach never ended
    public class GhostBrainReviewTests
    {
        private readonly GameTuning _t = TestTuning.Load();
        private static readonly List<V2> Route = new List<V2> { new V2(0, 0), new V2(10, 0) };

        [Test]
        public void Tired_NeverCatches()
        {
            var b = new GhostBrain(_t, Route);
            var at = new V2(5, 0);
            Assert.IsTrue(b.CanCatch(at, at + new V2(_t.CatchRadius * 0.5f, 0)), "a ghost at the keeper catches");
            Assert.IsFalse(b.CanCatch(at, at + new V2(_t.CatchRadius * 1.5f, 0)), "out of reach");
            b.Tire();
            Assert.IsTrue(b.Tired);
            Assert.IsFalse(b.CanCatch(at, at), "a tired ghost walks through the keeper");
        }

        [Test]
        public void Search_GivesUp_AfterSearchMaxSeconds_EvenFarFromTheSpot()
        {
            var b = new GhostBrain(_t, Route);
            for (float s = 0; s < _t.SuspiciousSeconds + 0.1f; s += 0.02f) b.Tick(0.02f, true, new V2(3, 3), new V2(5, 0), out _);
            for (float s = 0; s < _t.LoseSightSeconds + 0.1f; s += 0.02f) b.Tick(0.02f, false, new V2(3, 3), new V2(5, 0), out _);
            Assert.AreEqual(GhostState.Search, b.State);
            // The ghost never gets near the last seen spot (it is off the NavMesh): the old clock waited forever
            for (float s = 0; s < _t.SearchMaxSeconds - 0.5f; s += 0.02f) b.Tick(0.02f, false, default, new V2(30, 30), out _);
            Assert.AreEqual(GhostState.Search, b.State, "still searching before the limit");
            for (float s = 0; s < 0.6f; s += 0.02f) b.Tick(0.02f, false, default, new V2(30, 30), out _);
            Assert.AreEqual(GhostState.Return, b.State, "gave up");
        }
    }

    public class NightRulesTests
    {
        private readonly GameTuning _t = TestTuning.Load();
        private static readonly List<V2> Souls = new List<V2> { new V2(5, 0), new V2(10, 0) };
        private static readonly V2 Gate = new V2(0, -10);

        [Test]
        public void Clock_StartsOnTheFirstMove()
        {
            var n = new NightRules(_t, 2);
            n.Tick(1f, false, default, Souls, Gate, false);
            Assert.AreEqual(_t.NightSeconds, n.TimeLeft);
            CollectionAssert.Contains(n.Tick(1f, true, default, Souls, Gate, false), NightEvent.Started);
            Assert.Less(n.TimeLeft, _t.NightSeconds);
        }

        [Test]
        public void Gate_StaysShutUntilEverySoulIsCollected()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, Souls[0], Souls, Gate, false);
            Assert.AreEqual(1, n.Collected);
            n.Tick(0.1f, true, Gate, Souls, Gate, false);
            Assert.AreEqual(Outcome.Playing, n.Outcome, "one soul short");
            var ev = n.Tick(0.1f, true, Souls[1], Souls, Gate, false);
            CollectionAssert.Contains(ev, NightEvent.AllSouls);
            CollectionAssert.Contains(n.Tick(0.1f, true, Gate, Souls, Gate, false), NightEvent.Escaped);
            Assert.AreEqual(Outcome.Escaped, n.Outcome);
        }

        [Test]
        public void Caught_CostsTheLastSoul_NotTheNight()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, Souls[0], Souls, Gate, false);
            n.Tick(0.1f, true, Souls[1], Souls, Gate, false);
            Assert.AreEqual(2, n.Collected);
            CollectionAssert.Contains(n.Tick(0.1f, true, new V2(-5, -5), Souls, Gate, true), NightEvent.Caught);
            Assert.AreEqual(Outcome.Playing, n.Outcome);
            Assert.AreEqual(1, n.Collected);
            Assert.AreEqual(1, n.LastLostSoul, "the last one collected slips back");
            Assert.IsFalse(n.IsCollected(1));
            Assert.AreEqual(1, n.Catches);
            n.Tick(0.1f, true, Souls[1], Souls, Gate, false);
            Assert.AreEqual(2, n.Collected, "and can be collected again");
        }

        // Playtest: caught on the way out with every soul, the soul went back but the gate stayed open
        [Test]
        public void Caught_WithEverySoul_ShutsTheGate_UntilTheSoulIsBack()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, Souls[0], Souls, Gate, false);
            CollectionAssert.Contains(n.Tick(0.1f, true, Souls[1], Souls, Gate, false), NightEvent.AllSouls);
            var caught = n.Tick(0.1f, true, new V2(-5, -5), Souls, Gate, true);
            CollectionAssert.Contains(caught, NightEvent.GateShut);
            Assert.IsFalse(n.AllCollected);
            n.Tick(0.1f, true, Gate, Souls, Gate, false);
            Assert.AreEqual(Outcome.Playing, n.Outcome, "a shut gate lets nobody out");
            CollectionAssert.Contains(n.Tick(0.1f, true, Souls[1], Souls, Gate, false), NightEvent.AllSouls, "the gate opens again");
            CollectionAssert.DoesNotContain(n.Tick(0.1f, true, new V2(-5, -5), new List<V2>(), Gate, false), NightEvent.GateShut);
        }

        [Test]
        public void Caught_WithSomeSouls_DoesNotShutAnything()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, Souls[0], Souls, Gate, false);
            CollectionAssert.DoesNotContain(n.Tick(0.1f, true, new V2(-5, -5), Souls, Gate, true), NightEvent.GateShut);
        }

        // Kimi audit: the escape fired while the leaves were still swinging (and 3 m inside the wall)
        [Test]
        public void Escape_WaitsForTheGateToFinishOpening()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, Souls[0], Souls, Gate, false);
            n.Tick(0.1f, true, Souls[1], Souls, Gate, false);
            n.Tick(0.1f, true, Gate, Souls, Gate, false, gateOpen: false);
            Assert.AreEqual(Outcome.Playing, n.Outcome, "the leaves are still swinging");
            CollectionAssert.Contains(n.Tick(0.1f, true, Gate, Souls, Gate, false, gateOpen: true), NightEvent.Escaped);
        }

        [Test]
        public void Escape_NotFromTheStart()
        {
            // The start is 2 m inside the gate point on every yard (Level.Walled): that is not the doorway
            var l = Level.Graveyard();
            Assert.Greater(V2.Distance(l.KeeperStart, l.Gate), _t.GateRadius, "the start is outside the escape zone");
        }

        // Review fix (2026-10-26): a ghost near the start caught the respawned keeper every frame, 35 catches in a second
        [Test]
        public void Caught_ThenGrace_TouchesIgnoredForCatchGraceSeconds()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, Souls[0], Souls, Gate, false);
            n.Tick(0.1f, true, Souls[1], Souls, Gate, false);
            const float frame = 1f / 60f;
            n.Tick(frame, true, new V2(-5, -5), Souls, Gate, true);
            Assert.AreEqual(1, n.Catches);
            Assert.IsTrue(n.InGrace);
            // A ghost stays on the keeper for one second, every frame a touch
            for (int i = 0; i < 60; i++) n.Tick(frame, true, new V2(-5, -5), Souls, Gate, true);
            Assert.AreEqual(1, n.Catches, "one catch costs one soul, not one per frame");
            Assert.AreEqual(1, n.Collected);
            for (float s = 0; s < _t.CatchGraceSeconds; s += frame) n.Tick(frame, true, new V2(-5, -5), Souls, Gate, false);
            Assert.IsFalse(n.InGrace);
            n.Tick(frame, true, new V2(-5, -5), Souls, Gate, true);
            Assert.AreEqual(2, n.Catches, "after the grace a touch is a catch again");
        }

        [Test]
        public void Caught_WithNoSouls_StillCountsButLosesNothing()
        {
            var n = new NightRules(_t, 2);
            n.Tick(0.1f, true, new V2(-5, -5), Souls, Gate, true);
            Assert.AreEqual(-1, n.LastLostSoul);
            Assert.AreEqual(0, n.Collected);
        }

        [Test]
        public void Ending_NothingHappensAfterTheNightIsOver()
        {
            var n = new NightRules(_t, 1);
            var one = new List<V2> { Souls[0] };
            n.Tick(0.1f, true, Souls[0], one, Gate, false);
            n.Tick(0.1f, true, Gate, one, Gate, false);
            Assert.AreEqual(Outcome.Escaped, n.Outcome);
            Assert.IsEmpty(n.Tick(0.1f, true, Souls[0], one, Gate, true));
        }

        [Test]
        public void Dawn_EndsTheNight_WithOneLowTimeWarningBefore()
        {
            var n = new NightRules(_t, 2);
            var all = new List<NightEvent>();
            for (int i = 0; i < 2 * (int)_t.NightSeconds + 20; i++) all.AddRange(n.Tick(0.5f, true, new V2(-5, -5), Souls, Gate, false));
            Assert.AreEqual(Outcome.Dawn, n.Outcome);
            Assert.AreEqual(1, all.Count(e => e == NightEvent.LowTime));
            Assert.Less(all.IndexOf(NightEvent.LowTime), all.IndexOf(NightEvent.Dawn));
        }
    }

    // Kimi audit: Write deleted the old save before moving the new one in, so a crash between them lost it
    public class SaveStoreTests
    {
        private string _dir;

        [SetUp]
        public void MakeDir()
        {
            _dir = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "gs-save-" + System.Guid.NewGuid().ToString("N"));
            System.IO.Directory.CreateDirectory(_dir);
        }

        [TearDown]
        public void RemoveDir() => System.IO.Directory.Delete(_dir, true);

        [Test]
        public void Write_ReplacesTheOldSave_AndLeavesNoTemporaryFile()
        {
            var store = new graveyard_shift.Game.SaveStore(System.IO.Path.Combine(_dir, "save.json"));
            var save = new SaveV3 { nightsPlayed = 1 };
            store.Write(save);
            save.nightsPlayed = 2;
            store.Write(save);
            Assert.AreEqual(2, store.Load().nightsPlayed);
            Assert.IsFalse(System.IO.File.Exists(store.Path + ".tmp"));
        }

        [Test]
        public void Load_FindsASaveLeftOnlyAsTheTemporaryFile()
        {
            var store = new graveyard_shift.Game.SaveStore(System.IO.Path.Combine(_dir, "save.json"));
            store.Write(new SaveV3 { nightsPlayed = 7 });
            System.IO.File.Move(store.Path, store.Path + ".tmp");   // as if the first save crashed before its move
            Assert.AreEqual(7, store.Load().nightsPlayed);
        }

        // Review fix (2026-10-26): a crash during the very first save leaves an empty .tmp and no save.json. Load copied
        // the missing save.json to .bad and threw: the game started to a black window on every launch.
        [Test]
        public void Load_ABrokenTemporaryFileAndNoSave_StartsFresh_AndSetsTheTemporaryFileAside()
        {
            var store = new graveyard_shift.Game.SaveStore(System.IO.Path.Combine(_dir, "save.json"));
            System.IO.File.WriteAllText(store.Path + ".tmp", "");
            SaveV3 data = null;
            Assert.DoesNotThrow(() => data = store.Load());
            Assert.IsNotNull(data);
            Assert.AreEqual(0, data.nightsPlayed, "a fresh start");
            Assert.IsTrue(System.IO.File.Exists(store.Path + ".bad"), "the broken file is kept as .bad");
            Assert.IsFalse(System.IO.File.Exists(store.Path + ".tmp"), "and not read again on the next launch");
            Assert.DoesNotThrow(() => store.Write(new SaveV3 { nightsPlayed = 1 }));
            Assert.AreEqual(1, store.Load().nightsPlayed);
        }
    }

    public class SaveMigrationTests
    {
        [Test]
        public void V1_MigratesToV3_KeepingTheBestTime()
        {
            var v3 = SaveMigration.Upgrade(1, new SaveV1 { bestSeconds = 97.5f }, null, null);
            Assert.AreEqual(3, v3.version);
            Assert.AreEqual(97.5f, v3.bestEscapeSeconds);
            Assert.AreEqual(1, v3.escapes);
            Assert.IsNotNull(v3.settings);
            Assert.AreEqual("Normal", v3.settings.difficulty);
        }

        [Test]
        public void V1_WithoutATime_MigratesToAnEmptyRecord()
        {
            var v3 = SaveMigration.Upgrade(1, new SaveV1(), null, null);
            Assert.AreEqual(0, v3.escapes);
            Assert.AreEqual(0f, v3.bestEscapeSeconds);
        }

        [Test]
        public void V2_MigratesToV3_KeepingEverything_DifficultyNormal()
        {
            var old = new SaveV2 { nightsPlayed = 4, escapes = 2, bestEscapeSeconds = 80f };
            old.settings.volume = 0.3f;
            old.settings.showHints = false;
            var v3 = SaveMigration.Upgrade(2, null, old, null);
            Assert.AreEqual(3, v3.version);
            Assert.AreEqual(4, v3.nightsPlayed);
            Assert.AreEqual(2, v3.escapes);
            Assert.AreEqual(80f, v3.bestEscapeSeconds);
            Assert.AreEqual(0.3f, v3.settings.volume);
            Assert.IsFalse(v3.settings.showHints);
            Assert.AreEqual(Difficulty.Normal, DifficultySettings.Parse(v3.settings.difficulty));
        }

        [Test]
        public void V3_PassesThrough_AndAFutureVersionIsRefused()
        {
            var mine = new SaveV3 { nightsPlayed = 4 };
            Assert.AreSame(mine, SaveMigration.Upgrade(3, null, null, mine));
            Assert.Throws<System.NotSupportedException>(() => SaveMigration.Upgrade(4, null, null, null));
        }

        [Test]
        public void RecordEscape_KeepsTheFasterTime()
        {
            var s = new SaveV3();
            s.RecordEscape(120f);
            s.RecordEscape(130f);
            s.RecordEscape(90f);
            Assert.AreEqual(90f, s.bestEscapeSeconds);
            Assert.AreEqual(3, s.escapes);
        }
    }

    // The original level checks, now over the hand-made yard and the generated yards the scenario trio plays.
    // Footprints are the measured ones (Core/Footprint.cs); the first version guessed a radius per model.
    public class LevelTests
    {
        public static IEnumerable<int> Yards() => new[] { 0 }.Concat(Enumerable.Range(1, 8).Select(LevelGenerator.SeedForNight));

        [TestCaseSource(nameof(Yards))]
        public void SoulsStartAndGate_AreClearOfProps_AndInsideTheWalls(int seed)
        {
            var l = LevelGenerator.Generate(seed, TestTuning.Load());
            Assert.AreEqual(LevelCheck.SoulCount, l.Souls.Count);
            for (int i = 0; i < l.Souls.Count + 2; i++)
            {
                var p = i < l.Souls.Count ? l.Souls[i] : i == l.Souls.Count ? l.KeeperStart : l.Gate + LevelCheck.GateApproach;
                Assert.GreaterOrEqual(LevelCheck.Clearance(l, p), LevelCheck.SpotClearance, $"seed {seed}: spot {p} is crowded");
                Assert.IsTrue(l.Inside(p, LevelCheck.WallMargin), $"seed {seed}: spot {p} is not inside the walls");
            }
        }

        [TestCaseSource(nameof(Yards))]
        public void GhostRoutes_EveryPointCanBeReached(int seed)
        {
            var l = LevelGenerator.Generate(seed, TestTuning.Load());
            var grid = new WalkGrid(l);
            Assert.That(l.GhostRoutes.Count, Is.InRange(LevelCheck.MinRoutes, LevelCheck.MaxRoutes));
            for (int r = 0; r < l.GhostRoutes.Count; r++)
            foreach (var p in l.GhostRoutes[r])
            {
                Assert.IsTrue(grid.ReachableNear(p, GhostBrain.Arrive - 0.05f), $"seed {seed}: waypoint {p} cannot be reached");
            }
        }

        // Ghosts may start at any corner of their loop: none may start on top of the keeper (LevelCheck.GhostStartSafe)
        [TestCaseSource(nameof(Yards))]
        public void NoGhostRoutePointIsNearTheKeeperStart(int seed)
        {
            var l = LevelGenerator.Generate(seed, TestTuning.Load());
            foreach (var route in l.GhostRoutes)
            foreach (var p in route)
                Assert.GreaterOrEqual(V2.Distance(p, l.KeeperStart), LevelCheck.GhostStartSafe, $"seed {seed}: {p}");
        }
    }

    // Review fixes (2026-10-26) in the level data: seams, cover that hides, and which loops get the extra ghosts
    public class LevelReviewTests
    {
        // Areas were open on both sides, so a point on a seam between the main body and a wing was in neither: a soul
        // 1 m from an interior seam was "outside the walls" (Inside(p, margin) probes p +- margin)
        [Test]
        public void Inside_OneMeterFromAnInteriorSeam_IsInside()
        {
            var l = Level.Graveyard();   // main body x in [-32, 32]; east wing x in [32, 46], z in [-20, 10]
            var p = new V2(31f, 0f);
            Assert.IsTrue(l.Inside(p));
            Assert.IsTrue(l.Inside(new V2(32f, 0f)), "the seam itself belongs to the wing");
            Assert.IsTrue(l.Inside(p, LevelCheck.WallMargin), "1 m from an interior seam is not 'outside the walls'");
        }

        [Test]
        public void Area_IsHalfOpen_SoASeamIsInExactlyOneArea()
        {
            var west = new Area(-10f, 0f, -10f, 10f);
            var east = new Area(0f, 10f, -10f, 10f);
            var seam = new V2(0f, 3f);
            Assert.AreEqual(1, (west.Contains(seam) ? 1 : 0) + (east.Contains(seam) ? 1 : 0));
            Assert.IsTrue(west.Contains(new V2(-10f, 0f)), "the min edge is in");
            Assert.IsFalse(east.Contains(new V2(10f, 0f)), "the max edge is out");
        }

        // A ghost looks from 1.3 m at the keeper's chest (1.1 m): a prop lower than the chest never blocks that line,
        // yet crypt-a, crypt-b (1.04 m), gravestone-bevel (1.06), gravestone-broken (0.68) and rocks (0.75) counted
        // as the cover LevelCheck wants near every soul (180 souls over 250 nights had nothing that hid them)
        [Test]
        public void Cover_IsOnlyWhatReachesTheKeepersChest()
        {
            foreach (string low in new[] { "crypt-a", "crypt-b", "gravestone-bevel", "gravestone-broken", "rocks" })
                Assert.IsFalse(Footprint.IsCover(low), $"{low} is too low to hide anyone");
            foreach (string tall in new[] { "crypt", "crypt-large", "crypt-small", "gravestone-cross", "gravestone-round", "gravestone-wide", "pine", "pine-crooked", "rocks-tall" })
                Assert.IsTrue(Footprint.IsCover(tall), $"{tall} hides a keeper pressed against it");
            Assert.IsFalse(Footprint.IsCover("stone-wall"));
            Assert.IsFalse(Footprint.IsCover("lightpost-single"));
            foreach (string model in Footprint.Models)
                if (Footprint.IsCover(model)) Assert.GreaterOrEqual(Footprint.Height(model), Footprint.ChestHeight, model);
        }

        // Every soul of the hand-made yard and the first generated nights has chest-high cover within reach
        [Test]
        public void EverySoul_HasCoverThatHidesWithinReach()
        {
            var t = TestTuning.Load();
            foreach (int seed in LevelTests.Yards())
            {
                var l = LevelGenerator.Generate(seed, t);
                for (int i = 0; i < l.Souls.Count; i++)
                    Assert.LessOrEqual(LevelCheck.CoverDistance(l, l.Souls[i]), LevelCheck.CoverReach, $"seed {seed} soul {i}");
            }
        }

        // Smoke_E found a generated ghost corner in a sliver between three props: the walk grid kept it, the NavMesh bake
        // closed it, and the ghost could never arrive (night 3, seed 55875). Corners now snap to open ground only.
        [Test]
        public void GeneratedGhostCorners_StandInOpenGround()
        {
            var t = TestTuning.Load();
            foreach (int seed in LevelTests.Yards().Where(s => s != 0))
            {
                var l = LevelGenerator.Generate(seed, t);
                var grid = new WalkGrid(l);
                foreach (var route in l.GhostRoutes)
                    foreach (var p in route)
                        Assert.IsTrue(grid.ReachableAround(p, LevelGenerator.CornerOpen), $"seed {seed}: corner {p} is in a sliver");
            }
        }

        // The extra ghosts go to the longest loops. The order came from a float sum, so two loops of (nearly) equal
        // length could swap between runtimes; now it is whole 1/16 m steps, then the loop's index
        [Test]
        public void GhostPlan_RanksLoopsByAnExactKey_TiesByIndex()
        {
            var l = Level.Walled(new[] { new Area(-40f, 40f, -30f, 30f) });
            List<V2> Square(float x, float z, float side) =>
                new List<V2> { new V2(x, z), new V2(x + side, z), new V2(x + side, z + side), new V2(x, z + side) };
            l.GhostRoutes.Add(Square(-30.1f, 0.3f, 10f));   // 40 m, its corners off the lattice
            l.GhostRoutes.Add(Square(10f, 0f, 10f));        // 40 m exactly
            l.GhostRoutes.Add(Square(-20f, -20f, 10.0625f)); // one lattice step per side longer: first
            Assert.AreEqual(GhostPlan.LengthKey(l.GhostRoutes[0]), GhostPlan.LengthKey(l.GhostRoutes[1]), "equal in whole steps");
            var extras = GhostPlan.For(l, 1, 3).Where(s => s.Extra).Select(s => s.Loop).ToList();
            CollectionAssert.AreEqual(new[] { 2, 0, 1 }, extras, "longest first, then by index");
        }
    }
}
