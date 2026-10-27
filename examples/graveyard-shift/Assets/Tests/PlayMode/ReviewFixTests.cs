// ---------------------------------------------------------------------------
// ReviewFixTests.cs
// Purpose : PlayMode regression tests for the bugs a review proved on the real scene (2026-10-26): a catch
//           cascade at the start, cover that a keeper hides behind, a search that ends, a ghost that keeps
//           walking toward a spot it cannot reach, and bot nights that leave the player's save alone.
// Usage   : python tools/dev.py smoke                       (they are named Smoke_R*, so smoke runs them)
//           python tools/dev.py smoke --filter Smoke_R      (only these, about a minute)
// Notes   : Each test loads the scene with a temp save. Where only the test may move things it disables the
//           game loop (as Smoke_K does). The gate case lives in Smoke_K (ScenarioTests.cs), next to its pushes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace graveyard_shift.Tests
{
    public class ReviewFixTests
    {
        private const string Scene = "Graveyard";
        private const int Fps = 60;
        private const float Hug = 0.4f;   // m from a prop to the keeper's center: his CharacterController radius
        private static readonly float[] GhostGaps = { 2f, 4f, 7f };   // m between a ghost and the far side of the cover
        private static string SavePath => Path.Combine(Application.temporaryCachePath, "review_save.json");

        [TearDown]
        public void Reset()
        {
            Time.captureFramerate = 0;
            GraveyardGame.Options = null;
        }

        private static IEnumerator Load(int seed, BotMode? bot = null)
        {
            GraveyardGame.Options = new LaunchOptions
            {
                Seed = seed, HandMadeYard = seed == 0, Difficulty = Core.Difficulty.Easy, SavePath = SavePath, Bot = bot,
            };
            Time.captureFramerate = Fps;
            yield return SceneManager.LoadSceneAsync(Scene);
            yield return null;
        }

        // A ghost on the keeper's start caught him every frame (35 catches, 35 souls' worth, in a second): the respawn
        // put him back under it. One catch, then a grace; and a tired ghost never catches at all.
        [UnityTest]
        public IEnumerator Smoke_R1_OneTouchIsOneCatch_AndTiredGhostsNeverCatch()
        {
            yield return Load(0);
            var game = GraveyardGame.Current;
            var yard = game.Yard;
            for (int i = 0; i < 12; i++) game.Night.Tick(0f, true, yard.Souls[i], yard.Souls, yard.Gate, false);
            Assert.IsTrue(game.Night.AllCollected);
            var ghost = game.Ghosts[1];
            Vector3 start = LevelBuilder.ToWorld(yard.KeeperStart);
            Assert.IsTrue(ghost.GetComponent<NavMeshAgent>().Warp(start + new Vector3(0.5f, 0f, 0f)), "the ghost stands on the start");
            for (int f = 0; f < Fps; f++) yield return null;
            Debug.Log($"[INFO][test] a ghost on the start for 1 s: catches {game.Night.Catches}, souls {game.Night.Collected}");
            Assert.AreEqual(1, game.Night.Catches, "one catch, not one per frame");

            // Past the grace a ghost still on the keeper catches again (here it would at 1.5 s), unless it is tired: tire
            // them all (TiredSeconds outlasts the rest of the test), let the grace run out, then put one on the keeper
            foreach (var g in game.Ghosts) g.Brain.Tire();
            int before = game.Night.Catches;
            for (int f = 0; f < Fps * 2; f++) yield return null;
            Assert.IsFalse(game.Night.InGrace);
            ghost.GetComponent<NavMeshAgent>().Warp(game.Keeper.transform.position);
            for (int f = 0; f < Fps; f++) yield return null;
            Assert.AreEqual(before, game.Night.Catches, "a tired ghost never catches");
        }

        // Everything LevelCheck counts as cover hides a keeper pressed against its far side, from a ghost 2, 4 or 7 m
        // off. Low tombs, bevelled and broken stones and low rocks counted as cover and hid nobody (the sight line runs
        // from 1.3 m to the chest at 1.1 m); now they do not count.
        [UnityTest]
        public IEnumerator Smoke_R2_CoverHidesAKeeperPressedAgainstIt()
        {
            var seenThrough = new List<string>();
            var checkedModels = new HashSet<string>();
            var lowSeenThrough = new HashSet<string>();
            foreach (int seed in new[] { 0, LevelGenerator.SeedForNight(1) })
            {
                yield return Load(seed);
                var game = GraveyardGame.Current;
                var keeper = game.Keeper;
                var ghost = game.Ghosts[0];
                game.enabled = false;                                  // only this test moves things
                ghost.GetComponent<NavMeshAgent>().enabled = false;   // CanSee reads the transform alone
                var yard = game.Yard;
                foreach (string model in Footprint.Models.Where(m => m != "stone-wall" && m != "lightpost-single"))
                {
                    if (checkedModels.Contains(model)) continue;
                    // any turn will do: a blocker is the world-aligned box around the turned mesh, which is the footprint
                    int idx = yard.Props.FindIndex(p => p.Model == model && p.Yaw == 0f);
                    if (idx < 0) idx = yard.Props.FindIndex(p => p.Model == model);
                    if (idx < 0) continue;
                    checkedModels.Add(model);
                    var box = Footprint.Of(yard.Props[idx]);
                    float cx = (box.MinX + box.MaxX) * 0.5f;
                    foreach (float gap in GhostGaps)
                    {
                        // ghost south of the prop, keeper hugging its north side, on a line through its middle
                        ghost.transform.position = LevelBuilder.ToWorld(new V2(cx, box.MinZ - gap));
                        keeper.Respawn(LevelBuilder.ToWorld(new V2(cx, box.MaxZ + Hug)));
                        Physics.SyncTransforms();
                        if (!ghost.CanSee(keeper)) continue;
                        if (Footprint.IsCover(model)) seenThrough.Add($"{model} (seed {seed}) from {gap} m");
                        else lowSeenThrough.Add(model);
                    }
                }
            }
            Debug.Log($"[INFO][test] cover: checked {string.Join(", ", checkedModels.OrderBy(m => m))}; " +
                      $"seen over (not cover): {string.Join(", ", lowSeenThrough.OrderBy(m => m))}");
            Assert.IsEmpty(seenThrough, "cover that did not hide the keeper: " + string.Join(", ", seenThrough));
            foreach (string model in Footprint.Models.Where(Footprint.IsCover))
                Assert.IsTrue(checkedModels.Contains(model), $"{model} is cover but was in neither yard to check");
        }

        // A hunt that loses the keeper outside the wall (the NavMesh was baked with the gate shut) searched the doorway
        // forever: the search clock waited for the ghost to reach a spot it never could
        [UnityTest]
        public IEnumerator Smoke_R3_ASearchForAnUnreachableSpotEnds()
        {
            yield return Load(0);
            var game = GraveyardGame.Current;
            var keeper = game.Keeper;
            var ghost = game.Ghosts[0];
            Vector3 start = LevelBuilder.ToWorld(game.Yard.KeeperStart);
            Assert.IsTrue(ghost.GetComponent<NavMeshAgent>().Warp(start + new Vector3(0f, 0f, 5f)), "warped onto the NavMesh");
            ghost.transform.rotation = Quaternion.LookRotation(Vector3.back);
            int f = 0;
            while (ghost.Brain.State != GhostState.Hunt && f++ < Fps * 4) yield return null;
            Assert.AreEqual(GhostState.Hunt, ghost.Brain.State, "the ghost hunts");
            // Seen just outside the gate (the bars hide nothing), so the last seen spot is off the NavMesh; then gone, dark
            float wall = game.Yard.Areas[0].MinZ;
            keeper.Respawn(new Vector3(0f, 0f, wall - 1.5f));
            f = 0;
            while ((!ghost.SeesKeeper || game.Yard.Inside(ghost.Brain.LastSeen)) && f++ < Fps * 2) yield return null;
            Assert.IsFalse(game.Yard.Inside(ghost.Brain.LastSeen), $"the ghost saw the keeper outside (last seen {ghost.Brain.LastSeen})");
            keeper.SetLantern(false);
            keeper.Respawn(new Vector3(0f, 0f, wall - 25f));
            float searching = 0f, longest = 0f;
            for (int i = 0; i < Fps * 25; i++)
            {
                yield return null;
                searching = ghost.Brain.State == GhostState.Search ? searching + 1f / Fps : 0f;
                longest = Mathf.Max(longest, searching);
            }
            Debug.Log($"[INFO][test] search outside the gate: longest search {longest:0.0} s, now {ghost.Brain.State} at {ghost.Ground}");
            Assert.Greater(longest, 1f, "the ghost searched");
            Assert.LessOrEqual(longest, game.Tuning.SearchMaxSeconds + 0.5f, "a search gives up after SearchMaxSeconds");
        }

        // Asked for a new path every frame, a ghost whose path takes more than a frame to compute (here a spot past the
        // shut gate) stood still: each request restarted the computation. Measured on the old code: 0.0 m in 3 s, path
        // still pending. Driven as Think drives it, it walks.
        [UnityTest]
        public IEnumerator Smoke_R4_AGhostWalksTowardASpotItCannotReach()
        {
            yield return Load(0);
            var game = GraveyardGame.Current;
            game.enabled = false;
            var ghost = game.Ghosts[0];
            var agent = ghost.GetComponent<NavMeshAgent>();
            var yard = game.Yard;
            V2 from = yard.KeeperStart + new V2(0f, 8f);
            V2 outside = yard.Gate + new V2(0f, -4f);   // beyond the shut gate: no complete path
            Assert.IsTrue(agent.Warp(LevelBuilder.ToWorld(from)), "warped onto the NavMesh");
            for (int i = 0; i < Fps * 3; i++)
            {
                ghost.Drive(outside, game.Tuning.HuntSpeed);
                yield return null;
            }
            float walked = V2.Distance(ghost.Ground, from);
            Debug.Log($"[INFO][test] partial path: walked {walked:0.0} m in 3 s, status {agent.pathStatus}, now {V2.Distance(ghost.Ground, outside):0.0} m from the spot");
            Assert.Greater(walked, 4f, "the ghost walks toward the spot instead of standing still");
        }

        // An --autoplay run of the player moved the player's own save on (nightsPlayed, so their next yard)
        [UnityTest]
        public IEnumerator Smoke_R5_BotNightsLeaveTheSaveAlone()
        {
            if (File.Exists(SavePath)) File.Delete(SavePath);
            yield return Load(0, BotMode.Careful);
            var game = GraveyardGame.Current;
            game.enabled = false;
            game.OnEvent(NightEvent.Dawn);
            yield return null;
            Assert.IsFalse(File.Exists(SavePath), "a bot night wrote the save");

            yield return Load(0);
            game = GraveyardGame.Current;
            game.enabled = false;
            game.OnEvent(NightEvent.Dawn);
            yield return null;
            Assert.IsTrue(File.Exists(SavePath), "a player's night is saved");
            Assert.AreEqual(1, new SaveStore(SavePath).Load().nightsPlayed);
            File.Delete(SavePath);
        }
    }
}
