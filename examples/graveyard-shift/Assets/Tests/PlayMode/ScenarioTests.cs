// ---------------------------------------------------------------------------
// ScenarioTests.cs
// Purpose : The scenario trio as PlayMode tests (SOP-14 step 6), on the real scene, NavMesh and physics:
//           a careful keeper (lights the lantern only while no ghost is near), an always-lit one and an
//           always-dark one share one movement brain, so the lantern is the only difference. They play twice:
//           8 nights on the hand-made yard (A to D, the baseline) and the first 8 generated nights a player
//           gets (F to I, SOP-17). Each comparison test: light used well must beat light always and never lose
//           to darkness, and the always-lit keeper must be caught far more (pillar 1). The trio plays at Easy (the
//           loops' ghosts, no extras): the bots see in meters, not pixels, so the darkness that Normal and up add costs
//           them nothing, while their extra ghosts cost the lantern-user most. Smoke_N logs the careful and dark bots at
//           Normal without judging them (the user's call, 2026-10-23, after a Kimi audit fix moved the extras apart).
//           Smoke_E checks the generator's walk grid against the real NavMesh; Smoke_J shows a yard from above.
// Usage   : python tools/dev.py smoke                                      (all Smoke tests, headless)
//           GRAVEYARD_SEEDS=6 python tools/dev.py smoke --filter Smoke_C --record Logs/frames   (a GIF)
//           GRAVEYARD_SEEDS=6258 python tools/dev.py smoke --filter Smoke_J --screenshot Logs/yard.png
// Notes   : Time.captureFramerate fixes every frame at 1/60 s of game time, so a night runs as fast as the
//           machine allows and replays exactly. Assert a gap over seeds, not one outcome (SOP-14).
//           Saves go to a temp file, never yours. GRAVEYARD_TRACE=1 logs the bot every half second;
//           GRAVEYARD_SEEDS=0 limits a run to those seeds (for captures; generated tests take them as night seeds).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): Smoke_K also pushes through the gate as a catch shuts it (the
//           leaves used to swing for 1.6 s while a lit keeper ran out and was locked outside).
// ---------------------------------------------------------------------------
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using graveyard_shift.Core;
using graveyard_shift.Game;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.AI;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace graveyard_shift.Tests
{
    public class ScenarioTests
    {
        private const string Scene = "Graveyard";
        private const int Fps = 60;
        private const int MaxFrames = Fps * 400;     // longer than a night (300 s): a stuck bot fails, never hangs
        private const int EndFrames = Fps;           // keep rendering a second after the end (for captures)
        private static readonly int[] AllSeeds = { 0, 1, 2, 3, 4, 5, 6, 7 };             // hand-made yard: ghost starts only
        private static readonly int[] NightSeeds = Enumerable.Range(1, 8).Select(LevelGenerator.SeedForNight).ToArray();
        private const int NavMeshNights = 8;    // generated yards whose walk grid is checked against the NavMesh
        private static readonly bool Trace = System.Environment.GetEnvironmentVariable("GRAVEYARD_TRACE") == "1";

        // One night's result. Progress = souls collected, and an escape counts as a full set plus one.
        private struct Result
        {
            public Outcome Outcome;
            public int Souls;
            public int Catches;
            public int Progress => Outcome == Outcome.Escaped ? Souls + 1 : Souls;   // an escape: every soul, plus one
        }

        // Results per yard kind ("hand-made", "generated") and bot
        private static readonly Dictionary<string, List<Result>> Results = new Dictionary<string, List<Result>>();

        private static string Only => System.Environment.GetEnvironmentVariable("GRAVEYARD_SEEDS");

        private static int[] Seeds(bool generated)
        {
            if (!string.IsNullOrEmpty(Only)) return Only.Split(',').Select(int.Parse).ToArray();
            return generated ? NightSeeds : AllSeeds;
        }

        private static string Key(bool generated, BotMode mode, Core.Difficulty difficulty = Core.Difficulty.Easy) =>
            $"{(generated ? "generated" : "hand-made")}/{mode}" + (difficulty == Core.Difficulty.Easy ? "" : $" at {difficulty}");

        private static string SavePath => Path.Combine(Application.temporaryCachePath, "scenario_save.json");

        private IEnumerator Night(BotMode mode, int seed, bool generated, Core.Difficulty difficulty)
        {
            GraveyardGame.Options = new LaunchOptions
            {
                Bot = mode,
                Seed = seed,
                HandMadeYard = !generated,
                Difficulty = difficulty,
                SavePath = SavePath,
            };
            Time.captureFramerate = Fps;
            yield return SceneManager.LoadSceneAsync(Scene);
            GameKitCapture.Attach();
            int frames = 0;
            while (GraveyardGame.Current == null || GraveyardGame.Current.Night == null ||
                   GraveyardGame.Current.Outcome == Outcome.Playing)
            {
                if (++frames > MaxFrames) break;
                if (Trace && frames % (Fps / 2) == 0 && GraveyardGame.Current?.Keeper != null)
                {
                    var g = GraveyardGame.Current;
                    var near = g.Ghosts.OrderBy(gh => V2.Distance(gh.Ground, g.Keeper.Ground)).First();
                    Debug.Log($"[INFO][trace] t={g.Night.Elapsed:0.0} pos={g.Keeper.Ground} souls={g.Night.Collected} {g.Bot.Reason} | " +
                              $"ghost{near.Id} {near.Brain.State} d={V2.Distance(near.Ground, g.Keeper.Ground):0.0} sees={near.SeesKeeper}");
                }
                yield return null;
            }
            for (int i = 0; i < EndFrames; i++) yield return null;
            GameKitCapture.Finish();
            var game = GraveyardGame.Current;
            // A night that hit the frame cap is a stuck bot, not a result (Kimi audit: it counted as a 0-soul night, which
            // even helped the lit-loses comparison pass)
            Assert.AreNotEqual(Outcome.Playing, game.Outcome, $"{mode} seed {seed}: the night never ended in {MaxFrames} frames");
            // An escape means the gate had finished opening (the last soul opens it)
            if (game.Outcome == Outcome.Escaped) Assert.IsTrue(Object.FindFirstObjectByType<GateSwing>().IsOpen, "escaped through a gate still opening");
            Results[Key(generated, mode, difficulty)].Add(new Result { Outcome = game.Outcome, Souls = game.Night.Collected, Catches = game.Night.Catches });
            Debug.Log($"[INFO][test] {(generated ? "generated" : "hand-made")} {mode} seed {seed}: {game.Outcome} after {game.Night.Elapsed:0.0}s, " +
                      $"souls {game.Night.Collected}/{game.Night.SoulCount}, caught {game.Night.Catches}x; {game.Bot.Stats()}");
        }

        private IEnumerator Nights(BotMode mode, bool generated, Core.Difficulty difficulty = Core.Difficulty.Easy)
        {
            string key = Key(generated, mode, difficulty);
            Results[key] = new List<Result>();
            foreach (int seed in Seeds(generated)) yield return Night(mode, seed, generated, difficulty);
            Debug.Log($"[INFO][test] {key} total: progress {Progress(key)}, escapes {Escapes(key)}/{Results[key].Count}, catches {Catches(key)}");
        }

        private static int Progress(string k) => Results[k].Sum(r => r.Progress);
        private static int Catches(string k) => Results[k].Sum(r => r.Catches);
        private static int Escapes(string k) => Results[k].Count(r => r.Outcome == Outcome.Escaped);
        private static bool Partial => !string.IsNullOrEmpty(Only);  // a capture run: report, do not judge

        // Pillar 1 on one kind of yard. minGap: how far careful must beat always-lit (progress over 8 nights).
        // litCaughtMost: also assert the always-lit keeper is caught far more than the others (true on the hand-made
        // yard; on generated nights it fails by stalling instead, so there it is logged, not asserted).
        // darkAsserted: careful must not lose to always-dark. The bots see ghosts in the dark, so this is the comparison
        // they are blind to: asserted on the hand-made yard, logged on generated nights (the user's call, 2026-10-23).
        private static void TheLanternIsAChoice(bool generated, int minGap, bool litCaughtMost, bool darkAsserted)
        {
            string lk = Key(generated, BotMode.AlwaysLit), dk = Key(generated, BotMode.AlwaysDark), ck = Key(generated, BotMode.Careful);
            if (Partial || !Results.ContainsKey(lk) || !Results.ContainsKey(dk) || !Results.ContainsKey(ck))
                Assert.Ignore("needs all three bots over all seeds");
            int lit = Progress(lk), dark = Progress(dk), careful = Progress(ck);
            string totals = $"{(generated ? "generated" : "hand-made")}: progress lit {lit}, dark {dark}, careful {careful}; " +
                            $"escapes lit {Escapes(lk)}, dark {Escapes(dk)}, careful {Escapes(ck)}; " +
                            $"catches lit {Catches(lk)}, dark {Catches(dk)}, careful {Catches(ck)}";
            Debug.Log("[INFO][test] " + totals);
            // Light used well beats light always by a wide margin, and never loses to light never (pillar 1).
            if (darkAsserted) Assert.GreaterOrEqual(careful, dark, "using the light well must never lose to never using it: " + totals);
            else if (careful < dark) Debug.Log($"[INFO][test] logged, not asserted: careful {careful} < always-dark {dark}");
            Assert.GreaterOrEqual(careful - lit, minGap, "using the light well must clearly beat always using it: " + totals);
            Assert.GreaterOrEqual(Escapes(ck), Escapes(lk), "careful must escape at least as often as always-lit: " + totals);
            // Light gets you seen: the always-lit keeper is caught far more often than the others
            if (litCaughtMost) Assert.Greater(Catches(lk), 2 * (Catches(dk) + Catches(ck)), totals);
        }

        [TearDown]
        public void Reset()
        {
            Time.captureFramerate = 0;
            GraveyardGame.Options = null;
        }

        // Each bot plays its nights; the comparison tests follow (NUnit runs these in name order, A to J).
        // A to D: the hand-made yard, the baseline measured before the generator existed.
        [UnityTest]
        public IEnumerator Smoke_A_AlwaysLitNights()
        {
            yield return Nights(BotMode.AlwaysLit, false);
        }

        [UnityTest]
        public IEnumerator Smoke_B_AlwaysDarkNights()
        {
            yield return Nights(BotMode.AlwaysDark, false);
        }

        [UnityTest]
        public IEnumerator Smoke_C_CarefulNights()
        {
            yield return Nights(BotMode.Careful, false);
        }

        [Test]
        public void Smoke_D_TheLanternIsAChoice()
        {
            // The 4x hand-made yard at Easy (8 ghosts), measured 2026-10-23 after the Kimi audit fixes: progress careful
            // 104, dark 104, lit 81 (of 104); escapes 8, 8, 0; catches careful 4, dark 0, lit 19. Night 0 is the easy
            // night: darkness costs no escapes here. On the old small yard lit was also caught twice as often as the
            // others together; on the big yard it loses by never getting out, so that ratio is logged, not asserted.
            // After the review fixes (2026-10-26): careful 104 (8 escapes, 5 catches), dark 104 (8, 0), lit 86 (0, 12);
            // one full run had careful 103 (one night at dawn with every soul): careful >= dark sits at the 104 cap.
            TheLanternIsAChoice(false, 10, false, true);
        }

        // E: the generator's walk grid (Core) against the real NavMesh, on the hand-made yard and 16 generated ones.
        // Every soul and the gate need a complete path from the start, and a ghost must get within
        // GhostBrain.Arrive of every route point, or it stands on that corner for the rest of the night.
        // The grid may be stricter than the NavMesh (it then only rejects good yards), never looser.
        [UnityTest]
        public IEnumerator Smoke_E_TheNavMeshAgreesWithTheWalkGrid()
        {
            var problems = new List<string>();   // the grid said yes, the NavMesh says no: the generator could ship a broken yard
            var stricter = new List<string>();   // the grid said no, the NavMesh says yes: safe, only throws away good yards
            var seeds = new[] { 0 }.Concat(Enumerable.Range(1, NavMeshNights).Select(LevelGenerator.SeedForNight)).ToList();
            int checks = 0;
            foreach (int seed in seeds)
            {
                GraveyardGame.Options = new LaunchOptions { Seed = seed, SavePath = SavePath };
                yield return SceneManager.LoadSceneAsync(Scene);
                yield return null;
                var game = GraveyardGame.Current;
                var yard = game.Yard;
                var grid = new WalkGrid(yard);
                Vector3 start = LevelBuilder.ToWorld(yard.KeeperStart);
                var targets = new List<(string, V2, float)>();
                for (int i = 0; i < yard.Souls.Count; i++) targets.Add(($"soul {i}", yard.Souls[i], game.Tuning.SoulPickupRadius));
                targets.Add(("gate", yard.Gate, game.Tuning.GateRadius));
                foreach (var (name, at, radius) in targets)
                {
                    checks++;
                    var path = new NavMeshPath();
                    bool ok = NavMesh.SamplePosition(start, out NavMeshHit from, 2f, NavMesh.AllAreas) &&
                              NavMesh.SamplePosition(LevelBuilder.ToWorld(at), out NavMeshHit to, radius, NavMesh.AllAreas) &&
                              NavMesh.CalculatePath(from.position, to.position, NavMesh.AllAreas, path) &&
                              path.status == NavMeshPathStatus.PathComplete;
                    bool gridOk = grid.ReachableNear(at, radius - WalkGrid.BakeMargin);
                    if (!ok && gridOk) problems.Add($"seed {seed}: no NavMesh path to the {name} {at}");
                    if (ok && !gridOk) stricter.Add($"seed {seed}: {name} {at}");
                }
                for (int r = 0; r < yard.GhostRoutes.Count; r++)
                {
                    foreach (var p in yard.GhostRoutes[r])
                    {
                        checks++;
                        bool near = NavMesh.SamplePosition(LevelBuilder.ToWorld(p), out NavMeshHit hit, 3f, NavMesh.AllAreas);
                        float d = near ? V2.Distance(LevelBuilder.ToGround(hit.position), p) : float.MaxValue;
                        bool gridOk = grid.ReachableNear(p, GhostBrain.Arrive - 0.05f);
                        if (d >= GhostBrain.Arrive && gridOk) problems.Add($"seed {seed}: ghost {r} cannot arrive at {p} (NavMesh {d:0.00} m away)");
                        if (d < GhostBrain.Arrive && !gridOk) stricter.Add($"seed {seed}: ghost {r} point {p} (NavMesh {d:0.00} m away)");
                    }
                }
            }
            var agent = NavMesh.GetSettingsByIndex(0);
            Debug.Log($"[INFO][test] navmesh agent: radius {agent.agentRadius}, climb {agent.agentClimb} (WalkGrid.KeeperRadius {WalkGrid.KeeperRadius})");
            Debug.Log($"[INFO][test] navmesh: {seeds.Count} yards, {checks} checks; the grid was looser {problems.Count}x" +
                      (problems.Count > 0 ? " (" + string.Join("; ", problems) + ")" : "") +
                      $", stricter {stricter.Count}x" + (stricter.Count > 0 ? " (" + string.Join("; ", stricter) + ")" : ""));
            Assert.IsEmpty(problems, "the walk grid let through what the NavMesh does not:\n" + string.Join("\n", problems));
        }

        // F to I: the first 8 generated nights a player gets (SeedForNight 1..8)
        [UnityTest]
        public IEnumerator Smoke_F_GeneratedAlwaysLitNights()
        {
            yield return Nights(BotMode.AlwaysLit, true);
        }

        [UnityTest]
        public IEnumerator Smoke_G_GeneratedAlwaysDarkNights()
        {
            yield return Nights(BotMode.AlwaysDark, true);
        }

        [UnityTest]
        public IEnumerator Smoke_H_GeneratedCarefulNights()
        {
            yield return Nights(BotMode.Careful, true);
        }

        [Test]
        public void Smoke_I_TheLanternIsAChoice_OnGeneratedNights()
        {
            // The 4x generated nights at Easy, measured 2026-10-23 after the Kimi audit fixes: progress careful 98, dark
            // 101, lit 45 (of 104); escapes 6, 7, 0; catches careful 8, dark 0, lit 25. Always-dark edges careful here, the
            // comparison bots cannot judge (they see in the dark), so it is logged; careful still beats lit by 53.
            // After the review fixes (2026-10-26, new yards): careful 96 (5 escapes, 23 catches), dark 103 (7, 6), lit 41 (0, 13).
            TheLanternIsAChoice(true, 10, false, false);
        }

        // K: nowhere to fall off. The keeper pushes for a few seconds at the shut gate and out of every corner of every
        // part of the outline, on the hand-made yard and a generated one, and must end up inside and on the ground.
        // (A playtester walked out of the open gate before collecting the souls and fell forever.)
        [UnityTest]
        public IEnumerator Smoke_K_TheYardHasNoWayOut()
        {
            var escapes = new List<string>();
            int pushed = 0;
            foreach (int seed in new[] { 0, NightSeeds[0] })
            {
                GraveyardGame.Options = new LaunchOptions { Seed = seed, SavePath = SavePath };
                yield return SceneManager.LoadSceneAsync(Scene);
                yield return null;
                var game = GraveyardGame.Current;
                var yard = game.Yard;
                var pushes = new List<(string name, V2 from, Vector2 dir)> { ("gate", yard.KeeperStart, new Vector2(0f, -1f)) };
                foreach (var area in yard.Areas)
                {
                    pushes.Add(($"{area} south-west", new V2(area.MinX + 1.25f, area.MinZ + 1.25f), new Vector2(-1f, -0.4f)));
                    pushes.Add(($"{area} south-east", new V2(area.MaxX - 1.25f, area.MinZ + 1.25f), new Vector2(1f, -0.4f)));
                    pushes.Add(($"{area} north-east", new V2(area.MaxX - 1.25f, area.MaxZ - 1.25f), new Vector2(1f, 0.4f)));
                    pushes.Add(($"{area} north-west", new V2(area.MinX + 1.25f, area.MaxZ - 1.25f), new Vector2(-1f, 0.4f)));
                }
                var keeper = game.Keeper;
                // Only this test moves the keeper: the game's own Update would call Move with no input each frame
                game.enabled = false;
                Time.captureFramerate = Fps;
                foreach (var push in pushes)
                {
                    keeper.Respawn(LevelBuilder.ToWorld(push.from) + Vector3.up * 0.1f);
                    for (int i = 0; i < Fps * 4; i++)
                    {
                        keeper.Move(push.dir, 1f / Fps);
                        yield return null;
                    }
                    var p = keeper.transform.position;
                    bool inside = p.y > -0.5f && yard.Inside(LevelBuilder.ToGround(p));
                    pushed++;
                    if (!inside) escapes.Add($"seed {seed} {push.name} at ({p.x:0.0}, {p.y:0.0}, {p.z:0.0})");
                }
            }
            // The gate opens for the last soul and swings shut again when a catch takes one away (playtest)
            var gate = Object.FindFirstObjectByType<GateSwing>();
            gate.Open();
            for (int i = 0; i < Fps * 2; i++) yield return null;
            Assert.IsTrue(gate.IsOpen, "the gate opened");
            Assert.Greater(Mathf.Abs(gate.Angle(0)), 90f, "the leaves swung out");
            gate.Close();
            for (int i = 0; i < Fps * 2; i++) yield return null;
            Assert.IsTrue(gate.IsShut, "the gate shut again");
            Assert.AreEqual(0f, gate.Angle(0), 0.01f, "the leaves are back on the wall line");

            // Caught with every soul in hand: the keeper wakes at the start, 3 m inside, and the gate shuts. A player
            // holding "down" ran out through the leaves while they swung (review, 2026-10-26). Through the game's own
            // event handling, lit (fast) and dark.
            var live = GraveyardGame.Current;
            var liveYard = live.Yard;
            var liveKeeper = live.Keeper;
            var night = live.Night;
            void Feed(List<NightEvent> events)
            {
                foreach (var e in events) live.OnEvent(e);
            }
            foreach (bool lit in new[] { true, false })
            {
                night.Tick(live.Tuning.CatchGraceSeconds + 0.1f, true, liveYard.KeeperStart, liveYard.Souls, liveYard.Gate, false);   // past any grace
                for (int i = 0; i < liveYard.Souls.Count; i++) Feed(night.Tick(1f / Fps, true, liveYard.Souls[i], liveYard.Souls, liveYard.Gate, false));
                Assert.IsTrue(night.AllCollected, "every soul in hand");
                for (int i = 0; i < Fps * 2; i++) yield return null;
                Assert.IsTrue(gate.IsOpen, "the last soul opened the gate");
                liveKeeper.SetLantern(lit);
                liveKeeper.Respawn(LevelBuilder.ToWorld(liveYard.KeeperStart));
                var caught = night.Tick(1f / Fps, true, liveKeeper.Ground, liveYard.Souls, liveYard.Gate, true, gate.IsOpen);
                CollectionAssert.Contains(caught, NightEvent.GateShut);
                Feed(caught);
                Assert.IsTrue(gate.IsShut, "the gate is shut in the same frame as the catch");
                for (int i = 0; i < Fps * 3; i++)
                {
                    liveKeeper.Move(new Vector2(0f, -1f), 1f / Fps);   // the player holds "down": toward the gate
                    yield return null;
                }
                var p = liveKeeper.transform.position;
                bool inside = p.y > -0.5f && liveYard.Inside(LevelBuilder.ToGround(p));
                pushed++;
                if (!inside) escapes.Add($"caught at the open gate, lantern {(lit ? "lit" : "out")}: out through the shutting gate at ({p.x:0.0}, {p.y:0.0}, {p.z:0.0})");
            }
            Debug.Log($"[INFO][test] no way out: {pushed} pushes, {escapes.Count} got out" + (escapes.Count > 0 ? ": " + string.Join("; ", escapes) : ""));
            Assert.IsEmpty(escapes, "the keeper got out of the yard: " + string.Join("; ", escapes));
        }

        // L: the difficulty changes the night: more ghosts each step, darker, and Insane black outside the lantern
        [UnityTest]
        public IEnumerator Smoke_L_EachDifficultyIsDarkerAndBusier()
        {
            int loops = -1;
            float lastAmbient = float.MaxValue;
            var report = new List<string>();
            foreach (Core.Difficulty d in System.Enum.GetValues(typeof(Core.Difficulty)))
            {
                GraveyardGame.Options = new LaunchOptions { Seed = NightSeeds[0], SavePath = SavePath, Difficulty = d };
                yield return SceneManager.LoadSceneAsync(Scene);
                yield return null;
                var game = GraveyardGame.Current;
                var settings = DifficultySettings.For(d);
                if (loops < 0) loops = game.Yard.GhostRoutes.Count;
                Assert.AreEqual(d, game.Difficulty.Level);
                Assert.AreEqual(loops + 2 * (int)d, game.Ghosts.Count, $"{d}: ghosts");
                // Skybox ambient ignores the colors below: every difficulty looked the same in the playtest
                Assert.AreEqual(AmbientMode.Trilight, RenderSettings.ambientMode, $"{d}: the difficulty owns the ambient light");
                float ambient = RenderSettings.ambientSkyColor.maxColorComponent;
                report.Add($"{d} {game.Ghosts.Count} ghosts, ambient {ambient:0.000}, reflections {RenderSettings.reflectionIntensity:0.00}");
                Assert.Less(ambient, lastAmbient, $"{d}: darker than the step before");
                lastAmbient = ambient;
                if (d == Core.Difficulty.Insane)
                {
                    Assert.AreEqual(0f, ambient + RenderSettings.ambientEquatorColor.maxColorComponent + RenderSettings.ambientGroundColor.maxColorComponent, "Insane: no ambient light");
                    Assert.AreEqual(0f, RenderSettings.reflectionIntensity, "Insane: no sky in the reflections");
                    // Kimi audit: the gate light stayed on (4 m) under "pitch black outside your lantern"
                    var lit = Object.FindObjectsByType<Light>(FindObjectsInactive.Exclude, FindObjectsSortMode.None)
                        .Where(x => x.enabled && x.intensity > 0f && !x.transform.IsChildOf(game.Keeper.transform)).ToList();
                    Assert.IsEmpty(lit, "Insane: no light but the keeper's: " + string.Join(", ", lit.Select(x => x.name)));
                }
            }
            Debug.Log("[INFO][test] difficulty: " + string.Join("; ", report));
        }

        // M: the keeper carries the lantern in his hand, and his legs walk with the lantern out (playtest: the light
        // floated at his side, and lantern out his legs froze in the kit's still crouch pose)
        [UnityTest]
        public IEnumerator Smoke_M_KeeperHoldsTheLanternAndWalksInTheDark()
        {
            GraveyardGame.Options = new LaunchOptions { Seed = 0, SavePath = SavePath };
            yield return SceneManager.LoadSceneAsync(Scene);
            yield return null;
            var game = GraveyardGame.Current;
            var keeper = game.Keeper;
            var hand = CharacterAnimator.FindBone(keeper.transform, "arm-right");
            Assert.IsNotNull(keeper.Lantern, "a lantern model");
            Assert.IsTrue(keeper.Lantern.IsChildOf(hand), "the lantern hangs from his right arm");
            Assert.IsTrue(keeper.LanternLight.transform.IsChildOf(keeper.Lantern), "the light is in the lantern");
            game.enabled = false;
            Time.captureFramerate = Fps;
            foreach (var anim in keeper.GetComponentsInChildren<Animation>()) anim.cullingType = AnimationCullingType.AlwaysAnimate;
            var leg = CharacterAnimator.FindBone(keeper.transform, "leg-left");
            var report = new List<string>();
            foreach (bool lit in new[] { true, false })
            {
                keeper.SetLantern(lit);
                float least = float.MaxValue, most = float.MinValue;
                for (int i = 0; i < Fps * 2; i++)
                {
                    keeper.Move(new Vector2(0f, 1f), 1f / Fps);
                    yield return null;
                    if (i < Fps / 2) continue;   // let the crossfade settle
                    float swing = Mathf.DeltaAngle(0f, leg.localEulerAngles.x);
                    least = Mathf.Min(least, swing);
                    most = Mathf.Max(most, swing);
                }
                report.Add($"{(lit ? "lit" : "dark")} leg swing {most - least:0} degrees");
                Assert.Greater(most - least, 20f, $"lantern {(lit ? "lit" : "out")}: the legs walk");
                Vector3 local = keeper.transform.InverseTransformPoint(keeper.Lantern.position);
                Assert.Greater(local.z, 0f, "the lantern is held in front of him");
            }
            Debug.Log("[INFO][test] keeper: " + string.Join("; ", report));
            // a close look from his right side and a little in front (dev.py smoke --filter Smoke_M --screenshot ...)
            var cam = Camera.main;
            Object.Destroy(cam.GetComponent<CameraRig>());
            keeper.SetLantern(true);
            var chest = keeper.Chest;
            cam.transform.position = chest + keeper.transform.right * 2.6f + keeper.transform.forward * 1.6f + Vector3.up * 0.4f;
            cam.transform.LookAt(chest - Vector3.up * 0.3f);
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.3f, 0.32f, 0.4f);
            GameKitCapture.Attach();
            for (int i = 0; i < 10; i++)
            {
                keeper.Move(Vector2.zero, 1f / Fps);
                yield return null;
            }
            GameKitCapture.Finish();
        }

        // N: the careful and always-dark bots at Normal, two ghosts more, logged and not judged: the bots ignore the
        // darkness that is most of what Normal adds, so this only shows how the extra ghosts move the numbers
        [UnityTest]
        [Timeout(1800000)]   // 32 nights; the default 3 minutes covers 8
        public IEnumerator Smoke_N_NormalNights_Logged()
        {
            if (Partial) Assert.Ignore("a capture run");
            foreach (bool generated in new[] { false, true })
            {
                yield return Nights(BotMode.Careful, generated, Core.Difficulty.Normal);
                yield return Nights(BotMode.AlwaysDark, generated, Core.Difficulty.Normal);
                string ck = Key(generated, BotMode.Careful, Core.Difficulty.Normal), dk = Key(generated, BotMode.AlwaysDark, Core.Difficulty.Normal);
                Debug.Log($"[INFO][test] {(generated ? "generated" : "hand-made")} at Normal (logged): progress careful {Progress(ck)}, " +
                          $"dark {Progress(dk)}; escapes careful {Escapes(ck)}, dark {Escapes(dk)}; catches careful {Catches(ck)}, dark {Catches(dk)}");
            }
        }

        // J: one generated yard seen from above with the fog off, for screenshots
        // (dev.py smoke --filter Smoke_J --screenshot ...). Without a capture it still checks the yard builds.
        [UnityTest]
        public IEnumerator Smoke_J_YardFromAbove()
        {
            int seed = Seeds(true)[0];
            GraveyardGame.Options = new LaunchOptions { Seed = seed, SavePath = SavePath };
            yield return SceneManager.LoadSceneAsync(Scene);
            yield return null;
            var game = GraveyardGame.Current;
            Assert.AreEqual(seed, game.NightSeed);
            Assert.IsFalse(game.Yard.HandMade, "a generated night");
            // The live HUD's seed label (what OnGUI draws; batch mode never calls OnGUI, so read it from the component)
            var hud = Object.FindFirstObjectByType<Hud>();
            Assert.IsNotNull(hud, "the HUD is in the scene");
            Assert.AreEqual($"SEED {seed}", hud.SeedLabel);
            Debug.Log($"[INFO][test] hud seed label: \"{hud.SeedLabel}\"");
            var cam = Camera.main;
            Object.Destroy(cam.GetComponent<CameraRig>());
            var bounds = game.Yard.Bounds;
            var middle = new Vector3((bounds.MinX + bounds.MaxX) * 0.5f, 0f, (bounds.MinZ + bounds.MaxZ) * 0.5f);
            float size = Mathf.Max(bounds.MaxX - bounds.MinX, (bounds.MaxZ - bounds.MinZ) * 1.6f);
            cam.transform.position = middle + new Vector3(0f, size * 0.95f, -size * 0.45f);
            cam.transform.LookAt(middle);
            cam.farClipPlane = 1000f;
            RenderSettings.fog = false;
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.35f, 0.38f, 0.5f);
            GameKitCapture.Attach();
            for (int i = 0; i < 10; i++) yield return null;
            GameKitCapture.Finish();
            Debug.Log($"[INFO][test] yard from above: seed {seed}, {game.Yard.Props.Count} props, attempts {game.Yard.Attempts}");
        }
    }
}
